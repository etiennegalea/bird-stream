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
        return make_agent(**{"schedule.enabled": enabled,
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

    def test_enable_valid_updates_config(self):
        a = self._agent()
        a.action_set_schedule({"enabled": True, "start": "07:00", "end": "19:30"})
        self.assertEqual(a.config["schedule"],
                         {"enabled": True, "start": "07:00", "end": "19:30"})
        self.assertTrue(a.replies[-1]["ok"])

    def test_enable_invalid_time_rejected(self):
        a = self._agent()
        a.action_set_schedule({"enabled": True, "start": "7am", "end": "19:30"})
        self.assertFalse(a.replies[-1]["ok"])
        # config must be untouched (still the default disabled schedule)
        self.assertFalse(a.config["schedule"]["enabled"])

    def test_disable_clears_flag(self):
        a = self._agent()
        a.config["schedule"] = {"enabled": True, "start": "06:00", "end": "20:00"}
        a.action_set_schedule({"enabled": False})
        self.assertFalse(a.config["schedule"]["enabled"])
        self.assertTrue(a.replies[-1]["ok"])


if __name__ == "__main__":
    unittest.main()
