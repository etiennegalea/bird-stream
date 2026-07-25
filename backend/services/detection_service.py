"""Bird object detection over the MediaMTX stream.

Enabled via DETECTION_ENABLED=true. Runs a background thread that reads the
RTSP stream from MediaMTX, motion-gates frames (cheap frame differencing), and
runs a YOLO model on sampled frames only. Detections are kept in memory and
exposed via /detection/* endpoints.

Env:
    DETECTION_ENABLED       "true" to start the worker (default false)
    DETECTION_STREAM_URL    default rtsp://mediamtx:8554/birdcam. A bare integer
                            (e.g. "0") opens that local camera device index —
                            handy for testing on a laptop/Mac webcam.
    DETECTION_MODEL         ultralytics model name/path (default yolo11n.pt,
                            auto-downloaded on first run)
    DETECTION_FPS           inference sampling rate (default 2)
    DETECTION_CONF          min confidence (default 0.4)
    DETECTION_CLASSES       comma-separated COCO class names (default "bird,cat")
    DETECTION_MOTION_GATE   "false" to run inference on every sampled frame
    DETECTION_MOTION_MIN_AREA  min changed-pixel fraction to count as motion
                               (default 0.005 = 0.5% of the frame)

Bird species classification (optional second stage): when enabled, each YOLO
"bird" box is cropped and passed to a fine-grained image classifier, and the
detection gains "species" / "species_confidence" fields. Cats (and any other
class) are left as-is.

    DETECTION_SPECIES_ENABLED   "true" to enable (default false)
    DETECTION_SPECIES_MODEL     HF image-classification model (default
                                dennisjooo/Birds-Classifier-EfficientNetB2,
                                525 species, auto-downloaded on first run)
    DETECTION_SPECIES_CONF      min classifier confidence to attach a species
                                (default 0.5; below it the label stays "bird")
    DETECTION_SPECIES_MIN_PX    min crop side in pixels to bother classifying
                                (default 32 — tiny distant birds are skipped)

The ultralytics/transformers imports are lazy so the backend runs fine without
the optional 'detection' dependency group installed (uv sync --group detection).
"""

import logging
import os
import threading
import time
from collections import deque

logger = logging.getLogger("detection_service")


def detection_enabled() -> bool:
    return os.environ.get("DETECTION_ENABLED", "false").lower() == "true"


def _parse_classes(raw: str) -> set[str]:
    return {c.strip().lower() for c in raw.split(",") if c.strip()}


def _crop_bbox(frame, bbox, pad_fraction: float = 0.1, min_size: int = 32):
    """Crop a padded bbox from a frame; None if the clamped crop is too small.

    A little padding of context around the box helps the classifier; the crop
    is clamped to the frame, so boxes at the edge shrink rather than error.
    """
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    pad_x = (x2 - x1) * pad_fraction
    pad_y = (y2 - y1) * pad_fraction
    x1 = max(0, int(x1 - pad_x))
    y1 = max(0, int(y1 - pad_y))
    x2 = min(w, int(x2 + pad_x))
    y2 = min(h, int(y2 + pad_y))
    if (x2 - x1) < min_size or (y2 - y1) < min_size:
        return None
    return frame[y1:y2, x1:x2]


