from db_helper   import get_conn
from risk_helper import get_risk, get_suggested_action
from lstm_helper import load_lstm_prediction

def fusion_admin_present(location_name, yolo_count, gnn_flow_score, cctv_id):
    conn   = get_conn()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT area_capacity FROM loc_part WHERE cctv_id = %s
    """, (cctv_id,))
    cam           = cursor.fetchone()
    area_capacity = cam['area_capacity'] if cam else 100

    lstm_pred         = load_lstm_prediction(location_name, conn) or yolo_count
    gnn_crowd         = int(gnn_flow_score * area_capacity)
    final_score       = round(0.50*yolo_count + 0.35*lstm_pred + 0.15*gnn_crowd)
    risk_level, ratio = get_risk(final_score, area_capacity)
    action            = get_suggested_action(risk_level, location_name)

    # save to fusion_output
    cursor.execute("""
        SELECT ts_id FROM timestamp_info
        WHERE date = CURDATE() AND hour_number = HOUR(NOW())
        LIMIT 1
    """)
    ts_row = cursor.fetchone()
    ts_id  = ts_row['ts_id'] if ts_row else None

    if ts_id:
        cursor.execute("""
            INSERT INTO fusion_output
            (cctv_id, ts_id, lstm_pred, final_score, risk_level, suggested_action)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (cctv_id, ts_id, lstm_pred,
              round(final_score/area_capacity, 3),
              risk_level, action))
        conn.commit()

    cursor.close()
    conn.close()

    return {
        "location"        : location_name,
        "cctv_id"         : cctv_id,
        "yolo_count"      : yolo_count,
        "lstm_prediction" : lstm_pred,
        "gnn_flow_score"  : gnn_flow_score,
        "final_score"     : final_score,
        "capacity"        : area_capacity,
        "occupancy_ratio" : round(ratio * 100, 1),
        "risk_level"      : risk_level,
        "suggested_action": action,
        "type"            : "PRESENT"
    }


def fusion_admin_future(fusion1_result, location_name, hours_ahead=1):
    from datetime import datetime
    conn   = get_conn()
    cursor = conn.cursor(dictionary=True)

    future_hour = (datetime.now().hour + hours_ahead) % 24

    # Ola/Uber signal
    cursor.execute("""
        SELECT COUNT(*) AS cnt FROM booking
        WHERE destination LIKE %s
        AND status = 'active'
        AND HOUR(estimated_arrival) = %s
    """, (f"%{location_name.split()[0]}%", future_hour))
    mob_row        = cursor.fetchone()
    booking_count  = mob_row['cnt'] if mob_row else 0
    mobility_crowd = booking_count * 3

    # social events signal — uses expected_crowd
    cursor.execute("""
        SELECT expected_crowd, event_name FROM social_events
        WHERE location_name LIKE %s
        AND event_date BETWEEN CURDATE() AND DATE_ADD(CURDATE(), INTERVAL 1 DAY)
        ORDER BY event_date ASC LIMIT 1
    """, (f"%{location_name.split()[0]}%",))
    event_row      = cursor.fetchone()
    event_name     = event_row['event_name']          if event_row else None
    expected_crowd = int(event_row['expected_crowd']) if event_row else 0

    base_capacity  = fusion1_result['capacity']
    event_mult     = min(3.5, round(expected_crowd/base_capacity, 1)) \
                     if expected_crowd > 0 else 1.0

    cursor.close()
    conn.close()

    lstm_base    = fusion1_result['lstm_prediction']
    future_crowd = round((lstm_base + mobility_crowd) * event_mult)
    risk_level, ratio = get_risk(future_crowd, base_capacity)
    action       = get_suggested_action(risk_level, location_name)

    return {
        "location"        : location_name,
        "hours_ahead"     : hours_ahead,
        "lstm_base"       : lstm_base,
        "mobility_signal" : mobility_crowd,
        "booking_count"   : booking_count,
        "event_name"      : event_name,
        "event_multiplier": event_mult,
        "future_crowd"    : future_crowd,
        "capacity"        : base_capacity,
        "occupancy_ratio" : round(ratio * 100, 1),
        "risk_level"      : risk_level,
        "suggested_action": action,
        "type"            : "FUTURE"
    }