"""
main.py  —  FastAPI backend for Kairo crowd detection
Run:  uvicorn main:app --reload --host 0.0.0.0 --port 8000

Flutter calls:
  POST /detection/start   { "cctv_id": 1, "video_path": "videos/cam1.mp4" }
  POST /detection/stop    { "cctv_id": 1 }
  GET  /detection/active
  GET  /cameras           → all rows from loc_part
  GET  /crowd/{cctv_id}   → latest N crowd_data rows for a camera
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import mysql.connector
import os

import detector
import db

app = FastAPI(title="Kairo AI Detection API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / Response models ──────────────────────────────────────────────────
class StartRequest(BaseModel):
    cctv_id: int
    video_path: str           # e.g. "videos/cam1.mp4"  (relative to server root)


class StopRequest(BaseModel):
    cctv_id: int


# ── Detection control ──────────────────────────────────────────────────────────
@app.post("/detection/start")
def start(req: StartRequest):
    """
    Called when Flutter user clicks a CCTV node on the map.
    Starts YOLO detection on the associated demo video.
    Crowd data is flushed to DB every 10 minutes automatically.
    """
    import pathlib
    if not pathlib.Path(req.video_path).exists():
        raise HTTPException(status_code=404,
                            detail=f"Video not found: {req.video_path}")

    cam_info = db.get_camera_info(req.cctv_id)
    if cam_info is None:
        raise HTTPException(status_code=404,
                            detail=f"cctv_id={req.cctv_id} not found in loc_part")

    result = detector.start_detection(req.cctv_id, req.video_path)
    return {**result, "camera": cam_info}


@app.post("/detection/stop")
def stop(req: StopRequest):
    """Stop detection for a specific camera."""
    return detector.stop_detection(req.cctv_id)


@app.get("/detection/active")
def active():
    """Returns list of cctv_ids currently running detection."""
    return {"active_cameras": detector.list_active()}


# ── Camera / location info ─────────────────────────────────────────────────────
@app.get("/cameras")
def get_cameras():
    """
    Returns all cameras from loc_part.
    Flutter uses this to draw nodes on the map.
    """
    conn = db._get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute("SELECT * FROM loc_part ORDER BY cctv_id")
        return {"cameras": cur.fetchall()}
    finally:
        conn.close()


@app.get("/cameras/{cctv_id}")
def get_camera(cctv_id: int):
    cam = db.get_camera_info(cctv_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    return cam


# ── Crowd data ─────────────────────────────────────────────────────────────────
@app.get("/crowd/{cctv_id}")
def get_crowd(cctv_id: int, limit: int = 20):
    """
    Returns latest `limit` crowd_data rows for a camera,
    joined with timestamp_info for human-readable time.
    """
    conn = db._get_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(
            """
            SELECT
                cd.crowd_id,
                cd.crowd_value,
                cd.risk_level,
                ti.date,
                ti.time_of_day,
                ti.hour_number,
                ti.part_of_day
            FROM crowd_data cd
            JOIN timestamp_info ti ON ti.ts_id = cd.ts_id
            WHERE cd.cctv_id = %s
            ORDER BY cd.crowd_id DESC
            LIMIT %s
            """,
            (cctv_id, limit),
        )
        rows = cur.fetchall()
        # Convert date/time objects to strings for JSON serialisation
        for r in rows:
            if r.get("date"):
                r["date"] = str(r["date"])
            if r.get("time_of_day"):
                r["time_of_day"] = str(r["time_of_day"])
        return {"cctv_id": cctv_id, "records": rows}
    finally:
        conn.close()


@app.get("/crowd/{cctv_id}/latest")
def get_latest_crowd(cctv_id: int):
    """Returns only the most recent crowd record for quick dashboard polling."""
    result = get_crowd(cctv_id, limit=1)
    records = result.get("records", [])
    if not records:
        raise HTTPException(status_code=404, detail="No data yet for this camera")
    return records[0]


# ── Health check ───────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status": "ok"}
