"""Unit tests for the Pi camera agent (FFmpeg command building, config,
overlay escaping, SRT auth). Run with either:

    python -m unittest test_agent -v          (no extra deps needed)
    pytest test_agent.py
"""

import json
import sys
import types
import unittest
from unittest import mock

# The agent imports paho at module level; stub it when not installed so these
# tests run anywhere (paho is present on the Pi via requirements.txt).
try:
    import paho.mqtt.client  # noqa: F401
except ImportError:
    paho = types.ModuleType("paho")
    mqtt_pkg = types.ModuleType("paho.mqtt")
    client = types.ModuleType("paho.mqtt.client")
    enums = types.ModuleType("paho.mqtt.enums")
    client.Client = object
    client.MQTTv5 = 5

    class _CAV:
        VERSION2 = 2

    enums.CallbackAPIVersion = _CAV
    sys.modules.update({"paho": paho, "paho.mqtt": mqtt_pkg,
                        "paho.mqtt.client": client, "paho.mqtt.enums": enums})

import agent  # noqa: E402


def make_agent(**overrides):
    a = agent.CameraAgent.__new__(agent.CameraAgent)
    a.config = json.loads(json.dumps(agent.DEFAULT_CONFIG))  # deep copy
    for dotted, value in overrides.items():
        node = a.config
        keys = dotted.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return a


class TestDeepMerge(unittest.TestCase):
    def test_nested_override(self):
        merged = agent.deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3}})
        self.assertEqual(merged, {"a": {"b": 1, "c": 3}})

    def test_none_override_is_noop(self):
        self.assertEqual(agent.deep_merge({"a": 1}, None), {"a": 1})

    def test_new_keys_added(self):
        self.assertEqual(agent.deep_merge({"a": 1}, {"b": 2}), {"a": 1, "b": 2})


class TestDrawtextFilter(unittest.TestCase):
    def test_default_format_uses_noarg_localtime(self):
        vf = make_agent()._drawtext_filter()
        self.assertIn("text='%{localtime}'", vf)
        self.assertNotIn("\\:", vf)  # no escaping needed for the default

    def test_custom_format_triple_escapes_colons(self):
        vf = make_agent(**{"overlay.time_format": "%H:%M"})._drawtext_filter()
        self.assertIn(r"%{localtime\:%H\\\:%M}", vf)

    def test_disabled_overlay_returns_none(self):
        self.assertIsNone(make_agent(**{"overlay.enabled": False})._drawtext_filter())


class TestSrtUrl(unittest.TestCase):
    def test_url_without_credentials(self):
        url = make_agent()._srt_url("host", 8890)
        self.assertEqual(url, "srt://host:8890?mode=caller&streamid=publish:birdcam")

    def test_url_with_credentials(self):
        a = make_agent(**{"stream.srt.username": "picam",
                          "stream.srt.password": "pw"})
        self.assertEqual(a._srt_url("host", 8890),
                         "srt://host:8890?mode=caller&streamid=publish:birdcam:picam:pw")

    def test_custom_path(self):
        a = make_agent(**{"stream.srt.path": "cam2"})
        self.assertIn("streamid=publish:cam2", a._srt_url("h", 1))

    def test_path_argument_overrides_config_for_additional_camera(self):
        a = make_agent(**{"stream.srt.path": "birdcam"})
        self.assertIn(
            "streamid=publish:birdcam-pi-01-cam-2",
            a._srt_url("h", 8890, "birdcam-pi-01-cam-2"),
        )


