"""Global stream toggle state (video / audio), controlled by admins.

In-memory singleton — resets to fully enabled on backend restart. Viewers
receive the current state over the public /stream-settings WebSocket and the
GET /stream/settings endpoint; the MediaMTX auth hook additionally denies new
viewer reads while the whole stream (both video and audio) is disabled.
"""

import logging

logger = logging.getLogger("stream_settings_service")


class StreamSettingsService:
    def __init__(self) -> None:
        self.video_enabled: bool = True
        self.audio_enabled: bool = True
        self.version: int = 0  # bumped on every change; used by WS push loop

    def snapshot(self) -> dict:
        return {
            "video_enabled": self.video_enabled,
            "audio_enabled": self.audio_enabled,
        }

    def fully_blocked(self) -> bool:
        return not self.video_enabled and not self.audio_enabled

    def update(
        self,
        video_enabled: bool | None = None,
        audio_enabled: bool | None = None,
    ) -> dict:
        changed = False
        if video_enabled is not None and video_enabled != self.video_enabled:
            self.video_enabled = video_enabled
            changed = True
        if audio_enabled is not None and audio_enabled != self.audio_enabled:
            self.audio_enabled = audio_enabled
            changed = True
        if changed:
            self.version += 1
            logger.info(
                "Stream settings updated: video_enabled=%s audio_enabled=%s",
                self.video_enabled,
                self.audio_enabled,
            )
        return self.snapshot()

    def reset(self) -> None:
        """Restore defaults (used by tests)."""
        self.video_enabled = True
        self.audio_enabled = True
        self.version = 0


stream_settings = StreamSettingsService()
