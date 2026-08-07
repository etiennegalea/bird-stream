"""Bird object detection over the MediaMTX stream.

Enabled via DETECTION_ENABLED=true. Runs a background thread that reads the
RTSP stream from MediaMTX, motion-gates frames (cheap frame differencing), and
runs a YOLO model on sampled frames only. Detections are kept in memory and
exposed via /detection/* endpoints.

Env:
    DETECTION_ENABLED       "true" to start the worker (default false)
    DETECTION_STREAM_URL    "auto" (default) discovers an active MediaMTX path,
                            or set an explicit RTSP URL
    DETECTION_RTSP_BASE_URL MediaMTX RTSP base used by auto discovery
    MEDIAMTX_API_URL        MediaMTX control API used by auto discovery
    MEDIAMTX_PATH           accepted camera path prefix (default birdcam)
    DETECTION_MODEL         ultralytics model name/path (default yolo11n.pt,
                            auto-downloaded on first run)
    DETECTION_MODEL_DIR     writable model cache for bare model names
                            (default /var/lib/birdstream/models)
    DETECTION_FPS           inference sampling rate (default 1)
    DETECTION_IMGSZ         square inference input size (default 320; lower is
                            faster but misses very small/distant birds)
    DETECTION_CONF          min confidence (default 0.4)
    DETECTION_CLASSES       comma-separated supported object names
                            (bird, cat, human; default all three)
    DETECTION_MOTION_GATE   "false" to run inference on every sampled frame
    DETECTION_MOTION_MIN_AREA  min changed-pixel fraction to count as motion
                               (default 0.005 = 0.5% of the frame)
    BIRD_LINGER_SECONDS     continuous bird presence required before an alert
                            (default 3 seconds)
    BIRD_PRESENCE_GAP_SECONDS  tolerated missed-detection gap (default 1 second)
    POV_CAT_PRESENCE_GAP_SECONDS tolerated missed cat detections on the POV
                               stream before it is considered clear (default 2)
    POV_MONITOR_STARTUP_TIMEOUT_SECONDS maximum wait for a newly-started POV
                               stream before treating it as clear (default 15)
    BIRD_SNAPSHOT_BORDER    crop padding relative to the bird bounds
                            (default 0.4 = 40%)

The ultralytics import is lazy so the backend runs fine without the optional
'detection' dependency group installed (uv sync --group detection).
"""

import logging
import json
import os
import threading
import time
from collections import deque
from pathlib import Path
from urllib import parse, request

logger = logging.getLogger("detection_service")

_SUPPORTED_CLASSES = {"bird", "cat", "human"}
_MODEL_CLASS_NAMES = {"human": "person"}
_DISPLAY_CLASS_NAMES = {"person": "human"}


def detection_enabled() -> bool:
    return os.environ.get("DETECTION_ENABLED", "false").lower() == "true"


def _parse_classes(raw: str) -> set[str]:
    return {c.strip().lower() for c in raw.split(",") if c.strip()}


class MotionGate:
    """Cheap frame-differencing gate: True when the scene changed enough."""

    def __init__(self, min_area_fraction: float = 0.005, downscale_width: int = 320):
        self.min_area_fraction = min_area_fraction
        self.downscale_width = downscale_width
        self._prev = None

    def check(self, frame) -> bool:
        import cv2

        h, w = frame.shape[:2]
        scale = self.downscale_width / float(w)
        small = cv2.resize(frame, (self.downscale_width, max(1, int(h * scale))))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)

        if self._prev is None:
            self._prev = gray
            return True  # first frame: let inference establish a baseline

        delta = cv2.absdiff(self._prev, gray)
        self._prev = gray
        changed = (delta > 25).sum()
        return bool((changed / delta.size) >= self.min_area_fraction)