class TestCameraDiscovery(unittest.TestCase):
    def _agent(self):
        a = make_agent()
        a.pi_id = "pi-01"
        a.config["camera"]["auto_detect"] = True
        return a

    def test_detects_each_capture_device_and_assigns_paths(self):
        a = self._agent()
        by_id = "/dev/v4l/by-id/usb-one-video-index0"
        with mock.patch.object(agent.glob, "glob") as glob_mock, \
                mock.patch.object(a, "_is_capture_device", return_value=True), \
                mock.patch.object(agent.os.path, "realpath", side_effect=lambda p: p):
            glob_mock.side_effect = lambda pattern: (
                [by_id] if "by-id" in pattern else ["/dev/video2"]
            )
            cameras = a.discover_cameras()
        self.assertEqual([c["id"] for c in cameras], ["usb-one", "video2"])
        self.assertEqual(
            [c["path"] for c in cameras],
            ["birdcam", "birdcam-pi-01-video2"],
        )
        self.assertTrue(all(c["enabled"] for c in cameras))

    def test_by_id_and_video_node_for_same_camera_are_deduplicated(self):
        a = self._agent()
        by_id = "/dev/v4l/by-id/usb-one-video-index0"
        real = {by_id: "/dev/video0", "/dev/video0": "/dev/video0"}
        with mock.patch.object(agent.glob, "glob") as glob_mock, \
                mock.patch.object(a, "_is_capture_device", return_value=True), \
                mock.patch.object(
                    agent.os.path, "realpath", side_effect=lambda p: real.get(p, p)):
            glob_mock.side_effect = lambda pattern: (
                [by_id] if "by-id" in pattern else ["/dev/video0"]
            )
            cameras = a.discover_cameras()
        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0]["device"], by_id)

    def test_persisted_primary_path_does_not_shift_when_camera_is_removed(self):
        a = self._agent()
        a.config["camera"]["primary_id"] = "usb-one"
        with mock.patch.object(agent.glob, "glob") as glob_mock, \
                mock.patch.object(a, "_is_capture_device", return_value=True), \
                mock.patch.object(agent.os.path, "realpath", side_effect=lambda p: p):
            glob_mock.side_effect = lambda pattern: (
                [] if "by-id" in pattern else ["/dev/video2"]
            )
            cameras = a.discover_cameras()
        self.assertEqual(cameras[0]["id"], "video2")
        self.assertEqual(cameras[0]["path"], "birdcam-pi-01-video2")

    def test_config_override_sets_stable_identity_and_disabled_state(self):
        a = self._agent()
        a.config["camera"]["devices"] = [{
            "id": "Nest Box",
            "label": "Nest camera",
            "device": "/dev/video4",
            "enabled": False,
            "bitrate": "2500k",
        }]
        with mock.patch.object(agent.glob, "glob", return_value=[]), \
                mock.patch.object(a, "_is_capture_device", return_value=True), \
                mock.patch.object(agent.os.path, "realpath", side_effect=lambda p: p):
            camera = a.discover_cameras()[0]
        self.assertEqual(camera["id"], "nest-box")
        self.assertEqual(camera["label"], "Nest camera")
        self.assertFalse(camera["enabled"])
        self.assertEqual(camera["bitrate"], "2500k")


class LinuxCmdMixin:
    """Force the Linux/Pi branch regardless of the test host platform."""

    def build(self, a, use_hw=False):
        real = sys.platform
        sys.platform = "linux"
        try:
            return a._build_ffmpeg_cmd("host", 8890, 1280, 720, 30, "1500k",
                                       "/dev/video0", use_hw)
        finally:
            sys.platform = real


class TestFfmpegCommand(LinuxCmdMixin, unittest.TestCase):
    def test_video_only_by_default(self):
        cmd = self.build(make_agent())
        self.assertEqual(cmd.count("-i"), 1)
        self.assertNotIn("libopus", cmd)
        self.assertNotIn("alsa", cmd)

    def test_forces_yuv420p(self):
        # Browsers cannot decode H264 4:2:2 (MJPEG cams deliver yuvj422p)
        cmd = self.build(make_agent())
        self.assertIn("-pix_fmt", cmd)
        self.assertEqual(cmd[cmd.index("-pix_fmt") + 1], "yuv420p")

    def test_software_encoder_by_default(self):
        cmd = self.build(make_agent())
        self.assertIn("libx264", cmd)
        self.assertNotIn("h264_v4l2m2m", cmd)

    def test_hw_encoder_when_requested(self):
        cmd = self.build(make_agent(), use_hw=True)
        self.assertIn("h264_v4l2m2m", cmd)
        self.assertNotIn("libx264", cmd)

    def test_gop_is_two_seconds(self):
        cmd = self.build(make_agent())
        self.assertEqual(cmd[cmd.index("-g") + 1], "60")  # 30 fps * 2

    def test_ends_with_mpegts_and_srt_url(self):
        cmd = self.build(make_agent())
        self.assertEqual(cmd[-2], "mpegts")
        self.assertTrue(cmd[-1].startswith("srt://host:8890"))

    def test_overlay_filter_included(self):
        cmd = self.build(make_agent())
        self.assertIn("-vf", cmd)
        self.assertIn("drawtext", cmd[cmd.index("-vf") + 1])


