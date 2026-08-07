"""Unit tests for detection service config parsing and motion gating."""

import json
import os
import sys
from io import BytesIO
from types import SimpleNamespace

import numpy as np
import pytest

from services.detection_service import (
    DetectionService,
    MotionGate,
    _parse_classes,
    detection_enabled,
)


class TestDetectionEnabled:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("DETECTION_ENABLED", raising=False)
        assert detection_enabled() is False

    @pytest.mark.parametrize("value,expected", [
        ("true", True), ("TRUE", True), ("True", True),
        ("false", False), ("1", False), ("yes", False), ("", False),
    ])
    def test_env_values(self, monkeypatch, value, expected):
        monkeypatch.setenv("DETECTION_ENABLED", value)
        assert detection_enabled() is expected


class TestParseClasses:
    def test_single(self):
        assert _parse_classes("bird") == {"bird"}

    def test_multiple_with_whitespace_and_case(self):
        assert _parse_classes(" Bird, cat ,DOG") == {"bird", "cat", "dog"}

    def test_empty(self):
        assert _parse_classes("") == set()


class TestMotionGate:
    def _frame(self, value=0):
        return np.full((240, 320, 3), value, dtype=np.uint8)

    def test_first_frame_passes(self):
        gate = MotionGate()
        assert gate.check(self._frame()) is True

    def test_static_scene_gated(self):
        gate = MotionGate()
        gate.check(self._frame(100))
        assert gate.check(self._frame(100)) is False

    def test_large_change_passes(self):
        gate = MotionGate()
        gate.check(self._frame(0))
        assert gate.check(self._frame(200)) is True

    def test_small_change_gated(self):
        gate = MotionGate(min_area_fraction=0.05)
        base = self._frame(100)
        gate.check(base)
        moved = base.copy()
        moved[0:5, 0:5] = 255  # tiny blob ≪ 5% of the frame
        assert gate.check(moved) is False