class DetectionService:
    def __init__(
        self,
        on_detection=None,
        on_bird_presence_ended=None,
        pov_target_provider=None,
        on_pov_cat_presence=None,
    ):
        self.configured_stream_url = os.environ.get(
            "DETECTION_STREAM_URL", "auto").strip()
        self.stream_url = (
            None if self.configured_stream_url.lower() == "auto"
            else self.configured_stream_url
        )
        self.mediamtx_api_url = os.environ.get(
            "MEDIAMTX_API_URL", "http://mediamtx:9997").rstrip("/")
        self.rtsp_base_url = os.environ.get(
            "DETECTION_RTSP_BASE_URL", "rtsp://mediamtx:8554").rstrip("/")
        self.path_prefix = os.environ.get("MEDIAMTX_PATH", "birdcam")
        self.model_name = os.environ.get("DETECTION_MODEL", "yolo11n.pt")
        self.model_dir = Path(os.environ.get(
            "DETECTION_MODEL_DIR", "/var/lib/birdstream/models"
        )).expanduser()
        configured_model = Path(self.model_name).expanduser()
        self.model_path = (
            configured_model
            if configured_model.is_absolute()
            else self.model_dir / configured_model
        )
        self.sample_fps = float(os.environ.get("DETECTION_FPS", "1"))
        self.image_size = max(
            160, int(os.environ.get("DETECTION_IMGSZ", "320"))
        )
        self.conf = float(os.environ.get("DETECTION_CONF", "0.4"))
        requested_classes = _parse_classes(
            os.environ.get("DETECTION_CLASSES", "bird,cat,human")
        )
        unsupported_classes = requested_classes - _SUPPORTED_CLASSES
        if unsupported_classes:
            logger.warning(
                "Unsupported detection classes ignored: %s",
                sorted(unsupported_classes),
            )
        self.classes = requested_classes & _SUPPORTED_CLASSES
        if not self.classes:
            self.classes = set(_SUPPORTED_CLASSES)
        self.notification_cooldown = float(
            os.environ.get("BIRD_NOTIFICATION_COOLDOWN_SECONDS", "900")
        )
        self.bird_linger_seconds = max(
            0.0, float(os.environ.get("BIRD_LINGER_SECONDS", "3"))
        )
        self.bird_presence_gap_seconds = max(
            0.0, float(os.environ.get("BIRD_PRESENCE_GAP_SECONDS", "1"))
        )
        self.pov_cat_presence_gap_seconds = max(
            0.0, float(os.environ.get("POV_CAT_PRESENCE_GAP_SECONDS", "2"))
        )
        self.pov_monitor_startup_timeout = max(
            1.0,
            float(os.environ.get("POV_MONITOR_STARTUP_TIMEOUT_SECONDS", "15")),
        )
        self.snapshot_border = max(
            0.0, float(os.environ.get("BIRD_SNAPSHOT_BORDER", "0.4"))
        )
        self.motion_gate_enabled = os.environ.get(
            "DETECTION_MOTION_GATE", "true").lower() == "true"
        min_area = float(os.environ.get("DETECTION_MOTION_MIN_AREA", "0.005"))

        self._gate = MotionGate(min_area_fraction=min_area)
        self._lock = threading.Lock()
        self._model_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._pov_thread = None
        self._model = None
        self._on_detection = on_detection
        self._on_bird_presence_ended = on_bird_presence_ended
        self._pov_target_provider = pov_target_provider
        self._on_pov_cat_presence = on_pov_cat_presence
        self._last_notification = None
        self._bird_seen_since = None
        self._bird_last_seen = None
        self._bird_alerted_for_presence = False

        # state exposed via the API
        self.running = False
        self.connected = False
        self.frames_seen = 0
        self.frames_inferred = 0
        self.last_frame_ts = None
        self.last_error = None
        self.latest = {"timestamp": None, "detections": []}
        self.events = deque(maxlen=100)  # only frames that contained a match
        self.pov_monitor_connected = False
        self.pov_monitor_target = None
        self.pov_cat_present = None

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="detection-worker")
        self._thread.start()
        if self._pov_target_provider and self._on_pov_cat_presence:
            self._pov_thread = threading.Thread(
                target=self._run_pov_monitor,
                daemon=True,
                name="pov-cat-monitor",
            )
            self._pov_thread.start()
        logger.info(f"Detection worker started "
                    f"(stream={self.configured_stream_url}, "
                    f"model={self.model_name}, fps={self.sample_fps}, "
                    f"classes={sorted(self.classes)})")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._pov_thread:
            self._pov_thread.join(timeout=5)
        self.running = False
        logger.info("Detection worker stopped")

    # ── model ─────────────────────────────────────────────────────────────

    def _load_model(self):
        try:
            from ultralytics import YOLO
        except ImportError:
            logger.error(
                "DETECTION_ENABLED is true but ultralytics is not installed. "
                "Install with: uv sync --group detection "
                "(or build the image with INSTALL_DETECTION=true)")
            return None
        try:
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            model = YOLO(str(self.model_path))
        except Exception as exc:
            self.last_error = f"Unable to load detection model: {exc}"
            logger.exception(
                "Unable to load detection model %s. Ensure %s is writable.",
                self.model_path,
                self.model_path.parent,
            )
            return None

        self.last_error = None
        # Resolve requested class names -> ids for this model
        name_to_id = {v.lower(): k for k, v in model.names.items()}
        requested_model_names = {
            _MODEL_CLASS_NAMES.get(name, name) for name in self.classes
        }
        self._class_ids = [
            name_to_id[name]
            for name in requested_model_names
            if name in name_to_id
        ]
        missing = requested_model_names - set(name_to_id)
        if missing:
            logger.warning(f"Classes not in model vocabulary, ignored: {missing}")
        if not self._class_ids:
            self.last_error = "Model does not support bird, cat, or human detection"
            logger.error(self.last_error)
            return None
        self._cat_class_ids = (
            [name_to_id["cat"]] if "cat" in name_to_id else []
        )
        return model

    def _infer(self, frame, class_ids=None) -> list[dict]:
        with self._model_lock:
            results = self._model.predict(
                frame,
                conf=self.conf,
                classes=self._class_ids if class_ids is None else class_ids,
                imgsz=self.image_size,
                verbose=False,
            )
        detections = []
        for r in results:
            for b in r.boxes:
                detections.append({
                    "label": _DISPLAY_CLASS_NAMES.get(
                        self._model.names[int(b.cls)].lower(),
                        self._model.names[int(b.cls)].lower(),
                    ),
                    "confidence": round(float(b.conf), 3),
                    "bbox": [round(float(v), 1) for v in b.xyxy[0].tolist()],
                })
        return detections

    # ── triggered POV cat monitor ─────────────────────────────────────────

    def _run_pov_monitor(self):
        """Inspect only the currently triggered POV stream for generic cats."""
        import cv2

        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        cap = None
        target_key = None
        target = None
        startup_deadline = None
        last_inference = 0.0
        last_cat_seen = None
        reported = None
        interval = 1.0 / self.sample_fps if self.sample_fps > 0 else 1.0

        def close_capture():
            nonlocal cap
            if cap is not None:
                cap.release()
                cap = None
            self.pov_monitor_connected = False

        while not self._stop.is_set():
            try:
                next_target = self._pov_target_provider()
            except Exception:
                logger.exception("POV target provider failed")
                next_target = None

            next_key = (
                (next_target.get("pi_id"), next_target.get("path"))
                if next_target else None
            )
            if next_key != target_key:
                close_capture()
                target_key = next_key
                target = next_target
                startup_deadline = (
                    time.monotonic() + self.pov_monitor_startup_timeout
                    if target else None
                )
                last_cat_seen = None
                reported = None
                self.pov_cat_present = None
                self.pov_monitor_target = (
                    target.get("path") if target else None
                )

            if not target or self._model is None:
                self._stop.wait(0.25)
                continue

            if not getattr(self, "_cat_class_ids", None):
                if reported is not False:
                    self._report_pov_cat(target["pi_id"], False)
                    reported = False
                self._stop.wait(1)
                continue

            if cap is None:
                path = parse.quote(target["path"], safe="/-_.~")
                stream_url = f"{self.rtsp_base_url}/{path}"
                cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
                if not cap.isOpened():
                    cap.release()
                    cap = None
                    if (
                        time.monotonic() >= startup_deadline
                        and reported is not False
                    ):
                        logger.warning(
                            "POV stream %s did not start within %.1fs",
                            target["path"], self.pov_monitor_startup_timeout,
                        )
                        self._report_pov_cat(target["pi_id"], False)
                        reported = False
                    self._stop.wait(1)
                    continue
                self.pov_monitor_connected = True
                logger.info("Monitoring POV stream %s for cats", target["path"])

            ok, frame = cap.read()
            if not ok:
                close_capture()
                self._stop.wait(0.5)
                continue

            now = time.monotonic()
            if now - last_inference < interval:
                continue
            last_inference = now
            try:
                detections = self._infer(frame, self._cat_class_ids)
            except Exception:
                logger.exception("POV cat inference failed")
                continue

            present, last_cat_seen = self._pov_cat_state(
                detections, now, last_cat_seen
            )
            if present != reported:
                self._report_pov_cat(target["pi_id"], present)
                reported = present

        close_capture()
        self.pov_monitor_target = None
        self.pov_cat_present = None

    def _pov_cat_state(
        self,
        detections: list[dict],
        now: float,
        last_cat_seen: float | None,
    ) -> tuple[bool, float | None]:
        """Apply the missed-detection gap to POV cat observations."""
        if any(item.get("label") == "cat" for item in detections):
            return True, now
        return (
            last_cat_seen is not None
            and now - last_cat_seen <= self.pov_cat_presence_gap_seconds,
            last_cat_seen,
        )

    def _report_pov_cat(self, pi_id: str, present: bool) -> None:
        self.pov_cat_present = present
        try:
            self._on_pov_cat_presence(pi_id, present)
        except Exception:
            logger.exception("POV cat-presence callback failed")

    # ── worker loop ───────────────────────────────────────────────────────

    def _discover_stream_url(self) -> str | None:
        """Return an active MediaMTX camera stream, preferring the legacy path."""
        try:
            with request.urlopen(
                f"{self.mediamtx_api_url}/v3/paths/list", timeout=2
            ) as response:
                payload = json.load(response)
        except Exception as exc:
            logger.debug("MediaMTX path discovery failed: %s", exc)
            return None

        names = [
            item.get("name")
            for item in payload.get("items", [])
            if item.get("name")
            and item.get("ready", True)
            and (
                item["name"] == self.path_prefix
                or item["name"].startswith(f"{self.path_prefix}-")
            )
        ]
        if not names:
            return None
        names.sort(key=lambda name: (name != self.path_prefix, name))
        path = parse.quote(names[0], safe="/-_.~")
        return f"{self.rtsp_base_url}/{path}"

    def _capture_url(self) -> str | None:
        if self.configured_stream_url.lower() != "auto":
            return self.configured_stream_url
        return self._discover_stream_url()

    def _open_capture(self):
        import cv2

        stream_url = self._capture_url()
        if not stream_url:
            self.stream_url = None
            self.last_error = "No active MediaMTX camera stream"
            return None

        self.stream_url = stream_url
        os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                              "rtsp_transport;tcp")
        cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
        if cap.isOpened():
            self.last_error = None
            return cap
        cap.release()
        self.last_error = f"Cannot open stream {stream_url}"
        return None

    def _run(self):
        self._model = self._load_model()
        if self._model is None:
            self.running = False
            return

        interval = 1.0 / self.sample_fps if self.sample_fps > 0 else 0.5
        backoff = 2
        last_inference = 0.0

        while not self._stop.is_set():
            cap = self._open_capture()
            if cap is None:
                self.connected = False
                logger.warning("%s, retrying in %ss",
                               self.last_error or "Cannot open camera stream",
                               backoff)
                if self._stop.wait(backoff):
                    break
                backoff = min(backoff * 2, 30)
                continue

            self.connected = True
            backoff = 2
            logger.info(f"Connected to {self.stream_url}")

            while not self._stop.is_set():
                # Read every frame to keep the RTSP buffer drained...
                ok, frame = cap.read()
                if not ok:
                    logger.warning("Stream read failed, reconnecting...")
                    self.connected = False
                    break
                self.frames_seen += 1
                self.last_frame_ts = time.time()

                # ...but only run detection at the sampling interval.
                now = time.monotonic()
                if now - last_inference < interval:
                    continue
                last_inference = now

                # Once a bird-presence candidate exists, keep sampling even if
                # the scene becomes still. Otherwise the motion gate would
                # prevent a perched bird from ever satisfying the linger time.
                if (
                    self.motion_gate_enabled
                    and self._bird_seen_since is None
                    and not self._gate.check(frame)
                ):
                    continue

                try:
                    detections = self._infer(frame)
                except Exception:
                    logger.exception("Inference failed")
                    continue
                self.frames_inferred += 1

                entry = {"timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                         "detections": detections}
                with self._lock:
                    self.latest = entry
                    if detections:
                        self.events.append(entry)
                if detections:
                    logger.info(f"Detected: {detections}")
                self._track_bird_presence(
                    frame, detections, entry["timestamp"], now
                )

            cap.release()

        self.connected = False

    def _track_bird_presence(
        self,
        frame,
        detections: list[dict],
        timestamp: str,
        now: float | None = None,
    ) -> bool:
        """Notify once when a bird has remained visible for the linger period."""
        now = time.monotonic() if now is None else now
        birds = [item for item in detections if item.get("label") == "bird"]

        if not birds:
            if (
                self._bird_last_seen is not None
                and now - self._bird_last_seen > self.bird_presence_gap_seconds
            ):
                was_alerted = self._bird_alerted_for_presence
                self._bird_seen_since = None
                self._bird_last_seen = None
                self._bird_alerted_for_presence = False
                if was_alerted and self._on_bird_presence_ended is not None:
                    try:
                        self._on_bird_presence_ended()
                    except Exception:
                        logger.exception("Bird presence-ended callback failed")
            return False

        if self._bird_seen_since is None:
            self._bird_seen_since = now
            self._bird_alerted_for_presence = False
        self._bird_last_seen = now

        if (
            self._bird_alerted_for_presence
            or now - self._bird_seen_since < self.bird_linger_seconds
        ):
            return False

        notified = self._notify_detection(frame, birds, timestamp, now=now)
        if notified:
            self._bird_alerted_for_presence = True
        return notified

    def _crop_bird_snapshot(self, frame, detections: list[dict]):
        """Crop around every visible bird while retaining a generous border."""
        height, width = frame.shape[:2]
        boxes = [
            item["bbox"]
            for item in detections
            if item.get("label") == "bird"
            and len(item.get("bbox", [])) == 4
        ]
        if not boxes:
            return frame

        left = min(box[0] for box in boxes)
        top = min(box[1] for box in boxes)
        right = max(box[2] for box in boxes)
        bottom = max(box[3] for box in boxes)
        bird_width = max(1.0, right - left)
        bird_height = max(1.0, bottom - top)
        pad_x = max(bird_width * self.snapshot_border, width * 0.05)
        pad_y = max(bird_height * self.snapshot_border, height * 0.05)

        x1 = max(0, int(left - pad_x))
        y1 = max(0, int(top - pad_y))
        x2 = min(width, int(right + pad_x + 0.999))
        y2 = min(height, int(bottom + pad_y + 0.999))
        if x2 <= x1 or y2 <= y1:
            return frame
        return frame[y1:y2, x1:x2]

    def _notify_detection(
        self,
        frame,
        detections: list[dict],
        timestamp: str,
        now: float | None = None,
    ) -> bool:
        """Send the bordered bird crop to the email bridge, subject to cooldown."""
        if self._on_detection is None:
            return False
        now = time.monotonic() if now is None else now
        if (
            self._last_notification is not None
            and now - self._last_notification < self.notification_cooldown
        ):
            return False

        import cv2

        snapshot = self._crop_bird_snapshot(frame, detections)
        encoded, buffer = cv2.imencode(".jpg", snapshot)
        if not encoded:
            logger.warning("Could not encode bird detection snapshot")
            return False

        try:
            self._on_detection(buffer.tobytes(), detections, timestamp)
        except Exception:
            logger.exception("Bird notification callback failed")
            return False
        self._last_notification = now
        return True

    # ── API accessors ─────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "enabled": True,
            "running": self.running,
            "connected": self.connected,
            "stream_url": self.stream_url,
            "configured_stream_url": self.configured_stream_url,
            "model": self.model_name,
            "model_path": str(self.model_path),
            "last_error": self.last_error,
            "sample_fps": self.sample_fps,
            "inference_image_size": self.image_size,
            "confidence_threshold": self.conf,
            "classes": sorted(self.classes),
            "motion_gate": self.motion_gate_enabled,
            "notification_cooldown_seconds": self.notification_cooldown,
            "bird_linger_seconds": self.bird_linger_seconds,
            "bird_presence_gap_seconds": self.bird_presence_gap_seconds,
            "pov_cat_presence_gap_seconds": self.pov_cat_presence_gap_seconds,
            "pov_monitor_startup_timeout_seconds": self.pov_monitor_startup_timeout,
            "pov_monitor_connected": self.pov_monitor_connected,
            "pov_monitor_target": self.pov_monitor_target,
            "pov_cat_present": self.pov_cat_present,
            "snapshot_border": self.snapshot_border,
            "frames_seen": self.frames_seen,
            "frames_inferred": self.frames_inferred,
            "last_frame_ts": self.last_frame_ts,
        }

    def get_latest(self) -> dict:
        with self._lock:
            return dict(self.latest)

    def get_events(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self.events)[-limit:]
