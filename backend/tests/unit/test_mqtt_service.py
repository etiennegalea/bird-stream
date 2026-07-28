"""Unit tests for the MQTT device bridge (admin panel stream control)."""

import json
import time
import unittest
from unittest import mock

from tests.unit._stubs import ensure_paho

ensure_paho()

from services.mqtt_service import ALLOWED_ACTIONS, MqttDeviceService  # noqa: E402


class FakeResult:
    def __init__(self, rc=0):
        self.rc = rc


class FakeClient:
    def __init__(self, connected=True):
        self.published = []
        self.subscriptions = []
        self._connected = connected

    def is_connected(self):
        return self._connected

    def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))

    def publish(self, topic, payload, qos=0):
        self.published.append((topic, payload, qos))
        return FakeResult(0)

    def loop_stop(self): ...
    def disconnect(self): ...


class Msg:
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = json.dumps(payload).encode() if isinstance(payload, dict) \
            else payload


def make_service(connected=True):
    svc = MqttDeviceService()
    svc._client = FakeClient(connected=connected)
    svc.connected = connected
    return svc


class TestStatusIngestion(unittest.TestCase):
    def test_status_message_stored_per_device(self):
        svc = make_service()
        svc._on_message(None, None, Msg("camera/pi-01/status",
                                        {"status": "streaming", "cpu_temp": 51.2}))
        svc._on_message(None, None, Msg("camera/pi-02/status", {"status": "idle"}))
        devices = svc.devices()
        self.assertEqual({d["pi_id"] for d in devices}, {"pi-01", "pi-02"})

    def test_latest_status_wins(self):
        svc = make_service()
        svc._on_message(None, None, Msg("camera/pi-01/status", {"status": "idle"}))
        svc._on_message(None, None, Msg("camera/pi-01/status", {"status": "streaming"}))
        devices = svc.devices()
        self.assertEqual(len(devices), 1)
        self.assertEqual(devices[0]["status"], "streaming")

    def test_non_matching_topics_ignored(self):
        svc = make_service()
        svc._on_message(None, None, Msg("camera/pi 01/status", {"status": "x"}))
        svc._on_message(None, None, Msg("camera/pi-01/reply", {"status": "x"}))
        svc._on_message(None, None, Msg("weather/pi-01/status", {"status": "x"}))
        self.assertEqual(svc.devices(), [])

    def test_unparseable_payload_ignored(self):
        svc = make_service()
        svc._on_message(None, None, Msg("camera/pi-01/status", b"not json"))
        self.assertEqual(svc.devices(), [])

    def test_fresh_device_not_stale(self):
        svc = make_service()
        svc._on_message(None, None, Msg("camera/pi-01/status", {"status": "idle"}))
        self.assertFalse(svc.devices()[0]["stale"])

    def test_device_stale_after_missed_heartbeats(self):
        svc = make_service()
        svc._on_message(None, None, Msg("camera/pi-01/status", {"status": "streaming"}))
        svc._devices["pi-01"]["received_at"] = time.time() - 60
        device = svc.devices()[0]
        self.assertTrue(device["stale"])
        self.assertGreater(device["age_seconds"], 30)

    def test_devices_sorted_freshest_first(self):
        svc = make_service()
        svc._on_message(None, None, Msg("camera/old/status", {"status": "idle"}))
        svc._devices["old"]["received_at"] = time.time() - 100
        svc._on_message(None, None, Msg("camera/new/status", {"status": "idle"}))
        self.assertEqual([d["pi_id"] for d in svc.devices()], ["new", "old"])

    def test_offline_last_will_keeps_camera_inventory(self):
        svc = make_service()
        streams = [{"camera_id": "cam-1", "path": "birdcam",
                    "enabled": True, "status": "streaming"}]
        svc._on_message(
            None, None,
            Msg("camera/pi-01/status", {"status": "streaming", "streams": streams}),
        )
        svc._on_message(
            None, None, Msg("camera/pi-01/status", {"status": "offline"}))
        self.assertEqual(svc.devices()[0]["streams"], streams)


class TestStreamCatalog(unittest.TestCase):
    def test_only_enabled_streams_are_public(self):
        svc = make_service()
        svc._on_message(None, None, Msg("camera/pi-01/status", {
            "status": "streaming",
            "streams": [
                {"camera_id": "cam-1", "label": "Feeder",
                 "path": "birdcam", "enabled": True, "status": "streaming"},
                {"camera_id": "cam-2", "label": "Nest",
                 "path": "birdcam-pi-01-cam-2", "enabled": False,
                 "status": "idle"},
            ],
        }))
        catalog = svc.stream_catalog()
        self.assertEqual(len(catalog), 1)
        self.assertEqual(catalog[0]["path"], "birdcam")
        self.assertTrue(catalog[0]["available"])

    def test_stale_transmitter_stream_is_listed_but_unavailable(self):
        svc = make_service()
        svc._on_message(None, None, Msg("camera/pi-01/status", {
            "streams": [{
                "camera_id": "cam-1", "path": "birdcam",
                "enabled": True, "status": "streaming",
            }],
        }))
        svc._devices["pi-01"]["received_at"] = time.time() - 60
        item = svc.stream_catalog()[0]
        self.assertEqual(item["status"], "offline")
        self.assertFalse(item["available"])

    def test_legacy_single_camera_status_remains_viewable_during_upgrade(self):
        svc = make_service()
        svc._on_message(None, None, Msg("camera/pi-old/status", {
            "status": "streaming", "path": "birdcam", "audio": False,
        }))
        catalog = svc.stream_catalog()
        self.assertEqual(catalog[0]["path"], "birdcam")
        self.assertEqual(catalog[0]["camera_id"], "cam-1")
        self.assertTrue(catalog[0]["available"])