class TestDetectionServiceConfig:
    def test_defaults(self, monkeypatch):
        for var in ["DETECTION_STREAM_URL", "DETECTION_MODEL", "DETECTION_FPS",
                    "DETECTION_IMGSZ",
                    "DETECTION_MODEL_DIR", "DETECTION_CONF",
                    "DETECTION_CLASSES", "DETECTION_MOTION_GATE",
                    "DETECTION_RTSP_BASE_URL", "MEDIAMTX_API_URL",
                    "MEDIAMTX_PATH", "BIRD_LINGER_SECONDS",
                    "BIRD_PRESENCE_GAP_SECONDS", "BIRD_SNAPSHOT_BORDER",
                    "BIRD_NOTIFICATION_COOLDOWN_SECONDS"]:
            monkeypatch.delenv(var, raising=False)
        svc = DetectionService()
        assert svc.configured_stream_url == "auto"
        assert svc.stream_url is None
        assert svc.model_name == "yolo11n.pt"
        assert str(svc.model_path) == "/var/lib/birdstream/models/yolo11n.pt"
        assert svc.sample_fps == 1.0
        assert svc.image_size == 320
        assert svc.conf == 0.4
        assert svc.classes == {"bird", "cat", "human"}
        assert svc.bird_linger_seconds == 3.0
        assert svc.bird_presence_gap_seconds == 1.0
        assert svc.snapshot_border == 0.4
        assert svc.motion_gate_enabled is True
        assert svc.running is False

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("DETECTION_STREAM_URL", "rtsp://other:8554/cam2")
        monkeypatch.setenv("DETECTION_FPS", "5")
        monkeypatch.setenv("DETECTION_IMGSZ", "416")
        monkeypatch.setenv("DETECTION_CLASSES", "bird,cat")
        monkeypatch.setenv("DETECTION_MOTION_GATE", "false")
        svc = DetectionService()
        assert svc.configured_stream_url == "rtsp://other:8554/cam2"
        assert svc.stream_url == "rtsp://other:8554/cam2"
        assert svc.sample_fps == 5.0
        assert svc.image_size == 416
        assert svc.classes == {"bird", "cat"}
        assert svc.motion_gate_enabled is False

    def test_only_supported_object_classes_are_retained(self, monkeypatch):
        monkeypatch.setenv("DETECTION_CLASSES", "bird,dog,human")

        svc = DetectionService()

        assert svc.classes == {"bird", "human"}

    def test_human_maps_to_person_model_class(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DETECTION_CLASSES", "human")
        monkeypatch.setenv("DETECTION_MODEL_DIR", str(tmp_path))

        class FakeModel:
            names = {0: "person", 1: "bird"}

        monkeypatch.setitem(
            sys.modules,
            "ultralytics",
            SimpleNamespace(YOLO=lambda _path: FakeModel()),
        )

        svc = DetectionService()

        assert svc._load_model() is not None
        assert svc._class_ids == [0]

    def test_default_classes_map_to_generic_model_objects(
        self, monkeypatch, tmp_path
    ):
        monkeypatch.delenv("DETECTION_CLASSES", raising=False)
        monkeypatch.setenv("DETECTION_MODEL_DIR", str(tmp_path))

        class FakeModel:
            names = {0: "person", 1: "bird", 2: "cat", 3: "dog"}

        monkeypatch.setitem(
            sys.modules,
            "ultralytics",
            SimpleNamespace(YOLO=lambda _path: FakeModel()),
        )

        svc = DetectionService()

        assert svc._load_model() is not None
        assert set(svc._class_ids) == {0, 1, 2}

    def test_auto_discovers_primary_stream_first(self, monkeypatch):
        response = BytesIO(json.dumps({
            "items": [
                {"name": "birdcam-pi-01-side", "ready": True},
                {"name": "other", "ready": True},
                {"name": "birdcam", "ready": True},
            ],
        }).encode())
        monkeypatch.setattr(
            "services.detection_service.request.urlopen",
            lambda *_args, **_kwargs: response,
        )

        svc = DetectionService()
        assert svc._discover_stream_url() == "rtsp://mediamtx:8554/birdcam"

    def test_auto_falls_back_to_additional_camera(self, monkeypatch):
        response = BytesIO(json.dumps({
            "items": [
                {"name": "birdcam-pi-01-side", "ready": True},
                {"name": "birdcam-pi-01-offline", "ready": False},
            ],
        }).encode())
        monkeypatch.setattr(
            "services.detection_service.request.urlopen",
            lambda *_args, **_kwargs: response,
        )

        svc = DetectionService()
        assert svc._discover_stream_url() == (
            "rtsp://mediamtx:8554/birdcam-pi-01-side")

    def test_auto_returns_none_without_active_camera(self, monkeypatch):
        response = BytesIO(json.dumps({"items": []}).encode())
        monkeypatch.setattr(
            "services.detection_service.request.urlopen",
            lambda *_args, **_kwargs: response,
        )

        assert DetectionService()._discover_stream_url() is None

    def test_explicit_stream_skips_discovery(self, monkeypatch):
        monkeypatch.setenv("DETECTION_STREAM_URL", "rtsp://example/camera")
        svc = DetectionService()
        assert svc._capture_url() == "rtsp://example/camera"

    def test_bare_model_name_uses_writable_model_dir(
            self, monkeypatch, tmp_path):
        monkeypatch.setenv("DETECTION_MODEL", "yolo11n.pt")
        monkeypatch.setenv("DETECTION_MODEL_DIR", str(tmp_path / "models"))
        loaded = []

        class FakeModel:
            names = {0: "bird"}

        monkeypatch.setitem(
            sys.modules,
            "ultralytics",
            SimpleNamespace(YOLO=lambda path: loaded.append(path) or FakeModel()),
        )

        svc = DetectionService()
        assert svc._load_model() is not None
        assert loaded == [str(tmp_path / "models" / "yolo11n.pt")]
        assert (tmp_path / "models").is_dir()
        assert svc.last_error is None

    def test_absolute_model_path_is_preserved(self, monkeypatch, tmp_path):
        model_path = tmp_path / "custom.pt"
        monkeypatch.setenv("DETECTION_MODEL", str(model_path))
        svc = DetectionService()
        assert svc.model_path == model_path

    def test_model_load_failure_is_reported(self, monkeypatch, tmp_path):
        monkeypatch.setenv("DETECTION_MODEL_DIR", str(tmp_path))

        def fail(_path):
            raise PermissionError("read-only")

        monkeypatch.setitem(
            sys.modules, "ultralytics", SimpleNamespace(YOLO=fail))

        svc = DetectionService()
        assert svc._load_model() is None
        assert "read-only" in svc.last_error
        assert svc.status()["last_error"] == svc.last_error

    def test_status_shape(self):
        svc = DetectionService()
        s = svc.status()
        assert s["enabled"] is True
        assert s["running"] is False
        assert s["frames_inferred"] == 0

    def test_latest_and_events_empty(self):
        svc = DetectionService()
        assert svc.get_latest()["detections"] == []
        assert svc.get_events() == []

    def test_detection_callback_receives_jpeg_and_respects_cooldown(self, monkeypatch):
        calls = []
        monkeypatch.setenv("BIRD_NOTIFICATION_COOLDOWN_SECONDS", "900")
        svc = DetectionService(
            on_detection=lambda jpeg, detections, timestamp: calls.append(
                (jpeg, detections, timestamp)
            )
        )
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        detections = [{"label": "bird", "confidence": 0.92}]

        assert svc._notify_detection(frame, detections, "2026-07-27 21:00:00")
        assert not svc._notify_detection(frame, detections, "2026-07-27 21:00:01")
        assert len(calls) == 1
        assert calls[0][0].startswith(b"\xff\xd8")
        assert calls[0][1] == detections

    def test_bird_must_linger_before_notification(self, monkeypatch):
        calls = []
        monkeypatch.setenv("BIRD_LINGER_SECONDS", "3")
        svc = DetectionService(
            on_detection=lambda jpeg, detections, timestamp: calls.append(
                (jpeg, detections, timestamp)
            )
        )
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        bird = [{"label": "bird", "confidence": 0.92, "bbox": [30, 30, 60, 60]}]

        assert not svc._track_bird_presence(frame, bird, "first", now=10.0)
        assert not svc._track_bird_presence(frame, bird, "second", now=12.9)
        assert svc._track_bird_presence(frame, bird, "third", now=13.0)
        assert not svc._track_bird_presence(frame, bird, "fourth", now=20.0)

        assert len(calls) == 1
        assert calls[0][1] == bird
        assert calls[0][2] == "third"

    def test_cat_and_human_never_trigger_bird_alert(self):
        calls = []
        svc = DetectionService(on_detection=lambda *_args: calls.append(True))
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        other_objects = [
            {"label": "cat", "bbox": [10, 10, 20, 20]},
            {"label": "human", "bbox": [30, 30, 80, 90]},
        ]

        svc._track_bird_presence(frame, other_objects, "first", now=1.0)
        svc._track_bird_presence(frame, other_objects, "later", now=10.0)

        assert calls == []

    def test_short_bird_visit_is_discarded(self, monkeypatch):
        calls = []
        monkeypatch.setenv("BIRD_LINGER_SECONDS", "3")
        monkeypatch.setenv("BIRD_PRESENCE_GAP_SECONDS", "1")
        svc = DetectionService(on_detection=lambda *_args: calls.append(True))
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        bird = [{"label": "bird", "bbox": [30, 30, 60, 60]}]

        svc._track_bird_presence(frame, bird, "seen", now=1.0)
        svc._track_bird_presence(frame, [], "gone", now=2.1)
        svc._track_bird_presence(frame, bird, "back", now=3.0)
        svc._track_bird_presence(frame, bird, "not-yet", now=5.9)

        assert calls == []

    def test_alerted_bird_presence_emits_ended_callback(self, monkeypatch):
        ended = []
        monkeypatch.setenv("BIRD_LINGER_SECONDS", "0")
        monkeypatch.setenv("BIRD_PRESENCE_GAP_SECONDS", "1")
        svc = DetectionService(
            on_detection=lambda *_args: None,
            on_bird_presence_ended=lambda: ended.append(True),
        )
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        bird = [{"label": "bird", "bbox": [30, 30, 60, 60]}]

        assert svc._track_bird_presence(frame, bird, "seen", now=1.0)
        svc._track_bird_presence(frame, [], "gap", now=1.5)
        svc._track_bird_presence(frame, [], "gone", now=2.1)
        svc._track_bird_presence(frame, [], "still gone", now=3.2)

        assert ended == [True]

    def test_snapshot_crops_all_birds_with_border(self, monkeypatch):
        snapshots = []
        monkeypatch.setenv("BIRD_SNAPSHOT_BORDER", "0.5")
        svc = DetectionService(
            on_detection=lambda jpeg, *_args: snapshots.append(jpeg)
        )
        frame = np.zeros((200, 300, 3), dtype=np.uint8)
        birds = [
            {"label": "bird", "bbox": [100, 80, 140, 120]},
            {"label": "bird", "bbox": [150, 90, 170, 130]},
        ]

        assert svc._notify_detection(frame, birds, "now", now=1.0)

        import cv2

        decoded = cv2.imdecode(
            np.frombuffer(snapshots[0], dtype=np.uint8), cv2.IMREAD_COLOR
        )
        # Union is 70x50; 50% padding on both sides produces a 140x100 crop.
        assert decoded.shape[:2] == (100, 140)
