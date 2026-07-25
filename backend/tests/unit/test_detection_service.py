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
                    "DETECTION_MODEL_DIR", "DETECTION_CONF",
                    "DETECTION_CLASSES", "DETECTION_MOTION_GATE",
                    "DETECTION_RTSP_BASE_URL", "MEDIAMTX_API_URL",
                    "MEDIAMTX_PATH"]:
            monkeypatch.delenv(var, raising=False)
        svc = DetectionService()
        assert svc.configured_stream_url == "auto"
        assert svc.stream_url is None
        assert svc.model_name == "yolo11n.pt"
        assert str(svc.model_path) == "/var/lib/birdstream/models/yolo11n.pt"
        assert svc.sample_fps == 2.0
        assert svc.conf == 0.4
        assert svc.classes == {"bird"}
        assert svc.motion_gate_enabled is True
        assert svc.running is False

    def test_env_overrides(self, monkeypatch):
        monkeypatch.setenv("DETECTION_STREAM_URL", "rtsp://other:8554/cam2")
        monkeypatch.setenv("DETECTION_FPS", "5")
        monkeypatch.setenv("DETECTION_CLASSES", "bird,cat")
        monkeypatch.setenv("DETECTION_MOTION_GATE", "false")
        svc = DetectionService()
        assert svc.configured_stream_url == "rtsp://other:8554/cam2"
        assert svc.stream_url == "rtsp://other:8554/cam2"
        assert svc.sample_fps == 5.0
        assert svc.classes == {"bird", "cat"}
        assert svc.motion_gate_enabled is False

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
