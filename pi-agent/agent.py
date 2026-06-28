import os
import sys
import json
import time
import yaml
import logging
import subprocess
import threading
import paho.mqtt.client as mqtt

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("pi_camera_agent")

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.yaml")

# Global state variables
client = None
stream_process = None
stream_details = {}
config = {}
process_lock = threading.Lock()

def load_config():
    global config
    try:
        with open(CONFIG_PATH, "r") as f:
            config = yaml.safe_load(f)
            logger.info("Configuration loaded successfully")
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        # Default fallback config
        config = {
            "mqtt": {
                "host": "localhost",
                "port": 1883,
                "keepalive": 60,
                "client_id": "pi_camera_agent"
            },
            "camera": {
                "device": "/dev/video0",
                "width": 1280,
                "height": 720,
                "fps": 30,
                "bitrate": "1500k",
                "use_hw_acceleration": True
            }
        }

def get_cpu_temp():
    """Reads the Raspberry Pi CPU temperature if available."""
    try:
        if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_raw = int(f.read().strip())
                return round(temp_raw / 1000.0, 1)
    except Exception as e:
        logger.debug(f"Could not read CPU temperature: {e}")
    return None

def publish_status(status_str, error_msg=None):
    """Publishes current status to the camera/status topic."""
    global stream_details
    payload = {
        "status": status_str,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cpu_temp": get_cpu_temp()
    }
    
    if status_str == "streaming" and stream_details:
        payload.update(stream_details)
    elif status_str == "error" and error_msg:
        payload["error"] = error_msg
        
    try:
        client.publish("camera/status", json.dumps(payload), qos=1, retain=True)
        logger.info(f"Published status: {status_str}")
    except Exception as e:
        logger.error(f"Failed to publish status: {e}")

def stop_stream():
    """Kills the active streaming subprocess."""
    global stream_process, stream_details
    with process_lock:
        if stream_process:
            logger.info("Stopping stream process...")
            try:
                stream_process.terminate()
                stream_process.wait(timeout=5)
                logger.info("Stream process terminated gracefully")
            except subprocess.TimeoutExpired:
                logger.warning("Stream process timed out, killing forcefully...")
                stream_process.kill()
                stream_process.wait()
            except Exception as e:
                logger.error(f"Error terminating stream process: {e}")
            finally:
                stream_process = None
                stream_details = {}
        else:
            logger.info("No active stream process to stop")

def start_stream(cmd_args):
    """Starts the FFmpeg streaming process with configured arguments."""
    global stream_process, stream_details
    stop_stream()  # Ensure any existing stream is cleaned up first
    
    with process_lock:
        srt_host = cmd_args.get("srt_host")
        srt_port = cmd_args.get("srt_port")
        
        if not srt_host or not srt_port:
            publish_status("error", "Missing srt_host or srt_port parameters")
            return
            
        width = cmd_args.get("width", config["camera"].get("width", 1280))
        height = cmd_args.get("height", config["camera"].get("height", 720))
        fps = cmd_args.get("fps", config["camera"].get("fps", 30))
        bitrate = cmd_args.get("bitrate", config["camera"].get("bitrate", "1500k"))
        device = config["camera"].get("device", "/dev/video0")
        use_hw = config["camera"].get("use_hw_acceleration", True)
        
        logger.info(f"Preparing stream to srt://{srt_host}:{srt_port}")
        
        # Build FFmpeg command based on OS and HW acceleration choice
        if sys.platform == 'win32':
            # Windows testing (DirectShow)
            # Users can configure camera device name in config (e.g., 'Integrated Camera')
            cmd = [
                "ffmpeg",
                "-f", "dshow",
                "-i", f"video={device}",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-tune", "zerolatency",
                "-b:v", bitrate,
                "-f", "mpegts",
                f"srt://{srt_host}:{srt_port}?mode=caller"
            ]
        elif sys.platform == 'darwin':
            # macOS testing (AVFoundation)
            cmd = [
                "ffmpeg",
                "-f", "avfoundation",
                "-framerate", str(fps),
                "-i", f"{device}:none",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-tune", "zerolatency",
                "-b:v", bitrate,
                "-f", "mpegts",
                f"srt://{srt_host}:{srt_port}?mode=caller"
            ]
        else:
            # Linux / Raspberry Pi
            if use_hw:
                # V4L2 Hardware H264 Encoder (default on Pi)
                cmd = [
                    "ffmpeg",
                    "-f", "v4l2",
                    "-input_format", "mjpeg",
                    "-video_size", f"{width}x{height}",
                    "-framerate", str(fps),
                    "-i", device,
                    "-c:v", "h264_v4l2m2m",
                    "-b:v", bitrate,
                    "-f", "mpegts",
                    f"srt://{srt_host}:{srt_port}?mode=caller"
                ]
            else:
                # Software encoder (libx264)
                cmd = [
                    "ffmpeg",
                    "-f", "v4l2",
                    "-input_format", "mjpeg",
                    "-video_size", f"{width}x{height}",
                    "-framerate", str(fps),
                    "-i", device,
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-tune", "zerolatency",
                    "-b:v", bitrate,
                    "-f", "mpegts",
                    f"srt://{srt_host}:{srt_port}?mode=caller"
                ]
        
        logger.info(f"Running command: {' '.join(cmd)}")
        
        try:
            # Run FFmpeg in the background, logging errors to stderr
            stream_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Allow a moment to see if it exits immediately
            time.sleep(1)
            poll = stream_process.poll()
            if poll is not None:
                # Process exited immediately
                _, stderr = stream_process.communicate()
                error_msg = f"FFmpeg failed to start (exit code {poll}). Stderr: {stderr[-150:].strip()}"
                logger.error(error_msg)
                publish_status("error", error_msg)
                stream_process = None
            else:
                # Success!
                stream_details = {
                    "srt_destination": f"srt://{srt_host}:{srt_port}",
                    "width": width,
                    "height": height,
                    "fps": fps,
                    "bitrate": bitrate,
                    "device": device
                }
                publish_status("streaming")
                
                # Start stderr reader thread to log output at debug level
                threading.Thread(target=read_stderr, args=(stream_process,), daemon=True).start()
                
        except Exception as e:
            logger.error(f"Failed to spawn FFmpeg process: {e}")
            publish_status("error", str(e))

