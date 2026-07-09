"""MQTT bridge to the Pi transmitters.

Subscribes to camera/+/status (retained, so device state is known immediately
on connect) and publishes commands to camera/<pi_id>/control. Runs paho's
network loop in a background thread; safe to read from async handlers.

Env:
    MQTT_ENABLED   "false" to skip connecting (default true)
    MQTT_HOST      default "mosquitto" (compose service name)
    MQTT_PORT      default 1883
    MQTT_USERNAME / MQTT_PASSWORD
"""

import json
import logging
import os
import re
import threading
import time

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

logger = logging.getLogger("mqtt_service")

_PI_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ALLOWED_ACTIONS = {"start", "stop"}

_STATUS_TOPIC_RE = re.compile(r"^camera/([A-Za-z0-9_-]+)/status$")


class MqttDeviceService:
    def __init__(self):
        self.enabled = os.environ.get("MQTT_ENABLED", "true").lower() == "true"
        self.host = os.environ.get("MQTT_HOST", "mosquitto")
        self.port = int(os.environ.get("MQTT_PORT", "1883"))
        self.username = os.environ.get("MQTT_USERNAME") or None
        self.password = os.environ.get("MQTT_PASSWORD") or None

        self.connected = False
        self._client = None
        self._lock = threading.Lock()
        self._devices: dict[str, dict] = {}  # pi_id -> last status payload

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self.enabled:
            logger.info("MQTT disabled (MQTT_ENABLED != true)")
            return
        client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id="backend_stream_control",
            protocol=mqtt.MQTTv5,
        )
        if self.username:
            client.username_pw_set(self.username, self.password)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        # Bounded exponential backoff so a broker restart (e.g. adding users)
        # is recovered from within seconds instead of lingering "down".
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        self._client = client
        try:
            # connect_async + loop_start: non-blocking, auto-reconnects.
            client.connect_async(self.host, self.port, keepalive=60)
            client.loop_start()
            logger.info(f"MQTT bridge connecting to {self.host}:{self.port}")
        except Exception as e:
            logger.error(f"MQTT bridge failed to start: {e}")

    def stop(self) -> None:
        if self._client:
            self._client.loop_stop()
            try:
                self._client.disconnect()
            except Exception:
                pass
        self.connected = False

    # ── paho callbacks (VERSION2 signatures) ─────────────────────────────

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            self.connected = True
            client.subscribe("camera/+/status", qos=1)
            logger.info("MQTT bridge connected, subscribed to camera/+/status")
        else:
            logger.error(f"MQTT bridge connect failed: {reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        logger.warning(f"MQTT bridge disconnected: {reason_code}")

    def _on_message(self, client, userdata, msg):
        m = _STATUS_TOPIC_RE.match(msg.topic)
        if not m:
            return
        pi_id = m.group(1)
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            logger.warning(f"Unparseable status on {msg.topic}")
            return
        payload["pi_id"] = pi_id
        payload["received_at"] = time.time()
        with self._lock:
            self._devices[pi_id] = payload

    # ── API used by controllers ───────────────────────────────────────────

    def is_connected(self) -> bool:
        """Authoritative broker link state, straight from paho's socket/CONNACK
        state. The hand-maintained `self.connected` flag can drift out of sync
        (e.g. after a reconnect where a callback is missed), which showed up as
        a stuck "BROKER DOWN" in the UI while status messages were still
        flowing. paho's is_connected() reflects reality."""
        client = self._client
        return bool(client and client.is_connected())

    def devices(self) -> list[dict]:
        """Latest known status per device, freshest heartbeat first."""
        with self._lock:
            items = [dict(v) for v in self._devices.values()]
        now = time.time()
        for d in items:
            age = now - d.get("received_at", now)
            d["stale"] = age > 30  # heartbeat is every 10s
            d["age_seconds"] = round(age, 1)
        items.sort(key=lambda d: d.get("received_at", 0), reverse=True)
        return items

    def send_control(self, pi_id: str, action: str, params: dict | None = None) -> None:
        """Publish a control command. Raises ValueError on bad input,
        RuntimeError when the broker is unreachable."""
        if not _PI_ID_RE.match(pi_id or ""):
            raise ValueError("Invalid device id")
        if action not in ALLOWED_ACTIONS:
            raise ValueError(f"Action must be one of {sorted(ALLOWED_ACTIONS)}")
        if not self.is_connected():
            raise RuntimeError("MQTT broker not connected")
        payload = {"action": action, **(params or {})}
        result = self._client.publish(
            f"camera/{pi_id}/control", json.dumps(payload), qos=1)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            raise RuntimeError(f"MQTT publish failed (rc={result.rc})")
        logger.info(f"Sent '{action}' to camera/{pi_id}/control")


mqtt_devices = MqttDeviceService()