class TestFfmpegAudio(LinuxCmdMixin, unittest.TestCase):
    def _audio_agent(self, **extra):
        return make_agent(**{"audio.enabled": True, **extra})

    def test_audio_adds_alsa_input_and_opus(self):
        cmd = self.build(self._audio_agent())
        self.assertEqual(cmd.count("-i"), 2)
        self.assertIn("alsa", cmd)
        self.assertIn("libopus", cmd)

    def test_opus_uses_48k(self):
        cmd = self.build(self._audio_agent())
        self.assertEqual(cmd[cmd.index("-ar") + 1], "48000")

    def test_alsa_input_precedes_encoders(self):
        cmd = self.build(self._audio_agent())
        self.assertLess(cmd.index("alsa"), cmd.index("-c:v"))

    def test_audio_device_and_channels_from_config(self):
        cmd = self.build(self._audio_agent(**{"audio.device": "hw:1,0",
                                              "audio.channels": 2}))
        self.assertIn("hw:1,0", cmd)
        self.assertEqual(cmd[cmd.index("-ac") + 1], "2")


class TestStreamDetailsAndActions(unittest.TestCase):
    def test_camera_keys_whitelist(self):
        self.assertIn("bitrate", agent.CAMERA_KEYS)
        self.assertNotIn("id", agent.CAMERA_KEYS)

    def test_get_config_masks_secrets(self):
        a = make_agent(**{"mqtt.password": "hunter2",
                          "stream.srt.password": "hunter2"})
        replies = []
        a.publish_reply = lambda action, data, request_id=None: replies.append(data)
        a.action_get_config({})
        cfg = replies[0]["config"]
        self.assertEqual(cfg["mqtt"]["password"], "***")
        self.assertEqual(cfg["stream"]["srt"]["password"], "***")
        # the real config must be untouched
        self.assertEqual(a.config["mqtt"]["password"], "hunter2")

    def test_status_contains_independent_streams(self):
        a = make_agent()
        a.pi_id = "pi-01"
        a.streams = {
            "cam-1": {
                "process": mock.Mock(poll=lambda: None),
                "status": "streaming",
                "details": {"width": 1280, "audio": True},
            },
            "cam-2": {
                "process": None,
                "status": "idle",
                "details": {},
            },
        }
        a.discover_cameras = lambda: [
            {"id": "cam-1", "label": "Camera 1", "device": "/dev/video0",
             "enabled": True, "path": "birdcam"},
            {"id": "cam-2", "label": "Camera 2", "device": "/dev/video2",
             "enabled": False, "path": "birdcam-pi-01-cam-2"},
        ]
        a._window_bounds = lambda: None
        a._in_window = lambda: True
        published = []
        a.client = mock.Mock()
        a.client.publish.side_effect = \
            lambda topic, body, **kwargs: published.append(json.loads(body))
        a.topic_status = "camera/pi-01/status"
        a.publish_status()
        payload = published[-1]
        self.assertEqual(payload["status"], "streaming")
        self.assertEqual(len(payload["streams"]), 2)
        self.assertEqual(payload["streams"][0]["path"], "birdcam")
        self.assertFalse(payload["streams"][1]["enabled"])

    def test_disable_camera_is_persisted_and_stopped(self):
        a = make_agent()
        a.pi_id = "pi-01"
        a.streams = {}
        camera = {
            "id": "cam-2", "label": "Camera 2", "device": "/dev/video2",
            "real_device": "/dev/video2", "enabled": True,
            "path": "birdcam-pi-01-cam-2", "index": 1,
        }
        a.discover_cameras = lambda: [camera]
        a._save_config = mock.Mock()
        a.stop_stream = mock.Mock()
        a.publish_status = mock.Mock()
        replies = []
        a.publish_reply = lambda action, data, request_id=None: replies.append(data)
        a.action_set_camera_enabled({
            "camera_id": "cam-2", "enabled": False,
        })
        self.assertFalse(a.config["camera"]["devices"][0]["enabled"])
        a.stop_stream.assert_called_once_with(manual=True, camera_id="cam-2")
        self.assertTrue(replies[-1]["ok"])


