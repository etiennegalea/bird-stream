import json
import logging
import os
import yaml
import paho.mqtt.client as mqtt
from src.components.event_logger import log_event
from src.utils import get_secrets_path

logger = logging.getLogger("backend | mqtt_handler")

# Thread-safe global state for camera
CAMERA_STATUS = {
    "status": "offline",
    "timestamp": None,
    "cpu_temp": None,
    "srt_destination": None,
    "width": None,
    "height": None,
    "fps": None,
    "bitrate": None,
    "error": None
}

client = None

def load_mqtt_config():
    """Loads MQTT broker host, port and optional auth from .secrets.yaml."""
    host = "localhost"
    port = 1883
    username = None
    password = None

    secrets_path = get_secrets_path()
    if os.path.exists(secrets_path):
        try:
            with open(secrets_path, 'r') as file:
                secrets = yaml.safe_load(file)
                if secrets:
                    host = secrets.get("MQTT_HOST", host)
                    port = secrets.get("MQTT_PORT", port)
                    username = secrets.get("MQTT_USERNAME", username)
                    password = secrets.get("MQTT_PASSWORD", password)
        except Exception as e:
            logger.error(f"Error loading MQTT config from secrets: {e}")

    return host, port, username, password

def on_connect(client, userdata, flags, rc, properties=None):
    """Callback when client connects to broker."""
    # rc is reason_code in paho-mqtt v2.x (0 represents success)
    if rc == 0 or (hasattr(rc, "is_failure") and not rc.is_failure):
        logger.info("MQTT client connected to broker successfully")
        client.subscribe("camera/status", qos=1)
    else:
        logger.error(f"MQTT connection failed with code {rc}")

def on_message(client, userdata, msg):
    """Callback when a message is received from the broker."""
    global CAMERA_STATUS
    if msg.topic == "camera/status":
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            new_status = payload.get("status", "offline")
            old_status = CAMERA_STATUS.get("status", "offline")

            # Reset dynamic values if status is idle, offline or error
            if new_status in ["idle", "offline", "error"]:
                CAMERA_STATUS.update({
                    "srt_destination": None,
                    "width": None,
                    "height": None,
                    "fps": None,
                    "bitrate": None,
                    "error": None
                })

            # Update status dictionary with new fields
            for k in CAMERA_STATUS.keys():
                if k in payload:
                    CAMERA_STATUS[k] = payload[k]

            # Log events on state transitions
            if old_status == "offline" and new_status in ["idle", "streaming"]:
                log_event("DEVICE_ONLINE", f"Pi agent online (Status: {new_status})")
            elif old_status != "offline" and new_status == "offline":
                log_event("DEVICE_OFFLINE", "Pi agent disconnected")
            elif old_status == "idle" and new_status == "streaming":
                dest = payload.get("srt_destination", "")
                log_event("STREAM_STARTED", f"Streaming started to {dest}")
            elif old_status == "streaming" and new_status == "idle":
                log_event("STREAM_STOPPED", "Streaming stopped")
            elif new_status == "error":
                err_msg = payload.get("error", "Unknown error")
                log_event("STREAM_ERROR", f"Pi agent error: {err_msg}")

        except Exception as e:
            logger.error(f"Failed to parse status message: {e}")

def start_mqtt_client():
    """Starts the MQTT client loop in the background."""
    global client
    host, port, username, password = load_mqtt_config()

    try:
        # Use Paho V2 Client configuration
        client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_message = on_message

        if username:
            client.username_pw_set(username, password)

        logger.info(f"Connecting to MQTT broker at {host}:{port}...")
        client.connect(host, int(port), keepalive=60)
        client.loop_start()  # Runs client loop in background thread
    except Exception as e:
        logger.error(f"Failed to start MQTT client: {e}")

def stop_mqtt_client():
    """Disconnects and stops the MQTT client loop."""
    global client
    if client:
        logger.info("Stopping MQTT client...")
        try:
            client.loop_stop()
            client.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting MQTT client: {e}")
        client = None

def send_camera_command(action: str, params: dict = None):
    """Sends start/stop commands to the Pi agent."""
    global client
    if not client:
        logger.error("MQTT client is not running")
        return False

    payload = {"action": action}
    if params:
        payload.update(params)

    # Log the command request
    if action == "start":
        srt_host = payload.get("srt_host", "")
        srt_port = payload.get("srt_port", "")
        log_event("STREAM_START_REQUESTED", f"Requested stream to srt://{srt_host}:{srt_port}")
    elif action == "stop":
        log_event("STREAM_STOP_REQUESTED", "Requested stream stop")

    try:
        client.publish("camera/control", json.dumps(payload), qos=1)
        logger.info(f"Published control command: {action}")
        return True
    except Exception as e:
        logger.error(f"Failed to publish camera command: {e}")
        return False

def get_camera_status():
    """Returns the current camera state."""
    global CAMERA_STATUS
    return CAMERA_STATUS
