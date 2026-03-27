import mysql.connector
import pandas as pd
import numpy as np
import warnings
import os
warnings.filterwarnings('ignore')

from sklearn.preprocessing import MinMaxScaler
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from tensorflow.keras.callbacks import EarlyStopping
import pickle

# ── connection ─────────────────────────────────────────────────────────────
conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="surbhi",       # ← change this
    database="crowd_ai"
)

print("Loading data from MySQL...")

# ── load crowd data joined with timestamp and camera info ──────────────────
crowd_query = """
    SELECT
        cd.crowd_value,
        ti.date,
        ti.hour_number,
        lp.cctv_id,
        lp.cctv_label,
        lp.location_name,
        lp.area_capacity
    FROM crowd_data cd
    JOIN timestamp_info ti ON cd.ts_id   = ti.ts_id
    JOIN loc_part       lp ON cd.cctv_id = lp.cctv_id
    ORDER BY lp.cctv_id, ti.date, ti.hour_number
"""
df = pd.read_sql(crowd_query, conn)

# ── load events ────────────────────────────────────────────────────────────
events_query = """
    SELECT location_name, event_date, crowd_multiplier
    FROM events
"""
events_df = pd.read_sql(events_query, conn)
conn.close()

print(f"✓ Loaded {len(df)} crowd rows")
print(f"✓ Loaded {len(events_df)} events")

# ── add time features ──────────────────────────────────────────────────────
df['date']         = pd.to_datetime(df['date'])
df['day_of_week']  = df['date'].dt.dayofweek   # 0=Monday 6=Sunday
df['is_weekend']   = (df['day_of_week'] >= 5).astype(int)

# ── add event flag ─────────────────────────────────────────────────────────
# merge events into main df
# if a date+location matches an event → use its multiplier, else 1.0
events_df['event_date'] = pd.to_datetime(events_df['event_date'])
events_df = events_df.rename(columns={'event_date': 'date'})

df = df.merge(
    events_df[['date', 'location_name', 'crowd_multiplier']],
    on=['date', 'location_name'],
    how='left'
)
df['crowd_multiplier'] = df['crowd_multiplier'].fillna(1.0)  # no event = 1.0

print("\nFeatures ready:")
print(df[['date','hour_number','day_of_week','is_weekend',
          'crowd_value','crowd_multiplier']].head(10))

# ══════════════════════════════════════════════════════════════════════════
# LSTM BUILDER FUNCTION
# same function used for both temple and depot
# ══════════════════════════════════════════════════════════════════════════