class TestMultiCameraProcesses(unittest.TestCase):
    def test_start_all_launches_one_ffmpeg_process_per_enabled_camera(self):
        a = make_agent(**{
            "stream.srt.host": "server",
            "audio.enabled": True,
            "schedule.enabled": False,
        })
        a.pi_id = "pi-01"
        a.streams = {}
        a.should_stream = False
        a.last_start_params = {}
        a.lock = mock.MagicMock()
        cameras = [
            {"id": "primary", "label": "Primary", "device": "/dev/video0",
             "enabled": True, "path": "birdcam", "index": 0},
            {"id": "second", "label": "Second", "device": "/dev/video2",
             "enabled": True, "path": "birdcam-pi-01-second", "index": 1},
        ]
        a.discover_cameras = lambda: cameras
        a.publish_status = mock.Mock()
        processes = []

        def fake_popen(command, **kwargs):
            process = mock.Mock()
            process.poll.return_value = None
            process.command = command
            processes.append(process)
            return process

        with mock.patch.object(agent.subprocess, "Popen", side_effect=fake_popen), \
                mock.patch.object(agent.time, "sleep"), \
                mock.patch("agent.threading.Thread") as thread:
            a.start_stream({})

        self.assertEqual(len(processes), 2)
        first, second = (p.command for p in processes)
        self.assertIn("streamid=publish:birdcam", first[-1])
        self.assertIn("streamid=publish:birdcam-pi-01-second", second[-1])
        self.assertIn("libopus", first)
        self.assertNotIn("libopus", second)
        self.assertEqual(thread.call_count, 2)

    def test_disabled_camera_does_not_launch_process(self):
        a = make_agent(**{
            "stream.srt.host": "server",
            "schedule.enabled": False,
        })
        a.pi_id = "pi-01"
        a.streams = {}
        a.should_stream = False
        a.last_start_params = {}
        a.lock = mock.MagicMock()
        a.discover_cameras = lambda: [{
            "id": "disabled", "label": "Disabled", "device": "/dev/video2",
            "enabled": False, "path": "birdcam-pi-01-disabled", "index": 1,
        }]
        a.publish_status = mock.Mock()
        with mock.patch.object(agent.subprocess, "Popen") as popen:
            a.start_stream({})
        popen.assert_not_called()


def _at(hour, minute=0):
    """A time.struct_time for a given local hour/minute (date is irrelevant)."""
    import time as _t
    return _t.struct_time((2024, 1, 1, hour, minute, 0, 0, 1, -1))


