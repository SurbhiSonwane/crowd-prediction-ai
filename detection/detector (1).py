"""
detector.py  —  Kairo AI | YOLO Detection Engine

Flow:
  Flutter taps node → chooses "Video File" or "PC Camera"
       ↓
  POST /detection/start  { cctv_id, video_path }   ("0" = webcam)
       ↓
  FastAPI calls detector.start_detection()
       ↓
  Background thread starts:
    • cv2 window opens on PC showing live detections
    • Averages count over 10-minute window
    • Writes to crowd_data every 10 min automatically
    • Multiple nodes can run simultaneously (one thread each)
       ↓
  POST /detection/stop  { cctv_id }  (when Flutter closes the dialog)
"""

import cv2
import time
import threading
from collections import deque
from datetime import datetime
from ultralytics import YOLO
import db

# ── Model loaded once, shared across all threads ───────────────────────────────
print("[detector] Loading YOLOv8n model...")
_model = YOLO("yolov8n.pt")
print("[detector] ✅ Model ready.")

# ── Config ─────────────────────────────────────────────────────────────────────
CONF_THRESHOLD  = 0.50   # Min YOLO confidence to count a person
SKIP_FRAMES     = 2      # Process every Nth frame (performance)
WINDOW_SECONDS  = 600    # 10-minute window → DB write
PERSON_CLASS    = 0      # COCO class 0 = person

# ── Thread registry  (cctv_id → thread / stop_event) ──────────────────────────
_threads:    dict[int, threading.Thread] = {}
_stop_flags: dict[int, threading.Event] = {}
_registry_lock = threading.Lock()        # protect dict access across threads


