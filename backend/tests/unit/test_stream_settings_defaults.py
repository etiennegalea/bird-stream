"""Guards the privacy-sensitive defaults of the stream toggles.

Audio broadcasts whatever the webcam mic picks up, so it must never be
enabled without a deliberate admin action — including after a backend
restart or a settings reset.
"""

import unittest

from services.stream_settings_service import StreamSettingsService


class TestStreamSettingsDefaults(unittest.TestCase):
    def test_audio_disabled_by_default(self):
        svc = StreamSettingsService()
        self.assertFalse(svc.audio_enabled)

    def test_video_enabled_by_default(self):
        svc = StreamSettingsService()
        self.assertTrue(svc.video_enabled)

    def test_reset_turns_audio_back_off(self):
        svc = StreamSettingsService()
        svc.update(audio_enabled=True)
        self.assertTrue(svc.audio_enabled)
        svc.reset()
        self.assertFalse(svc.audio_enabled)

    def test_defaults_do_not_block_the_stream(self):
        # video on + audio off must NOT trip the fully-blocked kill switch
        self.assertFalse(StreamSettingsService().fully_blocked())

    def test_enabling_audio_bumps_version(self):
        svc = StreamSettingsService()
        v = svc.version
        svc.update(audio_enabled=True)
        self.assertEqual(svc.version, v + 1)

    def test_snapshot_reflects_defaults(self):
        self.assertEqual(StreamSettingsService().snapshot(),
                         {"video_enabled": True, "audio_enabled": False})


if __name__ == "__main__":
    unittest.main()
