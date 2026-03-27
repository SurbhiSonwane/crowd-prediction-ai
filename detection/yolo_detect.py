"""
yolo_detect.py  —  Kairo AI | Dual-mode YOLO detector
  Mode 1: Demo video file  (for deployed CCTV nodes)
  Mode 2: PC webcam        (for live testing / development)

Run:
  python yolo_detect.py
  → You will be asked to choose mode and cctv_id at runtime
"""

import cv2
import time
from collections import deque
from datetime import datetime
from ultralytics import YOLO
import sys
import os

# ── Add parent folder to path so db.py is importable ─────────────────────────
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db

# ── Config ────────────────────────────────────────────────────────────────────
CONF_THRESHOLD  = 0.50   # Minimum YOLO confidence to count a person
SKIP_FRAMES     = 2      # Process every Nth frame (saves CPU)
WINDOW_SECONDS  = 600    # 10-minute window → then average & write to DB
PERSON_CLASS    = 0      # COCO class 0 = person

# ── Load model once ───────────────────────────────────────────────────────────
print("Loading YOLOv8 model...")
model = YOLO("yolov8n.pt")
print("✅ Model loaded.\n")


# ── Runtime prompts ───────────────────────────────────────────────────────────
def ask_mode() -> str:
    print("=" * 45)
    print("  Kairo AI — YOLO Detection")
    print("=" * 45)
    print("  [1]  Demo video file")
    print("  [2]  PC webcam (live)")
    print("=" * 45)
    while True:
        choice = input("Select mode (1 or 2): ").strip()
        if choice in ("1", "2"):
            return choice
        print("  ❌ Invalid — enter 1 or 2")


def ask_cctv_id() -> int:
    while True:
        val = input("Enter cctv_id for this session: ").strip()
        if val.isdigit() and int(val) > 0:
            return int(val)
        print("  ❌ Must be a positive integer")


def ask_video_path() -> str:
    while True:
        path = input("Enter video file path (e.g. videos/cam1.mp4): ").strip()
        if os.path.exists(path):
            return path
        print(f"  ❌ File not found: {path}")


# ── Detection helpers ─────────────────────────────────────────────────────────
def detect_and_draw(frame) -> tuple[int, object]:
    """Run YOLO on frame, draw boxes, return (person_count, annotated_frame)."""
    results = model(frame, verbose=False)
    count = 0
    for r in results:
        for box in r.boxes:
            if int(box.cls[0]) == PERSON_CLASS and float(box.conf[0]) >= CONF_THRESHOLD:
                count += 1
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, f"{float(box.conf[0]):.2f}",
                            (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX,
                            0.45, (0, 255, 0), 1)
    return count, frame


