import mysql.connector
import pandas as pd
import warnings
warnings.filterwarnings('ignore')   # suppresses the pandas warning

conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="surbhi",       # ← change this
    database="crowd_ai"
)

query = "SELECT * FROM crowd_data"
query1 = "select *from timestamp_info"
df = pd.read_sql(query, conn, )
df1 = pd.read_sql(query1,conn)
#print(df.head(10))
#print("Shape:", df.shape)
#print("Columns:", df.columns)
print(type(df1.date[0]))

# step 1 — sort by time (ts_id is time order)
#df = df.sort_values(['cctv_id', 'ts_id'])

# step 2 — pick ONE camera to train on first
# camera cctv_id=11 is Camera K (Sanctum) — most important
#camera_df = df[df['cctv_id'] == 11]['crowd_value']

#print("\nCamera K crowd values (first 20):")
#print(camera_df.values[:20])
#print("Total readings for Camera K:", len(camera_df))