# ── Detection helpers ──────────────────────────────────────────────────────────
def _detect_and_draw(frame) -> int:
    """Run YOLO on one frame, draw green boxes, return person count."""
    results = _model(frame, verbose=False)
    count = 0
    for r in results:
        for box in r.boxes:
            if int(box.cls[0]) == PERSON_CLASS and float(box.conf[0]) >= CONF_THRESHOLD:
                count += 1
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(
                    frame, f"{float(box.conf[0]):.2f}",
                    (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1
                )
    return count


def _draw_hud(frame, count: int, cam_info: dict,
              elapsed: float, avg: float, risk: str):
    """Overlay info bar + risk badge on frame."""
    RISK_COLORS = {
        "LOW":      (0, 200, 0),
        "MODERATE": (0, 165, 255),
        "HIGH":     (0, 0, 255),
    }
    color    = RISK_COLORS.get(risk, (200, 200, 200))
    h, w     = frame.shape[:2]
    label    = cam_info.get("cctv_label", "?")
    location = cam_info.get("location_name", "Unknown")
    capacity = cam_info.get("area_capacity", 0)

    # Semi-transparent top bar
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 95), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    # Countdown to next DB write
    time_left   = max(0, int(WINDOW_SECONDS - elapsed))
    mins, secs  = divmod(time_left, 60)

    cv2.putText(frame, f"Kairo AI  |  CAM-{label}  —  {location}",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2)
    cv2.putText(frame, f"People: {count}   Capacity: {capacity}   Avg(window): {avg:.1f}",
                (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
    cv2.putText(frame, f"Next DB write: {mins:02d}:{secs:02d}",
                (10, 76), cv2.FONT_HERSHEY_SIMPLEX, 0.50, (150, 150, 150), 1)

    # Risk badge — bottom right
    badge = f"  {risk}  "
    (tw, th), _ = cv2.getTextSize(badge, cv2.FONT_HERSHEY_SIMPLEX, 0.65, 2)
    bx = w - tw - 14
    by = h - 16
    cv2.rectangle(frame, (bx - 6, by - th - 6), (bx + tw + 6, by + 8), color, -1)
    cv2.putText(frame, badge, (bx, by),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 0), 2)

    return frame


# ── Core detection loop (runs in background thread) ───────────────────────────
def _detection_loop(cctv_id: int, source, stop_event: threading.Event):
    """
    source = 0 (webcam) or a video file path string.
    Runs until stop_event is set (Flutter calls /detection/stop).
    One thread per node — multiple can run in parallel.
    """
    cam_info = db.get_camera_info(cctv_id)
    if cam_info is None:
        print(f"[detector] ❌ cctv_id={cctv_id} not found in loc_part. Aborting.")
        return

    area_capacity = cam_info.get("area_capacity", 0)
    label         = cam_info.get("cctv_label", "?")
    location      = cam_info.get("location_name", "Unknown")
    window_title  = f"Kairo AI  |  CAM-{label}  —  {location}"
    loop_video    = isinstance(source, str)   # loop file, not webcam

    print(f"[detector] ▶ Started  CAM-{label} | {location} | source={source}")

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[detector] ❌ Cannot open source: {source}")
        return

    counts_window: deque[int] = deque()
    window_start = time.time()
    frame_idx    = 0

    while not stop_event.is_set():
        ret, frame = cap.read()

        if not ret:
            if loop_video:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                continue
            else:
                print(f"[detector] 📷 Camera stream ended — CAM-{label}")
                break

        frame_idx += 1
        if frame_idx % SKIP_FRAMES != 0:
            continue

        # ── Detect ────────────────────────────────────────────────────────────
        count = _detect_and_draw(frame)
        counts_window.append(count)

        # ── HUD ───────────────────────────────────────────────────────────────
        elapsed   = time.time() - window_start
        avg       = sum(counts_window) / len(counts_window)
        risk      = db.compute_risk(int(avg), area_capacity)
        frame     = _draw_hud(frame, count, cam_info, elapsed, avg, risk)

        # ── Show cv2 window (stays open on PC) ────────────────────────────────
        cv2.imshow(window_title, frame)
        key = cv2.waitKey(1)
        if key == 27:                          # ESC closes this camera's window
            print(f"[detector] ESC pressed — closing CAM-{label}")
            break

        # ── 10-min DB flush ───────────────────────────────────────────────────
        if elapsed >= WINDOW_SECONDS:
            avg_count = int(sum(counts_window) / len(counts_window))
            dt        = datetime.now()
            ts_id     = db.get_or_create_ts_id(dt)
            record    = db.insert_crowd_record(
                            ts_id, cctv_id, avg_count, area_capacity)
            print(f"[detector] ✅ DB write  CAM-{label} → "
                  f"crowd={avg_count}  risk={record['risk_level']}  "
                  f"ts_id={ts_id}  time={dt.strftime('%H:%M:%S')}")
            counts_window.clear()
            window_start = time.time()

    # ── Cleanup ───────────────────────────────────────────────────────────────
    cap.release()
    cv2.destroyWindow(window_title)

    # Remove from registry
    with _registry_lock:
        _threads.pop(cctv_id, None)
        _stop_flags.pop(cctv_id, None)

    print(f"[detector] ⏹  Stopped  CAM-{label}")


# ── Public API (called by FastAPI) ─────────────────────────────────────────────
def start_detection(cctv_id: int, source) -> dict:
    """
    Starts a background detection thread for one node.
    source = 0 (webcam) or video file path string.
    If this node already has a running thread, it is stopped first.
    Multiple nodes can run simultaneously — each gets its own thread + cv2 window.
    """
    # Stop existing thread for this node if any
    stop_detection(cctv_id)

    stop_event = threading.Event()

    t = threading.Thread(
        target=_detection_loop,
        args=(cctv_id, source, stop_event),
        daemon=True,
        name=f"kairo-cam-{cctv_id}",
    )

    with _registry_lock:
        _stop_flags[cctv_id] = stop_event
        _threads[cctv_id]    = t

    t.start()

    source_label = "webcam" if source == 0 else str(source)
    return {
        "status":   "started",
        "cctv_id":  cctv_id,
        "source":   source_label,
        "message":  f"Detection started. cv2 window will open on server PC.",
    }


def stop_detection(cctv_id: int) -> dict:
    """
    Signals a camera's detection thread to stop.
    The cv2 window for that camera closes automatically.
    """
    with _registry_lock:
        event = _stop_flags.get(cctv_id)

    if event:
        event.set()
        # Give thread a moment to clean up
        t = _threads.get(cctv_id)
        if t:
            t.join(timeout=3.0)
        return {"status": "stopped", "cctv_id": cctv_id}

    return {"status": "not_running", "cctv_id": cctv_id}


def stop_all() -> dict:
    """Stop every running detection thread (e.g. on server shutdown)."""
    ids = list(_threads.keys())
    for cctv_id in ids:
        stop_detection(cctv_id)
    return {"status": "all_stopped", "stopped": ids}


def list_active() -> list[int]:
    """Returns cctv_ids that currently have a live detection thread."""
    with _registry_lock:
        return list(_threads.keys())
