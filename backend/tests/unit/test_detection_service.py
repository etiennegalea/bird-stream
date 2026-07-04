"""Unit tests for detection service config parsing and motion gating."""

import os

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
                    "DETECTION_CONF", "DETECTION_CLASSES", "DETECTION_MOTION_GATE"]:
            monkeypatch.delenv(var, raising=False)
        svc = DetectionService()
        assert svc.stream_url == "rtsp://mediamtx:8554/birdcam"
        assert svc.model_name == "yolo11n.pt"
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
        assert svc.stream_url == "rtsp://other:8554/cam2"
        assert svc.sample_fps == 5.0
        assert svc.classes == {"bird", "cat"}
        assert svc.motion_gate_enabled is False

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