def build_and_train_lstm(location_name, df, window=10):
    print(f"\n{'='*50}")
    print(f"Training LSTM for: {location_name}")
    print(f"{'='*50}")

    # ── filter for this location ───────────────────────────────────────────
    loc_df = df[df['location_name'] == location_name].copy()
    print(f"Total rows for this location: {len(loc_df)}")

    # ── features and target ────────────────────────────────────────────────
    # features LSTM will learn from
    feature_cols = [
        'crowd_value',        # main signal
        'hour_number',        # what hour is it
        'day_of_week',        # monday to sunday
        'is_weekend',         # 0 or 1
        'crowd_multiplier',   # event signal
    ]

    # target = next crowd value (shift by -1 means next row)
    loc_df['target'] = loc_df.groupby('cctv_id')['crowd_value'].shift(-1)
    loc_df = loc_df.dropna(subset=['target'])   # remove last row per camera

    X_raw = loc_df[feature_cols].values
    y_raw = loc_df['target'].values

    print(f"Features shape: {X_raw.shape}")

    # ── scale all values between 0 and 1 ──────────────────────────────────
    # LSTM works much better with small numbers (0-1) than large ones
    scaler_X = MinMaxScaler()
    scaler_y = MinMaxScaler()

    X_scaled = scaler_X.fit_transform(X_raw)
    y_scaled = scaler_y.fit_transform(y_raw.reshape(-1, 1)).flatten()

    # ── create sequences ───────────────────────────────────────────────────
    # window=10 means: look at last 10 readings to predict next one
    # this is what LSTM needs — sequences, not single rows
    def make_sequences(X, y, window):
        Xs, ys = [], []
        for i in range(len(X) - window):
            Xs.append(X[i:i+window])    # 10 rows of features
            ys.append(y[i+window])      # next crowd value
        return np.array(Xs), np.array(ys)

    X_seq, y_seq = make_sequences(X_scaled, y_scaled, window)
    print(f"Sequences shape: X={X_seq.shape}, y={y_seq.shape}")

    # ── train/test split ───────────────────────────────────────────────────
    # 80% train, 20% test
    split      = int(len(X_seq) * 0.8)
    X_train    = X_seq[:split]
    X_test     = X_seq[split:]
    y_train    = y_seq[:split]
    y_test     = y_seq[split:]

    print(f"Train size: {len(X_train)}, Test size: {len(X_test)}")

    # ── build LSTM model ───────────────────────────────────────────────────
    # exactly as you specified:
    # memory size 64, dropout 0.2, dense 1 output
    model = Sequential([
        LSTM(64,
             input_shape=(window, len(feature_cols)),
             return_sequences=False),   # one output not sequence
        Dropout(0.2),                   # prevents overfitting
        Dense(1)                        # predicts one number (next crowd)
    ])

    model.compile(
        optimizer='adam',
        loss='mean_squared_error'                      # mean squared error for regression
    )

    model.summary()

    # ── train ──────────────────────────────────────────────────────────────
    early_stop = EarlyStopping(
        monitor='val_loss',
        patience=5,                     # stop if no improvement for 5 epochs
        restore_best_weights=True
    )

    history = model.fit(
        X_train, y_train,
        epochs=50,
        batch_size=32,
        validation_data=(X_test, y_test),
        callbacks=[early_stop],
        verbose=1
    )

    # ── evaluate ───────────────────────────────────────────────────────────
    loss = model.evaluate(X_test, y_test, verbose=0)
    print(f"\nTest loss (MSE): {loss:.4f}")

    # ── save model and scalers ────────────────────────────────────────────
    os.makedirs('models', exist_ok=True)

    # clean name for file
    name = location_name.replace(' ', '_').lower()

    model.save(f'models/lstm_{name}.h5')
    pickle.dump(scaler_X, open(f'models/scaler_X_{name}.pkl', 'wb'))
    pickle.dump(scaler_y, open(f'models/scaler_y_{name}.pkl', 'wb'))

    print(f"✓ Model saved: models/lstm_{name}.h5")
    print(f"✓ Scalers saved: models/scaler_X_{name}.pkl")
    print(f"✓ Scalers saved: models/scaler_y_{name}.pkl")

    return model, scaler_X, scaler_y

# ══════════════════════════════════════════════════════════════════════════
# PREDICTION FUNCTION
# call this from fusion layer
# ══════════════════════════════════════════════════════════════════════════

def predict_crowd(location_name, recent_10_readings):
    """
    Input:  location name + last 10 readings as list of dicts
    Output: predicted crowd count for next hour

    Each reading in list must have:
    {crowd_value, hour_number, day_of_week, is_weekend, crowd_multiplier}
    """
    name     = location_name.replace(' ', '_').lower()
    model    = __import__('tensorflow').keras.models.load_model(
                   f'models/lstm_{name}.h5')
    scaler_X = pickle.load(open(f'models/scaler_X_{name}.pkl', 'rb'))
    scaler_y = pickle.load(open(f'models/scaler_y_{name}.pkl', 'rb'))

    feature_cols = ['crowd_value','hour_number',
                    'day_of_week','is_weekend','crowd_multiplier']

    X = np.array([[r[f] for f in feature_cols] for r in recent_10_readings])
    X_scaled = scaler_X.transform(X)
    X_seq    = X_scaled.reshape(1, 10, len(feature_cols))

    pred_scaled = model.predict(X_seq, verbose=0)
    pred_actual = scaler_y.inverse_transform(pred_scaled)[0][0]

    return max(0, round(pred_actual))


# ══════════════════════════════════════════════════════════════════════════
# TRAIN BOTH MODELS
# ══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # train temple model
    temple_model, temple_sX, temple_sy = build_and_train_lstm(
        'Siddhivinayak Temple', df
    )

    # train depot model
    depot_model, depot_sX, depot_sy = build_and_train_lstm(
        'Dadar Bus Depot', df
    )

    print("\n" + "="*50)
    print("Both LSTM models trained and saved!")
    print("Files in models/ folder:")
    for f in os.listdir('models'):
        print(f"  {f}")