def draw_hud(frame, count: int, cam_info: dict,
             window_elapsed: float, avg_so_far: float, risk: str):
    """Draw info overlay on frame."""

    # Risk colour
    risk_color = {"LOW": (0, 200, 0), "MODERATE": (0, 165, 255), "HIGH": (0, 0, 255)}
    color = risk_color.get(risk, (255, 255, 255))

    h, w = frame.shape[:2]

    # Semi-transparent dark bar at top
    overlay = frame.copy()
    cv2.rectangle(overlay, (0, 0), (w, 100), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame, 0.55, 0, frame)

    label    = cam_info.get("cctv_label", "?")
    location = cam_info.get("location_name", "Unknown")
    capacity = cam_info.get("area_capacity", 0)

    time_left = max(0, int(WINDOW_SECONDS - window_elapsed))
    mins, secs = divmod(time_left, 60)

    cv2.putText(frame, f"Kairo AI  |  Cam {label} — {location}",
                (12, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    cv2.putText(frame, f"People: {count}  /  Capacity: {capacity}",
                (12, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 1)
    cv2.putText(frame, f"Avg (window): {avg_so_far:.1f}   Next DB write: {mins:02d}:{secs:02d}",
                (12, 82), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)

    # Risk badge — bottom right
    badge_text = f"  {risk}  "
    (tw, th), _ = cv2.getTextSize(badge_text, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    bx = w - tw - 16
    by = h - 20
    cv2.rectangle(frame, (bx - 6, by - th - 6), (bx + tw + 6, by + 6), color, -1)
    cv2.putText(frame, badge_text, (bx, by),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)

    return frame


# ── Main detection loop ───────────────────────────────────────────────────────
def run_detection(source, cctv_id: int, loop_video: bool = False):
    """
    source      : 0 (webcam) or a file path string
    cctv_id     : which DB camera row to use
    loop_video  : True for video files (restarts at end), False for webcam
    """
    cam_info = db.get_camera_info(cctv_id)
    if cam_info is None:
        print(f"❌ cctv_id={cctv_id} not found in loc_part table. Exiting.")
        return

    area_capacity = cam_info.get("area_capacity", 0)
    label         = cam_info.get("cctv_label", "?")
    location      = cam_info.get("location_name", "Unknown")

    print(f"\n🎥 Starting detection — Cam {label} | {location} | capacity={area_capacity}")
    print("   Press ESC to quit.\n")

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"❌ Cannot open source: {source}")
        return

    counts_window: deque[int] = deque()
    window_start = time.time()
    frame_idx    = 0
    try:
        while True:
            ret, frame = cap.read()

            if not ret:
                if loop_video:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    continue
                else:
                    print("📷 Camera stream ended.")
                    break

            frame_idx += 1
            if frame_idx % SKIP_FRAMES != 0:
                continue

        # ── Detect ────────────────────────────────────────────────────────────
            count, frame = detect_and_draw(frame)
            counts_window.append(count)

        # ── Compute running average & risk for HUD ────────────────────────────
            avg_so_far = sum(counts_window) / len(counts_window)

            alpha = 0.2
            if len(counts_window) == 1:
                smoothed = counts_window[-1]
            else:
                smoothed = alpha * counts_window[-1] + (1 - alpha) * avg_so_far
            risk       = db.compute_risk(int(smoothed), area_capacity)

        # ── HUD overlay ───────────────────────────────────────────────────────
            window_elapsed = time.time() - window_start
            frame = draw_hud(frame, count, cam_info, window_elapsed, avg_so_far, risk)

            cv2.imshow(f"Kairo AI | Cam {label} — {location}", frame)

            key = cv2.waitKey(1) & 0xFF

            if key == 27:   # ESC key
                print("\n⏹ Stopped by ESC.")
                break

            elif key == ord('q'):   # press 'q'
                print("\n⏹ Stopped by Q key.")
                break
    except KeyboardInterrupt:
        print("\n⏹ Stopped using CTRL+C")

        # ── 10-minute DB flush ────────────────────────────────────────────────
        if window_elapsed >= WINDOW_SECONDS:
            avg_count = int(sum(counts_window) / len(counts_window))
            dt        = datetime.now()
            ts_id     = db.get_or_create_ts_id(dt)
            record    = db.insert_crowd_record(ts_id, cctv_id, avg_count, area_capacity)

            print(f"[{dt.strftime('%H:%M:%S')}] ✅ DB write → "
                  f"crowd={avg_count}  risk={record['risk_level']}  ts_id={ts_id}")

            counts_window.clear()
            window_start = time.time()

    cap.release()
    cv2.destroyAllWindows()
    print("Detection ended.")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mode     = ask_mode()
    cctv_id  = ask_cctv_id()

    if mode == "1":
        # ── Video file mode ───────────────────────────────────────────────────
        video_path = ask_video_path()
        print(f"\n▶  Mode: Video file  |  cctv_id={cctv_id}  |  file={video_path}")
        run_detection(source=video_path, cctv_id=cctv_id, loop_video=True)

    else:
        # ── Webcam mode ───────────────────────────────────────────────────────
        print(f"\n▶  Mode: PC Webcam  |  cctv_id={cctv_id}")
        print("   Trying camera index 0 (default webcam)...")
        run_detection(source=0, cctv_id=cctv_id, loop_video=False)