class SpeciesClassifier:
    """Second-stage fine-grained bird species classifier over YOLO crops."""

    def __init__(self, model_name: str, min_conf: float = 0.5,
                 min_crop_px: int = 32):
        self.model_name = model_name
        self.min_conf = min_conf
        self.min_crop_px = min_crop_px
        self._pipeline = None

    @property
    def loaded(self) -> bool:
        return self._pipeline is not None

    def load(self) -> bool:
        try:
            from transformers import pipeline
        except ImportError:
            logger.error(
                "DETECTION_SPECIES_ENABLED is true but transformers is not "
                "installed. Install with: uv sync --group detection")
            return False
        try:
            pipe = pipeline("image-classification", model=self.model_name)
        except Exception:
            logger.exception(f"Failed to load species model {self.model_name}")
            return False

        # Wrap PIL conversion here so classify() stays importable without
        # pillow (installed with the detection group; unit tests stub this).
        import numpy as np
        from PIL import Image

        def run(crop_rgb, top_k=1):
            return pipe(Image.fromarray(np.ascontiguousarray(crop_rgb)),
                        top_k=top_k)

        self._pipeline = run
        logger.info(f"Species classifier loaded ({self.model_name})")
        return True

    def classify(self, frame, bbox) -> tuple[str, float] | None:
        """Return (species, confidence) for a bird crop, or None."""
        if self._pipeline is None:
            return None
        crop = _crop_bbox(frame, bbox, min_size=self.min_crop_px)
        if crop is None:
            return None
        try:
            preds = self._pipeline(crop[:, :, ::-1], top_k=1)  # BGR -> RGB
        except Exception:
            logger.exception("Species classification failed")
            return None
        if not preds:
            return None
        top = preds[0]
        score = float(top["score"])
        if score < self.min_conf:
            return None
        return top["label"].title(), round(score, 3)


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
    def __init__(self):
        self.stream_url = os.environ.get(
            "DETECTION_STREAM_URL", "rtsp://mediamtx:8554/birdcam")
        self.model_name = os.environ.get("DETECTION_MODEL", "yolo11n.pt")
        self.sample_fps = float(os.environ.get("DETECTION_FPS", "2"))
        self.conf = float(os.environ.get("DETECTION_CONF", "0.4"))
        self.classes = _parse_classes(
            os.environ.get("DETECTION_CLASSES", "bird,cat"))
        self.motion_gate_enabled = os.environ.get(
            "DETECTION_MOTION_GATE", "true").lower() == "true"
        min_area = float(os.environ.get("DETECTION_MOTION_MIN_AREA", "0.005"))

        self.species_enabled = os.environ.get(
            "DETECTION_SPECIES_ENABLED", "false").lower() == "true"
        self.species_model = os.environ.get(
            "DETECTION_SPECIES_MODEL",
            "dennisjooo/Birds-Classifier-EfficientNetB2")
        species_conf = float(os.environ.get("DETECTION_SPECIES_CONF", "0.5"))
        species_min_px = int(os.environ.get("DETECTION_SPECIES_MIN_PX", "32"))
        self._species = SpeciesClassifier(
            self.species_model, min_conf=species_conf,
            min_crop_px=species_min_px) if self.species_enabled else None

        self._gate = MotionGate(min_area_fraction=min_area)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._model = None

        # state exposed via the API
        self.running = False
        self.connected = False
        self.frames_seen = 0
        self.frames_inferred = 0
        self.last_frame_ts = None
        self.latest = {"timestamp": None, "detections": []}
        self.events = deque(maxlen=100)  # only frames that contained a match

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="detection-worker")
        self._thread.start()
        self.running = True
        logger.info(f"Detection worker started (stream={self.stream_url}, "
                    f"model={self.model_name}, fps={self.sample_fps}, "
                    f"classes={sorted(self.classes)})")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
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
        model = YOLO(self.model_name)  # auto-downloads weights if missing
        # Resolve requested class names -> ids for this model
        name_to_id = {v.lower(): k for k, v in model.names.items()}
        self._class_ids = [name_to_id[c] for c in self.classes if c in name_to_id]
        missing = self.classes - set(name_to_id)
        if missing:
            logger.warning(f"Classes not in model vocabulary, ignored: {missing}")
        if not self._class_ids:
            logger.warning("No valid classes requested; detecting ALL classes")
            self._class_ids = None
        return model

    def _infer(self, frame) -> list[dict]:
        results = self._model.predict(
            frame, conf=self.conf, classes=self._class_ids, verbose=False)
        detections = []
        for r in results:
            for b in r.boxes:
                detections.append({
                    "label": self._model.names[int(b.cls)],
                    "confidence": round(float(b.conf), 3),
                    "bbox": [round(float(v), 1) for v in b.xyxy[0].tolist()],
                })
        self._attach_species(frame, detections)
        return detections

    def _attach_species(self, frame, detections: list[dict]) -> None:
        """Add species/species_confidence to bird detections (in place)."""
        if not (self._species and self._species.loaded):
            return
        for det in detections:
            if det["label"] != "bird":
                continue
            result = self._species.classify(frame, det["bbox"])
            if result:
                det["species"], det["species_confidence"] = result

    # ── worker loop ───────────────────────────────────────────────────────

    def _open_capture(self):
        import cv2

        src = str(self.stream_url)
        # A bare integer source (e.g. DETECTION_STREAM_URL=0) is a local camera
        # device index — used to test detection on a laptop webcam. Open it with
        # the platform's default backend (AVFoundation on macOS, V4L2 on Linux).
        # Anything else is treated as a stream URL (RTSP via FFmpeg).
        if src.isdigit():
            cap = cv2.VideoCapture(int(src))
        else:
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                                  "rtsp_transport;tcp")
            cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        return cap if cap.isOpened() else None

    def _run(self):
        self._model = self._load_model()
        if self._model is None:
            self.running = False
            return

        if self._species and not self._species.load():
            logger.warning("Species classification disabled (load failed); "
                           "detections will keep the generic 'bird' label")
            self._species = None

        interval = 1.0 / self.sample_fps if self.sample_fps > 0 else 0.5
        backoff = 2
        last_inference = 0.0

        while not self._stop.is_set():
            cap = self._open_capture()
            if cap is None:
                self.connected = False
                logger.warning(f"Cannot open stream {self.stream_url}, "
                               f"retrying in {backoff}s")
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

                if self.motion_gate_enabled and not self._gate.check(frame):
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

            cap.release()

        self.connected = False

    # ── API accessors ─────────────────────────────────────────────────────

    def status(self) -> dict:
        return {
            "enabled": True,
            "running": self.running,
            "connected": self.connected,
            "stream_url": self.stream_url,
            "model": self.model_name,
            "sample_fps": self.sample_fps,
            "confidence_threshold": self.conf,
            "classes": sorted(self.classes),
            "species_enabled": self.species_enabled,
            "species_model": self.species_model if self.species_enabled else None,
            "species_active": bool(self._species and self._species.loaded),
            "motion_gate": self.motion_gate_enabled,
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
