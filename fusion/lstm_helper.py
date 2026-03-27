import numpy as np
import pickle
import warnings
warnings.filterwarnings('ignore')

def load_lstm_prediction(location_name, conn):
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT 
                AVG(cd.crowd_value)                        AS crowd_value,
                ti.hour_number,
                DAYOFWEEK(ti.date)-1                       AS day_of_week,
                CASE WHEN DAYOFWEEK(ti.date) IN (1,7)
                     THEN 1 ELSE 0 END                     AS is_weekend,
                MAX(IFNULL(e.crowd_multiplier, 1.0))       AS crowd_multiplier
            FROM crowd_data cd
            JOIN timestamp_info ti ON cd.ts_id   = ti.ts_id
            JOIN loc_part       lp ON cd.cctv_id = lp.cctv_id
            LEFT JOIN events    e  ON e.location_name = lp.location_name
                                   AND e.event_date   = ti.date
            WHERE lp.location_name = %s
            GROUP BY ti.ts_id, ti.hour_number, ti.date
            ORDER BY ti.date DESC, ti.hour_number DESC
            LIMIT 10
        """, (location_name,))

        rows = cursor.fetchall()
        cursor.close()

        if len(rows) < 10:
            return None

        rows = list(reversed(rows))

        name = location_name.replace(' ', '_').lower()

        import tensorflow as tf
        model    = tf.keras.models.load_model(f'models/lstm_{name}.h5')
        scaler_X = pickle.load(open(f'models/scaler_X_{name}.pkl', 'rb'))
        scaler_y = pickle.load(open(f'models/scaler_y_{name}.pkl', 'rb'))

        feature_cols = ['crowd_value','hour_number',
                        'day_of_week','is_weekend','crowd_multiplier']

        X           = np.array([[float(r[f]) for f in feature_cols] for r in rows])
        X_scaled    = scaler_X.transform(X)
        X_seq       = X_scaled.reshape(1, 10, len(feature_cols))
        pred_scaled = model.predict(X_seq, verbose=0)
        pred_actual = scaler_y.inverse_transform(pred_scaled)[0][0]

        return max(0, round(pred_actual))

    except Exception as e:
        print(f"LSTM prediction error: {e}")
        return None