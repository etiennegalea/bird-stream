"""Per-transmitter automation for secondary cameras designated as POV."""

import logging
import threading
from urllib import parse

from sqlalchemy import select

from models.orm import DeviceCameraAutomation

logger = logging.getLogger("camera_automation_service")


def _is_pov(stream: dict) -> bool:
    """Recognize the explicit role and legacy configs named exactly `pov`."""
    if str(stream.get("role", "")).strip().lower() == "pov":
        return True
    return any(
        str(stream.get(key, "")).strip().lower() == "pov"
        for key in ("camera_id", "label")
    )


class CameraAutomationService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._settings: dict[str, dict[str, bool]] = {}
        self._devices: dict[str, dict] = {}
        self._mqtt = None
        self._triggered_devices: set[str] = set()
        self._primary_bird_present: set[str] = set()
        self._pov_cat_present: dict[str, bool | None] = {}

    @staticmethod
    def defaults() -> dict[str, bool]:
        return {"auto_manage_pov": False, "bird_triggered_pov": False}

    def load(self, db_factory) -> None:
        with db_factory() as session:
            rows = session.execute(select(DeviceCameraAutomation)).scalars().all()
            loaded = {
                row.pi_id: {
                    "auto_manage_pov": row.auto_manage_pov,
                    "bird_triggered_pov": row.bird_triggered_pov,
                }
                for row in rows
            }
        with self._lock:
            self._settings = loaded
        logger.info("Loaded POV camera automation for %d device(s)", len(loaded))

    def attach_mqtt(self, mqtt_service) -> None:
        self._mqtt = mqtt_service

    def snapshot(self, pi_id: str) -> dict[str, bool]:
        with self._lock:
            return dict(self._settings.get(pi_id, self.defaults()))

    def describe_device(self, device: dict) -> dict:
        result = self.snapshot(device["pi_id"])
        streams = device.get("streams") or []
        has_explicit_primary = any(
            stream.get("primary", False) for stream in streams
        )
        result["has_pov_camera"] = any(
            _is_pov(stream)
            and not self._is_primary(stream, index, has_explicit_primary)
            for index, stream in enumerate(streams)
        )
        return result

    def update(
        self,
        pi_id: str,
        *,
        auto_manage_pov: bool,
        bird_triggered_pov: bool,
        db_factory,
    ) -> dict:
        with db_factory() as session:
            row = session.get(DeviceCameraAutomation, pi_id)
            if row is None:
                row = DeviceCameraAutomation(pi_id=pi_id)
                session.add(row)
            row.auto_manage_pov = auto_manage_pov
            # The child option has no effect without its parent. Persisting it
            # as false also keeps the API and UI state unambiguous.
            row.bird_triggered_pov = bool(
                auto_manage_pov and bird_triggered_pov
            )
            session.commit()
        settings = {
            "auto_manage_pov": auto_manage_pov,
            "bird_triggered_pov": bool(auto_manage_pov and bird_triggered_pov),
        }
        with self._lock:
            self._settings[pi_id] = settings
            device = self._devices.get(pi_id)
            was_triggered = pi_id in self._triggered_devices
            if not settings["bird_triggered_pov"]:
                self._clear_trigger_locked(pi_id)
        if was_triggered and not settings["bird_triggered_pov"] and device:
            self._control_pov(device, "stop")
        if device:
            self._reconcile(device)
        return dict(settings)

    def handle_device_status(self, device: dict) -> None:
        """Remember inventory and enforce automation after each heartbeat."""
        pi_id = device.get("pi_id")
        if not pi_id:
            return
        with self._lock:
            self._devices[pi_id] = dict(device)
        self._reconcile(device)

    def device_id_for_stream_url(self, stream_url: str | None) -> str | None:
        """Resolve the Pi that owns the detection worker's current RTSP path."""
        if not stream_url:
            return None
        path = parse.unquote(parse.urlparse(stream_url).path).lstrip("/")
        with self._lock:
            devices = list(self._devices.values())
        for device in devices:
            if any(
                stream.get("path") == path
                for stream in device.get("streams") or []
            ):
                return device["pi_id"]
        return None

    def bird_detection_triggered(self, pi_id: str | None) -> None:
        """Start POV when the same linger/cooldown gate as an alert passes."""
        if pi_id is None:
            logger.warning(
                "POV trigger skipped: detection stream has no matching Pi"
            )
            return
        settings = self.snapshot(pi_id)
        if not (
            settings["auto_manage_pov"] and settings["bird_triggered_pov"]
        ):
            return
        with self._lock:
            self._triggered_devices.add(pi_id)
            self._primary_bird_present.add(pi_id)
            # Unknown until the POV monitor sees a frame. This prevents an
            # immediate stop while the newly-started stream is coming online.
            self._pov_cat_present[pi_id] = None
            device = self._devices.get(pi_id)
        if device:
            self._start_triggered_pov(device)

    def bird_presence_ended(self) -> None:
        """Mark primary birds absent; cats on POV may keep streaming active."""
        with self._lock:
            active_ids = set(self._triggered_devices)
            self._primary_bird_present.difference_update(active_ids)
        for pi_id in active_ids:
            self._stop_if_clear(pi_id)

    def pov_cat_presence_changed(self, pi_id: str, present: bool) -> None:
        """Receive generic cat presence from the active POV stream monitor."""
        with self._lock:
            if pi_id not in self._triggered_devices:
                return
            self._pov_cat_present[pi_id] = present
        self._stop_if_clear(pi_id)

    def active_pov_target(self) -> dict | None:
        """Return the active POV path that needs cat monitoring, if any."""
        with self._lock:
            pi_ids = sorted(self._triggered_devices)
            devices = {key: self._devices.get(key) for key in pi_ids}
        for pi_id in pi_ids:
            device = devices.get(pi_id)
            if not device:
                continue
            streams = device.get("streams") or []
            has_explicit_primary = any(
                stream.get("primary", False) for stream in streams
            )
            for index, stream in enumerate(streams):
                if (
                    not self._is_primary(stream, index, has_explicit_primary)
                    and _is_pov(stream)
                    and stream.get("path")
                ):
                    return {"pi_id": pi_id, "path": stream["path"]}
        return None

    def _stop_if_clear(self, pi_id: str) -> None:
        with self._lock:
            if (
                pi_id not in self._triggered_devices
                or pi_id in self._primary_bird_present
                or self._pov_cat_present.get(pi_id) is not False
            ):
                return
            device = self._devices.get(pi_id)
            self._clear_trigger_locked(pi_id)
        if device:
            self._control_pov(device, "stop")

    def _clear_trigger_locked(self, pi_id: str) -> None:
        self._triggered_devices.discard(pi_id)
        self._primary_bird_present.discard(pi_id)
        self._pov_cat_present.pop(pi_id, None)

    def _reconcile(self, device: dict) -> None:
        settings = self.snapshot(device["pi_id"])
        if (
            not settings["auto_manage_pov"]
            or device.get("stale")
            or device.get("status") == "offline"
        ):
            return

        # A managed secondary camera is public/enabled exactly when it is
        # designated POV. Primary cameras are never changed by this feature.
        streams = device.get("streams") or []
        has_explicit_primary = any(
            stream.get("primary", False) for stream in streams
        )
        for index, stream in enumerate(streams):
            if self._is_primary(stream, index, has_explicit_primary):
                continue
            desired = _is_pov(stream)
            if bool(stream.get("enabled", True)) != desired:
                self._send(
                    device["pi_id"], "set_camera_enabled",
                    {"camera_id": stream.get("camera_id"), "enabled": desired},
                )

        if settings["bird_triggered_pov"]:
            with self._lock:
                active = device["pi_id"] in self._triggered_devices
            if active:
                self._start_triggered_pov(device)
            else:
                self._control_pov(device, "stop", only_if_streaming=True)
        elif not device.get("resting", False):
            # In normal managed mode, keep the POV camera running whenever the
            # Pi is inside its broadcast window. A reported resting state is
            # respected so this automation does not defeat the Pi schedule.
            self._control_pov(device, "start", only_if_idle=True)

    def _start_triggered_pov(self, device: dict) -> None:
        settings = self.snapshot(device["pi_id"])
        if not (
            settings["auto_manage_pov"] and settings["bird_triggered_pov"]
        ) or device.get("stale") or device.get("status") == "offline":
            return
        self._control_pov(device, "start", only_if_idle=True)

    def _control_pov(
        self,
        device: dict,
        action: str,
        *,
        only_if_streaming: bool = False,
        only_if_idle: bool = False,
    ) -> None:
        streams = device.get("streams") or []
        has_explicit_primary = any(
            stream.get("primary", False) for stream in streams
        )
        for index, stream in enumerate(streams):
            if (
                self._is_primary(stream, index, has_explicit_primary)
                or not _is_pov(stream)
            ):
                continue
            status = stream.get("status")
            if only_if_streaming and status != "streaming":
                continue
            if only_if_idle and status == "streaming":
                continue
            self._send(
                device["pi_id"], action,
                {"camera_id": stream.get("camera_id")},
            )

    @staticmethod
    def _is_primary(
        stream: dict, index: int, has_explicit_primary: bool
    ) -> bool:
        # Rolling-upgrade safety: old agents do not report `primary`, and the
        # first inventory entry has always been the primary stream.
        return bool(stream.get("primary", False)) or (
            not has_explicit_primary and index == 0
        )

    def _send(self, pi_id: str, action: str, params: dict) -> None:
        if not self._mqtt or not params.get("camera_id"):
            return
        try:
            self._mqtt.send_control(pi_id, action, params=params)
        except (ValueError, RuntimeError) as exc:
            logger.warning(
                "Unable to apply POV automation to %s/%s: %s",
                pi_id, params.get("camera_id"), exc,
            )

    def reset(self) -> None:
        """Restore isolated defaults for tests."""
        with self._lock:
            self._settings = {}
            self._devices = {}
            self._triggered_devices = set()
            self._primary_bird_present = set()
            self._pov_cat_present = {}
        self._mqtt = None


camera_automation = CameraAutomationService()
