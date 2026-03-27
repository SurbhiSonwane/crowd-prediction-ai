from datetime import datetime, date
from db_helper   import get_conn
from risk_helper import user_risk, best_time_advice

def fusion_user(user_location, destination, travel_time_mins=None):
    conn   = get_conn()
    cursor = conn.cursor(dictionary=True)

    current_hour = datetime.now().hour
    today        = date.today()
    is_weekend   = 1 if today.weekday() >= 5 else 0

    # travel time
    if travel_time_mins is None:
        travel_map = {
            ("Andheri",    "Juhu Beach")      : 15,
            ("Andheri",    "Gateway of India"): 55,
            ("Andheri",    "Wankhede Stadium"): 50,
            ("Bandra",     "Juhu Beach")      : 20,
            ("Bandra",     "Gateway of India"): 35,
            ("Bandra",     "Wankhede Stadium"): 30,
            ("Dadar",      "Gateway of India"): 25,
            ("Dadar",      "Juhu Beach")      : 30,
            ("Dadar",      "Wankhede Stadium"): 20,
            ("Colaba",     "Gateway of India"): 10,
            ("Colaba",     "Wankhede Stadium"): 15,
            ("Kurla",      "Wankhede Stadium"): 35,
            ("Lower Parel","Wankhede Stadium"): 15,
        }
        travel_time_mins = travel_map.get((user_location, destination), 30)

    traffic = {7:0.5, 8:0.4, 9:0.5, 17:0.4, 18:0.4, 19:0.5, 20:0.7}
    factor        = traffic.get(current_hour, 1.0)
    actual_travel = round(travel_time_mins / factor)
    arrival_hour  = (current_hour + (actual_travel // 60)) % 24

    # current crowd
    cursor.execute("""
        SELECT current_crowd FROM location_crowd
        WHERE location_name LIKE %s AND date_of = %s
        ORDER BY ABS(HOUR(recorded_time) - %s) ASC LIMIT 1
    """, (f"%{destination.split()[0]}%", today, current_hour))
    row           = cursor.fetchone()
    current_crowd = row['current_crowd'] if row else 150

    # crowd at arrival time (historical average for that hour)
    cursor.execute("""
        SELECT AVG(current_crowd) AS avg
        FROM location_crowd
        WHERE location_name LIKE %s
        AND HOUR(recorded_time) = %s
    """, (f"%{destination.split()[0]}%", arrival_hour))
    arr_row       = cursor.fetchone()
    arrival_crowd = int(arr_row['avg']) if arr_row and arr_row['avg'] else current_crowd

    # Ola/Uber signal
    cursor.execute("""
        SELECT COUNT(*) AS cnt FROM booking
        WHERE destination LIKE %s
        AND status = 'active'
        AND HOUR(estimated_arrival) = %s
    """, (f"%{destination.split()[0]}%", arrival_hour))
    mob_row       = cursor.fetchone()
    mobility_add  = (mob_row['cnt'] * 3) if mob_row else 0

    # social events
    cursor.execute("""
        SELECT expected_crowd, event_name FROM social_events
        WHERE location_name LIKE %s AND event_date = %s
        ORDER BY expected_crowd DESC LIMIT 1
    """, (f"%{destination.split()[0]}%", today))
    ev_row         = cursor.fetchone()
    event_name     = ev_row['event_name']          if ev_row else None
    expected_crowd = int(ev_row['expected_crowd']) if ev_row else 0
    event_mult     = min(3.5, round(expected_crowd/500, 1)) \
                     if expected_crowd > 0 else 1.0

    # alternatives
    cursor.execute("""
        SELECT alt_location_1, alt_location_2
        FROM mumbai_locations
        WHERE name LIKE %s LIMIT 1
    """, (f"%{destination.split()[0]}%",))
    alt_row      = cursor.fetchone()
    alternatives = [alt_row['alt_location_1'],
                    alt_row['alt_location_2']] if alt_row else []

    cursor.close()
    conn.close()

    predicted_arrival = round((arrival_crowd + mobility_add) * event_mult)
    current_risk      = user_risk(current_crowd)
    arrival_risk      = user_risk(predicted_arrival)

    return {
        "destination"             : destination,
        "user_location"           : user_location,
        "travel_time_mins"        : actual_travel,
        "arrival_hour"            : f"{arrival_hour:02d}:00",
        "current_crowd"           : current_crowd,
        "current_risk"            : current_risk,
        "predicted_crowd_arrival" : predicted_arrival,
        "arrival_risk"            : arrival_risk,
        "mobility_added"          : mobility_add,
        "event_name"              : event_name,
        "event_multiplier"        : event_mult,
        "alternatives"            : alternatives,
        "avoid_if"                : arrival_risk == "HIGH",
        "best_time_advice"        : best_time_advice(arrival_risk, arrival_hour)
    }