class TestParseHHMM(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(agent._parse_hhmm("00:00"), 0)
        self.assertEqual(agent._parse_hhmm("06:30"), 390)
        self.assertEqual(agent._parse_hhmm("23:59"), 1439)

    def test_invalid(self):
        for bad in ["24:00", "6:60", "abc", "12", "", None, "12:99", "99:00"]:
            self.assertIsNone(agent._parse_hhmm(bad), msg=f"accepted {bad!r}")


class TestScheduleWindow(unittest.TestCase):
    def _agent(self, enabled=True, start="06:00", end="20:00"):
        return make_agent(**{"schedule.enabled": enabled, "schedule.mode": "fixed",
                             "schedule.start": start, "schedule.end": end})

    def test_disabled_always_in_window(self):
        a = self._agent(enabled=False)
        with mock.patch.object(agent.time, "localtime", return_value=_at(3)):
            self.assertTrue(a._in_window())

    def test_daytime_window(self):
        a = self._agent(start="06:00", end="20:00")
        for hour, expected in [(5, False), (6, True), (12, True),
                               (19, True), (20, False), (23, False)]:
            with mock.patch.object(agent.time, "localtime",
                                   return_value=_at(hour)):
                self.assertEqual(a._in_window(), expected, msg=f"hour {hour}")

    def test_overnight_window_wraps_midnight(self):
        a = self._agent(start="22:00", end="06:00")
        for hour, expected in [(22, True), (23, True), (0, True), (5, True),
                               (6, False), (12, False), (21, False)]:
            with mock.patch.object(agent.time, "localtime",
                                   return_value=_at(hour)):
                self.assertEqual(a._in_window(), expected, msg=f"hour {hour}")

    def test_malformed_window_does_not_restrict(self):
        a = self._agent(start="nope", end="20:00")
        with mock.patch.object(agent.time, "localtime", return_value=_at(3)):
            self.assertTrue(a._in_window())


class TestSunSchedule(unittest.TestCase):
    def _agent(self):
        # Explicit lat/lon avoids any network geolocation. London, Jan 1
        # (via _at's date): sunrise ~08:06, sunset ~16:02 UTC.
        return make_agent(**{
            "schedule.enabled": True, "schedule.mode": "sun",
            "schedule.latitude": 51.5, "schedule.longitude": -0.1,
        })

    def test_streams_during_daylight_rests_at_night(self):
        a = self._agent()
        for hour, expected in [(4, False), (12, True), (20, False)]:
            with mock.patch.object(agent.time, "localtime",
                                   return_value=_at(hour)):
                self.assertEqual(a._in_window(), expected, msg=f"hour {hour}")

    def test_window_bounds_are_sunrise_sunset(self):
        a = self._agent()
        with mock.patch.object(agent.time, "localtime", return_value=_at(12)):
            start, end = a._window_bounds()
        # Morning sunrise, afternoon sunset, and sunrise before sunset.
        self.assertTrue(6 * 60 < start < 10 * 60, msg=start)
        self.assertTrue(14 * 60 < end < 18 * 60, msg=end)
        self.assertLess(start, end)

    def test_polar_night_falls_back_to_fixed(self):
        # Far north in deep winter: no sunrise → fall back to fixed start/end.
        a = make_agent(**{
            "schedule.enabled": True, "schedule.mode": "sun",
            "schedule.latitude": 78.2, "schedule.longitude": 15.6,  # Svalbard
            "schedule.start": "09:00", "schedule.end": "15:00",
        })
        with mock.patch.object(agent.time, "localtime", return_value=_at(12)):
            self.assertEqual(a._window_bounds(), (9 * 60, 15 * 60))


class TestSetScheduleAction(unittest.TestCase):
    def _agent(self):
        a = make_agent()
        a._save_config = lambda: None
        a._apply_schedule = lambda: None
        a._is_streaming = lambda: False
        a.start_stream = lambda params: None
        a.replies = []
        a.publish_reply = lambda action, data, request_id=None: a.replies.append(data)
        return a

    def test_enable_fixed_updates_config(self):
        a = self._agent()
        a.action_set_schedule({"enabled": True, "mode": "fixed",
                               "start": "07:00", "end": "19:30"})
        s = a.config["schedule"]
        self.assertEqual((s["enabled"], s["mode"], s["start"], s["end"]),
                         (True, "fixed", "07:00", "19:30"))
        self.assertTrue(a.replies[-1]["ok"])

    def test_enable_sun_mode(self):
        a = self._agent()
        a.action_set_schedule({"enabled": True, "mode": "sun",
                               "latitude": 51.5, "longitude": -0.1})
        s = a.config["schedule"]
        self.assertEqual((s["enabled"], s["mode"]), (True, "sun"))
        self.assertEqual((s["latitude"], s["longitude"]), (51.5, -0.1))
        self.assertTrue(a.replies[-1]["ok"])

    def test_fixed_mode_invalid_time_rejected(self):
        a = self._agent()
        a.action_set_schedule({"enabled": True, "mode": "fixed",
                               "start": "7am", "end": "19:30"})
        self.assertFalse(a.replies[-1]["ok"])
        # config untouched (still the default schedule)
        self.assertEqual(a.config["schedule"]["start"], "06:00")

    def test_invalid_mode_rejected(self):
        a = self._agent()
        a.action_set_schedule({"enabled": True, "mode": "banana"})
        self.assertFalse(a.replies[-1]["ok"])

    def test_disable_clears_flag(self):
        a = self._agent()
        a.action_set_schedule({"enabled": False})
        self.assertFalse(a.config["schedule"]["enabled"])
        self.assertTrue(a.replies[-1]["ok"])


if __name__ == "__main__":
    unittest.main()
