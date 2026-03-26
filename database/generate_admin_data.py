import mysql.connector
from datetime import date, time, timedelta
import random

conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="surbhi",        # ← change this
    database="crowd_ai"
)
cursor = conn.cursor()

print("Clearing old admin data...")
cursor.execute("DELETE FROM alerts")
cursor.execute("DELETE FROM crowd_data")
cursor.execute("DELETE FROM timestamp_info")
conn.commit()

# ── average people per camera (from your GNN files) ───────────────────────
temple_avg = {
    'A':55, 'B':42, 'C':78, 'D':24, 'E':38,
    'F':62, 'G':90, 'H':22, 'I':68, 'J':95,
    'K':80, 'L':45, 'M':40, 'N':55, 'O':8
}
depot_avg = {
    'A':32, 'B':18, 'C':48, 'D':29,
    'E':6,  'F':38, 'G':34
}

# ── realistic crowd multiplier by hour ────────────────────────────────────
def get_multiplier(hour, is_weekend, location_name):
    if "Temple" in location_name:
        # temple peaks morning pooja + evening aarti
        pattern = [
            0.3, 0.2, 0.1, 0.1, 0.2, 0.5,   # 0-5
            0.8, 1.0, 0.9, 0.8, 0.8, 0.8,   # 6-11
            0.9, 0.8, 0.8, 0.9, 1.0, 1.2,   # 12-17
            1.3, 1.1, 0.8, 0.6, 0.5, 0.4    # 18-23
        ]
        weekend_boost = 1.5
    else:
        # depot peaks morning + evening office rush
        pattern = [
            0.2, 0.1, 0.1, 0.1, 0.2, 0.6,   # 0-5
            1.1, 1.3, 1.0, 0.7, 0.6, 0.7,   # 6-11
            0.8, 0.7, 0.7, 0.8, 1.0, 1.3,   # 12-17
            1.2, 0.8, 0.6, 0.4, 0.3, 0.2    # 18-23
        ]
        weekend_boost = 0.7   # depot quieter on weekends

    mult = pattern[hour]
    if is_weekend:
        mult *= weekend_boost
    return mult

# ── threshold based on area capacity ──────────────────────────────────────
def get_risk(crowd_value, area_capacity):
    ratio = crowd_value / area_capacity if area_capacity > 0 else 0
    if ratio < 0.60:  return "SAFE"
    if ratio < 0.85:  return "MODERATE"
    return "HIGH"

def get_part_of_day(hour):
    if 5  <= hour < 12: return "morning"
    if 12 <= hour < 17: return "afternoon"
    if 17 <= hour < 21: return "evening"
    return "night"

# ── fetch all cameras with capacity ───────────────────────────────────────
cursor.execute("""
    SELECT cctv_id, location_name, cctv_label, area_capacity 
    FROM loc_part 
    ORDER BY location_name, cctv_label
""")
cameras = cursor.fetchall()
print(f"Found {len(cameras)} cameras in database")

# ── generate 30 days of timestamps ────────────────────────────────────────
start_date = date.today() - timedelta(days=30)
ts_rows    = []

for day_offset in range(30):
    current_date = start_date + timedelta(days=day_offset)
    for hour in range(24):
        ts_rows.append((
            current_date,
            time(hour, 0, 0),
            hour,
            get_part_of_day(hour)
        ))

cursor.executemany("""
    INSERT INTO timestamp_info (date, time_of_day, hour_number, part_of_day)
    VALUES (%s, %s, %s, %s)
""", ts_rows)
conn.commit()
print(f"✓ {len(ts_rows)} timestamps inserted (30 days x 24 hours)")

# ── fetch timestamp IDs back ───────────────────────────────────────────────
cursor.execute("""
    SELECT ts_id, date, hour_number 
    FROM timestamp_info 
    ORDER BY date, hour_number
""")
all_timestamps = cursor.fetchall()

# ── generate crowd readings ────────────────────────────────────────────────
crowd_rows = []

for (ts_id, ts_date, hour) in all_timestamps:
    is_weekend = ts_date.weekday() >= 5    # 5=Sat 6=Sun

    for (cctv_id, location_name, cctv_label, area_capacity) in cameras:

        # base average for this specific camera
        if "Temple" in location_name:
            base = temple_avg.get(cctv_label, 30)
        else:
            base = depot_avg.get(cctv_label, 20)

        # apply time pattern + small randomness
        mult  = get_multiplier(hour, is_weekend, location_name)
        crowd = max(0, int(base * mult) + random.randint(-8, 8))
        risk  = get_risk(crowd, area_capacity)

        crowd_rows.append((ts_id, cctv_id, crowd, risk))

# insert in batches of 5000 to avoid memory issues
batch_size = 5000
total      = len(crowd_rows)

for i in range(0, total, batch_size):
    batch = crowd_rows[i:i + batch_size]
    cursor.executemany("""
        INSERT INTO crowd_data (ts_id, cctv_id, crowd_value, risk_level)
        VALUES (%s, %s, %s, %s)
    """, batch)
    conn.commit()
    print(f"  inserted {min(i+batch_size, total)}/{total} crowd rows...")

print(f"✓ {total} crowd readings inserted")

# ── generate alerts for HIGH risk only ────────────────────────────────────
cursor.execute("""
    SELECT cd.crowd_id, cd.crowd_value, lp.cctv_label, 
           lp.location_name, lp.area_name, lp.area_capacity
    FROM crowd_data cd
    JOIN loc_part lp ON cd.cctv_id = lp.cctv_id
    WHERE cd.risk_level = 'HIGH'
""")
high_readings = cursor.fetchall()

alert_rows = []
for (crowd_id, crowd_value, cctv_label, location_name, area_name, area_capacity) in high_readings:
    note = (
        f"HIGH alert: {crowd_value} people at CAM-{cctv_label} "
        f"({area_name}, {location_name}). "
        f"Capacity: {area_capacity}. "
        f"Ratio: {round(crowd_value/area_capacity*100)}%"
    )
    alert_rows.append((crowd_id, note))

for i in range(0, len(alert_rows), batch_size):
    batch = alert_rows[i:i + batch_size]
    cursor.executemany("""
        INSERT INTO alerts (crowd_id, note) VALUES (%s, %s)
    """, batch)
    conn.commit()

print(f"✓ {len(alert_rows)} alerts generated")

# ── final summary ──────────────────────────────────────────────────────────
conn.close()
print(f"""
╔══════════════════════════════════════╗
  Admin database complete
  Cameras       : {len(cameras)}
  Days          : 30
  Timestamps    : {len(ts_rows)}
  Crowd readings: {total}
  Alerts        : {len(alert_rows)}
╚══════════════════════════════════════╝
""")