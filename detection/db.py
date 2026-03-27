"""
db.py  —  MySQL helper for timestamp_info, loc_part, crowd_data
"""

import os
import mysql.connector
from mysql.connector import pooling
from datetime import datetime, time

# ── Connection pool ────────────────────────────────────────────────────────────
_pool = pooling.MySQLConnectionPool(
    pool_name="crowd_ai",
    pool_size=5,
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", 3306)),
    database=os.getenv("DB_NAME", "crowd_ai"),
    user=os.getenv("DB_USER", "root"),
    password=os.getenv("DB_PASSWORD", "surbhi"),
    autocommit=False,
)


def _get_conn():
    return _pool.get_connection()


# ── Risk level ─────────────────────────────────────────────────────────────────
SAFE_RATIO     = 0.60
MODERATE_RATIO = 0.85


def compute_risk(crowd_value: int, area_capacity: int) -> str:
    """
    Returns 'LOW', 'MODERATE', or 'HIGH' based on crowd vs capacity.
    Falls back to absolute thresholds if capacity is 0 or unknown.
    """
    if area_capacity and area_capacity > 0:
        ratio = crowd_value / area_capacity
        if ratio < SAFE_RATIO:
            return "LOW"
        elif ratio < MODERATE_RATIO:
            return "MODERATE"
        else:
            return "HIGH"
    # Fallback absolute thresholds
    if crowd_value < 20:
        return "LOW"
    elif crowd_value < 50:
        return "MODERATE"
    return "HIGH"


# ── Part-of-day helper ─────────────────────────────────────────────────────────
def _part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    return "night"


# ── timestamp_info ─────────────────────────────────────────────────────────────
def get_or_create_ts_id(dt: datetime) -> int:
    """
    Looks up an existing ts_id for the given datetime's hour bucket,
    or inserts a new row and returns the new ts_id.
    Hour bucket = same date + same hour (minute/second zeroed).
    """
    hour_bucket = dt.replace(minute=0, second=0, microsecond=0)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ts_id FROM timestamp_info
            WHERE date = %s AND time_of_day = %s AND hour_number = %s
            LIMIT 1
            """,
            (hour_bucket.date(), hour_bucket.time(), hour_bucket.hour),
        )
        row = cur.fetchone()
        if row:
            return row[0]

        # Insert new hourly slot
        cur.execute(
            """
            INSERT INTO timestamp_info (date, time_of_day, hour_number, part_of_day)
            VALUES (%s, %s, %s, %s)
            """,
            (
                hour_bucket.date(),
                hour_bucket.time(),
                hour_bucket.hour,
                _part_of_day(hour_bucket.hour),
            ),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


# ── loc_part ───────────────────────────────────────────────────────────────────
def get_camera_info(cctv_id: int) -> dict | None:
    """
    Returns dict with area_capacity (and other loc_part fields) for given cctv_id.
    Returns None if not found.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            "SELECT * FROM loc_part WHERE cctv_id = %s LIMIT 1", (cctv_id,)
        )
        return cur.fetchone()
    finally:
        conn.close()


# ── crowd_data ─────────────────────────────────────────────────────────────────
def insert_crowd_record(ts_id: int, cctv_id: int, crowd_value: int, area_capacity: int):
    """
    Inserts one row into crowd_data. Risk is computed here.
    """
    risk = compute_risk(crowd_value, area_capacity)
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO crowd_data (ts_id, cctv_id, crowd_value, risk_level)
            VALUES (%s, %s, %s, %s)
            """,
            (ts_id, cctv_id, crowd_value, risk),
        )
        conn.commit()
        return {"ts_id": ts_id, "cctv_id": cctv_id,
                "crowd_value": crowd_value, "risk_level": risk}
    finally:
        conn.close()
