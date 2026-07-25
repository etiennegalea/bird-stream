#!/usr/bin/env python3
"""Local detection tester — run the active YOLO model on your Mac webcam.

Opens the webcam, runs the same model the app uses (DETECTION_MODEL), and serves
an annotated live preview (bounding boxes + labels + FPS) at:

    http://localhost:8060

It streams MJPEG to the browser instead of opening a native window, so it works
with the project's headless OpenCV — no extra GUI libraries required.

Setup (macOS), from the backend/ directory:

    uv sync --group detection            # installs ultralytics + CPU torch
    uv run python scripts/detect_webcam.py
    # then open http://localhost:8060  (first run downloads the model weights)

Or in one step:  make detect-webcam        (from the repo root)

Config — CLI flags, or the app's DETECTION_* env vars as defaults:

    --source   DETECTION_STREAM_URL   webcam device index (default 0)
    --model    DETECTION_MODEL        ultralytics model (default yolo11n.pt)
    --conf     DETECTION_CONF         min confidence (default 0.4)
    --classes  DETECTION_CLASSES      comma-separated COCO names; EMPTY = all
                                      classes (this tester defaults to all so you
                                      can verify it works at your desk without a
                                      real bird in frame). Use "bird" to match
                                      the production config.
    --port     DETECT_PREVIEW_PORT    HTTP port (default 8060)

Press Ctrl-C in the terminal to stop.

macOS note: the first run triggers a camera-permission prompt for your terminal.
If capture fails, grant access in System Settings → Privacy & Security → Camera.
"""

import argparse
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import cv2

try:
    from ultralytics import YOLO
except ImportError:
    sys.exit(
        "ultralytics is not installed. From the backend/ directory run:\n"
        "    uv sync --group detection\n"
        "then re-run with:  uv run python scripts/detect_webcam.py"
    )


class _Shared:
    """Latest annotated JPEG frame, shared between the worker and HTTP threads."""

    def __init__(self):
        self.lock = threading.Lock()
        self.jpeg: bytes | None = None
        self.stop = threading.Event()


shared = _Shared()

_INDEX_HTML = b"""<!doctype html><html><head><meta charset="utf-8">
<title>Bird detection - webcam</title>
<style>
  body{margin:0;background:#111;color:#eee;font-family:-apple-system,sans-serif;text-align:center}
  h1{font-size:.95rem;font-weight:600;padding:.6rem;margin:0;color:#E87530}
  img{max-width:100%;height:auto;display:block;margin:0 auto}
</style></head><body>
<h1>Detection preview &mdash; press Ctrl-C in the terminal to stop</h1>
<img src="/stream" alt="detection stream">
</body></html>"""


def _resolve_class_ids(model, classes_str: str):
    """Map requested COCO class names to model ids. Empty string -> all classes."""
    wanted = {c.strip().lower() for c in classes_str.split(",") if c.strip()}
    if not wanted:
        return None  # detect everything
    name_to_id = {v.lower(): k for k, v in model.names.items()}
    ids = [name_to_id[c] for c in wanted if c in name_to_id]
    missing = wanted - set(name_to_id)
    if missing:
        print(f"[warn] classes not in model vocabulary, ignored: {sorted(missing)}")
    if not ids:
        print("[warn] no valid classes requested; detecting ALL classes")
        return None
    return ids


def _open_camera(source: str):
    idx = int(source) if str(source).isdigit() else source
    cap = cv2.VideoCapture(idx)  # default backend: AVFoundation (macOS) / V4L2 (Linux)
    return cap if cap.isOpened() else None


def _worker(model, class_ids, args):
    cap = _open_camera(args.source)
    if cap is None:
        print(
            f"\n[error] Could not open camera source {args.source!r}.\n"
            "  • On macOS, grant camera access to your terminal in\n"
            "    System Settings -> Privacy & Security -> Camera, then re-run.\n"
            "  • Try a different index with --source 1.\n"
        )
        shared.stop.set()
        return

    print(f"Camera {args.source} opened. Serving preview at "
          f"http://localhost:{args.port}")
    fps = 0.0
    last = time.time()
    while not shared.stop.is_set():
        ok, frame = cap.read()
        if not ok:
            time.sleep(0.05)
            continue
        results = model.predict(frame, conf=args.conf, classes=class_ids,
                                verbose=False)
        annotated = results[0].plot()  # BGR frame with boxes/labels drawn
        n = len(results[0].boxes)

        now = time.time()
        dt = now - last
        last = now
        if dt > 0:
            fps = fps * 0.9 + (1.0 / dt) * 0.1
        cv2.putText(annotated, f"{fps:4.1f} FPS  |  {n} detection(s)",
                    (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
                    cv2.LINE_AA)

        ok2, buf = cv2.imencode(".jpg", annotated,
                                [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok2:
            with shared.lock:
                shared.jpeg = buf.tobytes()

    cap.release()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # silence per-request logging

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(_INDEX_HTML)
            return
        if self.path == "/stream":
            self.send_response(200)
            self.send_header(
                "Content-Type",
                "multipart/x-mixed-replace; boundary=frame")
            self.end_headers()
            try:
                while not shared.stop.is_set():
                    with shared.lock:
                        buf = shared.jpeg
                    if buf is None:
                        time.sleep(0.03)
                        continue
                    self.wfile.write(b"--frame\r\n")
                    self.wfile.write(b"Content-Type: image/jpeg\r\n")
                    self.wfile.write(
                        f"Content-Length: {len(buf)}\r\n\r\n".encode())
                    self.wfile.write(buf)
                    self.wfile.write(b"\r\n")
                    time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                return
            return
        self.send_response(404)
        self.end_headers()


def main():
    ap = argparse.ArgumentParser(description="Run YOLO detection on the webcam.")
    ap.add_argument("--source",
                    default=os.environ.get("DETECTION_STREAM_URL", "0"),
                    help="webcam device index (default 0)")
    ap.add_argument("--model",
                    default=os.environ.get("DETECTION_MODEL", "yolo11n.pt"),
                    help="ultralytics model name/path (default yolo11n.pt)")
    ap.add_argument("--conf", type=float,
                    default=float(os.environ.get("DETECTION_CONF", "0.4")),
                    help="minimum confidence (default 0.4)")
    ap.add_argument("--classes",
                    default=os.environ.get("DETECTION_CLASSES", ""),
                    help="comma-separated COCO names; empty = all classes")
    ap.add_argument("--port", type=int,
                    default=int(os.environ.get("DETECT_PREVIEW_PORT", "8060")),
                    help="HTTP preview port (default 8060)")
    args = ap.parse_args()

    print(f"Loading model {args.model!r} (auto-downloads on first run)...")
    model = YOLO(args.model)
    class_ids = _resolve_class_ids(model, args.classes)
    print("Detecting: " +
          ("ALL classes" if class_ids is None
           else ", ".join(model.names[i] for i in class_ids)))

    worker = threading.Thread(target=_worker, args=(model, class_ids, args),
                              daemon=True)
    worker.start()

    server = ThreadingHTTPServer(("0.0.0.0", args.port), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        shared.stop.set()
        server.shutdown()
        worker.join(timeout=3)


if __name__ == "__main__":
    main()
