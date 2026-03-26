import mysql.connector
from datetime import date, timedelta
import random

conn = mysql.connector.connect(
    host="localhost",
    user="root",
    password="surbhi",    # ← change this
    database="crowd_ai"
)
cursor = conn.cursor()

# first clear the single day we manually inserted
cursor.execute("DELETE FROM location_crowd")

# ── location patterns ──────────────────────────────────────────────────────
# each location has a crowd pattern by hour
# these are realistic Mumbai patterns

locations = {
    "Siddhivinayak Temple": {
        "pattern": {6:120, 8:280, 10:210, 12:180, 14:90, 17:320, 18:410, 20:260, 21:140, 22:60},
        "weekend_multiplier": 1.5   # 50% more on weekends
    },
    "Dadar Bus Depot": {
        "pattern": {6:200, 7:340, 8:420, 10:280, 12:190, 14:160, 17:380, 18:450, 20:310, 22:80},
        "weekend_multiplier": 0.8   # less on weekends (fewer office commuters)
    },
    "Juhu Beach": {
        "pattern": {6:40, 8:80, 10:150, 12:200, 14:180, 17:350, 18:480, 19:420, 20:300, 21:120},
        "weekend_multiplier": 1.8   # much more on weekends
    },
    "Hanging Gardens": {
        "pattern": {6:80, 7:150, 8:120, 10:60, 12:40, 14:30, 16:90, 17:110, 19:70, 21:20},
        "weekend_multiplier": 1.4
    },
    "Wankhede Stadium": {
        "pattern": {9:20, 11:50, 13:100, 16:500, 18:8000, 19:32000, 20:28000, 21:15000, 22:3000, 23:200},
        "weekend_multiplier": 1.2
    },
    "NSCI Dome Worli": {
        "pattern": {9:10, 11:30, 13:80, 15:200, 17:2000, 19:8000, 20:10000, 21:9000, 22:5000, 23:800},
        "weekend_multiplier": 1.3
    }
}

def get_risk(count):
    if count <= 100:  return "SAFE"
    if count <= 250:  return "MODERATE"
    return "HIGH"

# ── generate 30 days of data ───────────────────────────────────────────────
rows = []
start_date = date.today() - timedelta(days=30)  # start 30 days ago

for day_offset in range(30):
    current_date = start_date + timedelta(days=day_offset)
    is_weekend   = current_date.weekday() >= 5   # 5=Sat, 6=Sun

    for location_name, config in locations.items():
        for hour, base_crowd in config["pattern"].items():

            # apply weekend multiplier
            if is_weekend:
                crowd = int(base_crowd * config["weekend_multiplier"])
            else:
                crowd = base_crowd

            # add randomness so data looks real
            crowd = max(0, crowd + random.randint(-15, 15))
            risk  = get_risk(crowd)

            rows.append((
                location_name,
                crowd,
                f"{hour:02d}:00:00",   # formats hour as 06:00:00
                current_date,
                risk
            ))

# insert all rows at once
cursor.executemany("""
    INSERT INTO location_crowd
    (location_name, current_crowd, recorded_time, date_of, risk_level)
    VALUES (%s, %s, %s, %s, %s)
""", rows)

conn.commit()

print(f"✓ {len(rows)} rows inserted into location_crowd")
print(f"  Date range: {start_date} to {date.today()}")
print(f"  Locations: {len(locations)}")
print(f"  Days: 30")
print(f"\nSample query to verify:")
print(f"  SELECT * FROM location_crowd WHERE location_name='Juhu Beach' ORDER BY date_of, recorded_time LIMIT 10;")

conn.close()