"""Global stream state (video / audio / viewer access), controlled by admins.

In-memory singleton — resets on backend restart to video ENABLED but audio
DISABLED: audio broadcasts whatever the webcam mic picks up, so enabling it
must be a deliberate admin action every time, never an accidental leftover.
The private-viewing flag is persisted in Postgres because losing that setting
on a restart could unintentionally expose a stream. Viewers receive the
current state over the public /stream-settings WebSocket and GET endpoint;
the MediaMTX auth hook enforces the access decision independently of the UI.
"""

import logging

from models.orm import StreamConfiguration

logger = logging.getLogger("stream_settings_service")

_CONFIGURATION_ID = 1


class StreamSettingsService:
    def __init__(self) -> None:
        self.video_enabled: bool = True
        self.audio_enabled: bool = False  # privacy: audio is opt-in, always
        self.private_enabled: bool = False
        self.version: int = 0  # bumped on every change; used by WS push loop

    def snapshot(self) -> dict:
        return {
            "video_enabled": self.video_enabled,
            "audio_enabled": self.audio_enabled,
            "private_enabled": self.private_enabled,
        }

    def fully_blocked(self) -> bool:
        return not self.video_enabled and not self.audio_enabled

    def update(
        self,
        video_enabled: bool | None = None,
        audio_enabled: bool | None = None,
        private_enabled: bool | None = None,
        db_factory=None,
    ) -> dict:
        changed = False
        if video_enabled is not None and video_enabled != self.video_enabled:
            self.video_enabled = video_enabled
            changed = True
        if audio_enabled is not None and audio_enabled != self.audio_enabled:
            self.audio_enabled = audio_enabled
            changed = True
        if private_enabled is not None and private_enabled != self.private_enabled:
            if db_factory is not None:
                self._persist_private_setting(db_factory, private_enabled)
            self.private_enabled = private_enabled
            changed = True
        if changed:
            self.version += 1
            logger.info(
                "Stream settings updated: video_enabled=%s audio_enabled=%s "
                "private_enabled=%s",
                self.video_enabled,
                self.audio_enabled,
                self.private_enabled,
            )
        return self.snapshot()

    def load(self, db_factory) -> None:
        """Load the persisted privacy setting, creating its singleton row."""
        with db_factory() as session:
            config = session.get(StreamConfiguration, _CONFIGURATION_ID)
            if config is None:
                config = StreamConfiguration(
                    id=_CONFIGURATION_ID,
                    private_enabled=self.private_enabled,
                )
                session.add(config)
                session.commit()
            else:
                self.private_enabled = config.private_enabled
        logger.info(
            "Loaded persisted stream privacy setting: private_enabled=%s",
            self.private_enabled,
        )

    def _persist_private_setting(self, db_factory, private_enabled: bool) -> None:
        with db_factory() as session:
            config = session.get(StreamConfiguration, _CONFIGURATION_ID)
            if config is None:
                config = StreamConfiguration(id=_CONFIGURATION_ID)
                session.add(config)
            config.private_enabled = private_enabled
            session.commit()

    def reset(self) -> None:
        """Restore defaults (used by tests)."""
        self.video_enabled = True
        self.audio_enabled = False  # keep in sync with __init__
        self.private_enabled = False
        self.version = 0


stream_settings = StreamSettingsService()