class TestSendControl(unittest.TestCase):
    def test_publishes_action_to_device_topic(self):
        svc = make_service()
        svc.send_control("pi-01", "start")
        topic, payload, qos = svc._client.published[-1]
        self.assertEqual(topic, "camera/pi-01/control")
        self.assertEqual(json.loads(payload), {"action": "start"})
        self.assertEqual(qos, 1)

    def test_extra_params_included(self):
        svc = make_service()
        svc.send_control("pi-01", "start", params={"fps": 25})
        _, payload, _ = svc._client.published[-1]
        self.assertEqual(json.loads(payload), {"action": "start", "fps": 25})

    def test_all_allowed_actions_accepted(self):
        svc = make_service()
        for action in ALLOWED_ACTIONS:
            params = {"camera_id": "cam-1", "enabled": True} \
                if action == "set_camera_enabled" else None
            svc.send_control("pi-01", action, params=params)
        self.assertEqual(len(svc._client.published), len(ALLOWED_ACTIONS))

    def test_camera_action_validates_and_includes_camera_id(self):
        svc = make_service()
        svc.send_control(
            "pi-01", "start", params={"camera_id": "cam-2"})
        _, payload, _ = svc._client.published[-1]
        self.assertEqual(
            json.loads(payload),
            {"action": "start", "camera_id": "cam-2"},
        )
        with self.assertRaises(ValueError):
            svc.send_control(
                "pi-01", "start", params={"camera_id": "../camera"})

    def test_camera_enabled_requires_boolean(self):
        svc = make_service()
        with self.assertRaises(ValueError):
            svc.send_control(
                "pi-01", "set_camera_enabled",
                params={"camera_id": "cam-1", "enabled": "true"},
            )

    def test_rejects_unknown_action(self):
        svc = make_service()
        with self.assertRaises(ValueError):
            svc.send_control("pi-01", "reboot")

    def test_rejects_invalid_device_ids(self):
        svc = make_service()
        for bad in ["", "pi 01", "../evil", "a/b", "x" * 65, "pi#1"]:
            with self.assertRaises(ValueError, msg=f"accepted {bad!r}"):
                svc.send_control(bad, "start")

    def test_fails_cleanly_when_broker_down(self):
        svc = make_service(connected=False)
        with self.assertRaises(RuntimeError):
            svc.send_control("pi-01", "start")
        self.assertEqual(svc._client.published, [])

    def test_fails_when_publish_rejected(self):
        svc = make_service()
        svc._client.publish = lambda *a, **k: FakeResult(rc=4)
        with self.assertRaises(RuntimeError):
            svc.send_control("pi-01", "start")


class TestLifecycle(unittest.TestCase):
    def test_disabled_service_never_connects(self):
        with mock.patch.dict("os.environ", {"MQTT_ENABLED": "false"}):
            svc = MqttDeviceService()
        svc.start()
        self.assertIsNone(svc._client)
        self.assertFalse(svc.connected)

    @mock.patch("services.mqtt_service.mqtt.Client")
    def test_mutual_tls_configures_ca_and_client_identity(self, client_class):
        client = client_class.return_value
        with mock.patch.dict("os.environ", {
            "MQTT_ENABLED": "true",
            "MQTT_USERNAME": "",
            "MQTT_PASSWORD": "",
            "MQTT_TLS_ENABLED": "true",
            "MQTT_TLS_CA_CERT": "/tls/ca.crt",
            "MQTT_TLS_CLIENT_CERT": "/tls/client.crt",
            "MQTT_TLS_CLIENT_KEY": "/tls/client.key",
        }, clear=True):
            svc = MqttDeviceService()
            svc.start()
        client.tls_set.assert_called_once_with(
            ca_certs="/tls/ca.crt",
            certfile="/tls/client.crt",
            keyfile="/tls/client.key",
        )
        client.username_pw_set.assert_not_called()
        client.connect_async.assert_called_once_with(
            "mosquitto", 1883, keepalive=60,
        )

    @mock.patch("services.mqtt_service.mqtt.Client")
    def test_mutual_tls_missing_path_does_not_connect(self, client_class):
        client = client_class.return_value
        with mock.patch.dict("os.environ", {
            "MQTT_ENABLED": "true",
            "MQTT_TLS_ENABLED": "true",
            "MQTT_TLS_CA_CERT": "/tls/ca.crt",
            "MQTT_TLS_CLIENT_CERT": "",
            "MQTT_TLS_CLIENT_KEY": "/tls/client.key",
        }, clear=True):
            svc = MqttDeviceService()
            svc.start()
        client.connect_async.assert_not_called()

    def test_on_connect_subscribes_to_status_wildcard(self):
        svc = make_service(connected=False)
        client = FakeClient()
        svc._on_connect(client, None, None, 0, None)
        self.assertTrue(svc.connected)
        self.assertIn(("camera/+/status", 1), client.subscriptions)

    def test_failed_connect_does_not_mark_connected(self):
        svc = make_service(connected=False)
        svc._on_connect(FakeClient(), None, None, 5, None)
        self.assertFalse(svc.connected)

    def test_disconnect_clears_connected(self):
        svc = make_service()
        svc._on_disconnect(svc._client, None, None, 1, None)
        self.assertFalse(svc.connected)

    def test_is_connected_reflects_client_state(self):
        # Authoritative broker status comes from the client's socket state,
        # not the hand-maintained flag (which can drift out of sync).
        svc = make_service(connected=True)
        self.assertTrue(svc.is_connected())
        svc._client._connected = False
        self.assertFalse(svc.is_connected())

    def test_is_connected_false_without_client(self):
        svc = MqttDeviceService()
        self.assertFalse(svc.is_connected())


if __name__ == "__main__":
    unittest.main()
