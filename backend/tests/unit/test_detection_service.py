"""Unit tests for detection service config parsing and motion gating."""

import os

import numpy as np
import pytest

from services.detection_service import (
    DetectionService,
    MotionGate,
    SpeciesClassifier,
    _crop_bbox,
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


class TestCropBbox:
    def _frame(self, h=240, w=320):
        return np.arange(h * w * 3, dtype=np.uint8).reshape(h, w, 3)

    def test_basic_crop_with_padding(self):
        crop = _crop_bbox(self._frame(), [100, 100, 200, 200])
        # 10% padding on a 100px box -> ~120px per side
        assert crop.shape[0] == pytest.approx(120, abs=2)
        assert crop.shape[1] == pytest.approx(120, abs=2)

    def test_clamped_to_frame_edges(self):
        crop = _crop_bbox(self._frame(), [-50, -50, 100, 100])
        assert crop is not None
        assert crop.shape[0] <= 240 and crop.shape[1] <= 320

    def test_too_small_returns_none(self):
        assert _crop_bbox(self._frame(), [10, 10, 20, 20], min_size=32) is None

    def test_min_size_respected_after_clamping(self):
        # Box mostly outside the frame: clamped crop is tiny -> None
        assert _crop_bbox(self._frame(), [310, 230, 400, 300], min_size=32) is None


class TestSpeciesClassifier:
    def test_classify_without_load_returns_none(self):
        clf = SpeciesClassifier("some/model")
        assert clf.loaded is False
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        assert clf.classify(frame, [10, 10, 100, 100]) is None

    def _loaded_classifier(self, preds, min_conf=0.5):
        clf = SpeciesClassifier("some/model", min_conf=min_conf)
        clf._pipeline = lambda image, top_k: preds
        return clf

    def test_confident_prediction_returned_titlecased(self):
        clf = self._loaded_classifier([{"label": "EURASIAN MAGPIE",
                                        "score": 0.912345}])
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        assert clf.classify(frame, [10, 10, 150, 150]) == \
            ("Eurasian Magpie", 0.912)

    def test_low_confidence_returns_none(self):
        clf = self._loaded_classifier([{"label": "HOUSE SPARROW",
                                        "score": 0.3}])
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        assert clf.classify(frame, [10, 10, 150, 150]) is None

    def test_tiny_bbox_skipped(self):
        clf = self._loaded_classifier([{"label": "ROBIN", "score": 0.99}])
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        assert clf.classify(frame, [10, 10, 15, 15]) is None

    def test_pipeline_error_returns_none(self):
        clf = SpeciesClassifier("some/model")

        def boom(image, top_k):
            raise RuntimeError("inference failed")

        clf._pipeline = boom
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        assert clf.classify(frame, [10, 10, 150, 150]) is None


class FakeSpecies:
    """Stand-in for SpeciesClassifier in _attach_species tests."""

    def __init__(self, result):
        self.result = result
        self.loaded = True
        self.calls = []

    def classify(self, frame, bbox):
        self.calls.append(bbox)
        return self.result


class TestAttachSpecies:
    def _svc(self):
        return DetectionService()

    def test_noop_when_species_disabled(self, monkeypatch):
        monkeypatch.delenv("DETECTION_SPECIES_ENABLED", raising=False)
        svc = self._svc()
        dets = [{"label": "bird", "confidence": 0.9, "bbox": [0, 0, 50, 50]}]
        svc._attach_species(None, dets)
        assert "species" not in dets[0]

    def test_species_attached_to_birds_only(self):
        svc = self._svc()
        fake = FakeSpecies(("Eurasian Magpie", 0.91))
        svc._species = fake
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        dets = [
            {"label": "bird", "confidence": 0.9, "bbox": [0, 0, 50, 50]},
            {"label": "cat", "confidence": 0.8, "bbox": [60, 60, 120, 120]},
        ]
        svc._attach_species(frame, dets)
        assert dets[0]["species"] == "Eurasian Magpie"
        assert dets[0]["species_confidence"] == 0.91
        assert "species" not in dets[1]
        assert fake.calls == [[0, 0, 50, 50]]  # cat bbox never classified

    def test_unconfident_species_leaves_plain_bird(self):
        svc = self._svc()
        svc._species = FakeSpecies(None)
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        dets = [{"label": "bird", "confidence": 0.9, "bbox": [0, 0, 50, 50]}]
        svc._attach_species(frame, dets)
        assert "species" not in dets[0]
        assert dets[0]["label"] == "bird"


class TestDetectionServiceConfig:
    def test_defaults(self, monkeypatch):
        for var in ["DETECTION_STREAM_URL", "DETECTION_MODEL", "DETECTION_FPS",
                    "DETECTION_CONF", "DETECTION_CLASSES", "DETECTION_MOTION_GATE",
                    "DETECTION_SPECIES_ENABLED", "DETECTION_SPECIES_MODEL",
                    "DETECTION_SPECIES_CONF", "DETECTION_SPECIES_MIN_PX"]:
            monkeypatch.delenv(var, raising=False)
        svc = DetectionService()
        assert svc.stream_url == "rtsp://mediamtx:8554/birdcam"
        assert svc.model_name == "yolo11n.pt"
        assert svc.sample_fps == 2.0
        assert svc.conf == 0.4
        assert svc.classes == {"bird", "cat"}
        assert svc.motion_gate_enabled is True
        assert svc.running is False
        assert svc.species_enabled is False
        assert svc._species is None

    def test_species_env_overrides(self, monkeypatch):
        monkeypatch.setenv("DETECTION_SPECIES_ENABLED", "true")
        monkeypatch.setenv("DETECTION_SPECIES_MODEL", "some/other-model")
        monkeypatch.setenv("DETECTION_SPECIES_CONF", "0.7")
        monkeypatch.setenv("DETECTION_SPECIES_MIN_PX", "64")
        svc = DetectionService()
        assert svc.species_enabled is True
        assert svc._species is not None
        assert svc._species.model_name == "some/other-model"
        assert svc._species.min_conf == 0.7
        assert svc._species.min_crop_px == 64
        assert svc._species.loaded is False  # lazy: loads in the worker

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
        assert s["species_active"] is False

    def test_status_species_fields(self, monkeypatch):
        monkeypatch.setenv("DETECTION_SPECIES_ENABLED", "true")
        svc = DetectionService()
        s = svc.status()
        assert s["species_enabled"] is True
        assert s["species_model"] == "dennisjooo/Birds-Classifier-EfficientNetB2"
        assert s["species_active"] is False  # not loaded until worker starts

    def test_latest_and_events_empty(self):
        svc = DetectionService()
        assert svc.get_latest()["detections"] == []
        assert svc.get_events() == []