def read_stderr(process):
    """Helper thread to read and log stderr from the FFmpeg process."""
    while True:
        if process.poll() is not None:
            break
        line = process.stderr.readline()
        if not line:
            break
        logger.debug(f"FFmpeg: {line.strip()}")
    
    # If process exited unexpectedly
    exit_code = process.poll()
    if exit_code is not None and exit_code != 0:
        logger.warning(f"FFmpeg process exited with non-zero exit code: {exit_code}")
        # Only notify error if we still think we are supposed to be streaming
        with process_lock:
            global stream_process
            if stream_process == process:
                stream_process = None
                publish_status("error", f"Stream process crashed (exit code {exit_code})")

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        logger.info("Connected successfully to MQTT Broker")
        # Subscribe to control topic
        client.subscribe("camera/control", qos=1)
        
        # Publish initial status (online and idle)
        with process_lock:
            if stream_process and stream_process.poll() is None:
                publish_status("streaming")
            else:
                publish_status("idle")
    else:
        logger.error(f"Failed to connect, return code: {rc}")

def on_message(client, userdata, msg):
    logger.info(f"Received message on {msg.topic}")
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        action = payload.get("action")
        
        if action == "start":
            start_stream(payload)
        elif action == "stop":
            stop_stream()
            publish_status("idle")
        else:
            logger.warning(f"Unknown action received: {action}")
    except Exception as e:
        logger.error(f"Error parsing control message: {e}")

def status_heartbeat_loop():
    """Periodic loop to report temperature and verify process health."""
    while True:
        time.sleep(10)
        try:
            with process_lock:
                if stream_process:
                    poll = stream_process.poll()
                    if poll is None:
                        publish_status("streaming")
                    else:
                        publish_status("error", f"FFmpeg exited with code {poll}")
                else:
                    publish_status("idle")
        except Exception as e:
            logger.error(f"Error in heartbeat loop: {e}")

def main():
    global client
    load_config()
    
    # Setup MQTT Client
    mqtt_cfg = config.get("mqtt", {})
    client_id = mqtt_cfg.get("client_id", "pi_camera_agent")
    
    client = mqtt.Client(client_id=client_id)
    client.on_connect = on_connect
    client.on_message = on_message
    
    # Configure Last Will and Testament (LWT)
    # If broker detects connection loss, it will publish {"status": "offline"} on camera/status
    lwt_payload = {
        "status": "offline",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    client.will_set("camera/status", json.dumps(lwt_payload), qos=1, retain=True)
    
    # Set credentials if specified
    if mqtt_cfg.get("username"):
        client.username_pw_set(mqtt_cfg["username"], mqtt_cfg.get("password"))
        
    logger.info(f"Connecting to MQTT broker at {mqtt_cfg.get('host')}:{mqtt_cfg.get('port', 1883)}")
    
    try:
        client.connect(
            mqtt_cfg.get("host", "localhost"),
            mqtt_cfg.get("port", 1883),
            mqtt_cfg.get("keepalive", 60)
        )
    except Exception as e:
        logger.critical(f"Could not connect to MQTT broker: {e}")
        sys.exit(1)
        
    # Start heartbeat thread
    threading.Thread(target=status_heartbeat_loop, daemon=True).start()
    
    # Run the client loop (reconnects automatically)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        logger.info("Agent shutting down...")
        stop_stream()
        publish_status("offline")
        client.disconnect()

if __name__ == "__main__":
    main()
