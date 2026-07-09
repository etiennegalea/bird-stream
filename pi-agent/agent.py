#!/usr/bin/env python3
"""Birdstream Pi agent.

Captures the camera with FFmpeg (timestamp overlay burned in on-device) and
pushes SRT to MediaMTX on the server. Controlled over MQTT v5 with per-device
topics so one broker can manage many Pis:

    camera/<pi_id>/control   (subscribe)  start | stop | set_camera | set_controls
                                          get_config | get_controls | update | reboot
    camera/<pi_id>/status    (publish, retained)  idle | streaming | error | offline
    camera/<pi_id>/reply     (publish)    responses to get_* / update actions
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque

import yaml
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("pi_camera_agent")

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(AGENT_DIR, "config.yaml")

DEFAULT_CONFIG = {
    "device": {"id": "pi-01"},
    "mqtt": {
        "host": "localhost",
        "port": 1883,
        "keepalive": 60,
        "username": None,
        "password": None,
        "tls": {"enabled": False, "ca_cert": None},
    },
    "camera": {
        "device": "/dev/video0",
        "width": 1280,
        "height": 720,
        "fps": 30,
        "bitrate": "1500k",
        "use_hw_acceleration": False,
    },
    "audio": {
        "enabled": False,       # capture mic audio (e.g. webcam mic via ALSA)
        "device": "default",    # ALSA device; list with: arecord -l
        "bitrate": "64k",
        "channels": 1,
    },
    "overlay": {
        "enabled": True,
        "time_format": "%Y-%m-%d %H:%M:%S",
        "fontfile": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "fontsize": 24,
    },
    "stream": {
        "auto_start": True,
        "srt": {"host": None, "port": 8890, "path": "birdcam",
                "username": None, "password": None},
    },
}

# Camera keys settable via the set_camera action
CAMERA_KEYS = {"device", "width", "height", "fps", "bitrate", "use_hw_acceleration"}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def get_cpu_temp():
    try:
        path = "/sys/class/thermal/thermal_zone0/temp"
        if os.path.exists(path):
            with open(path) as f:
                return round(int(f.read().strip()) / 1000.0, 1)
    except Exception as e:
        logger.debug(f"Could not read CPU temperature: {e}")
    return None


class CameraAgent:
    def __init__(self):
        self.config = self._load_config()
        self.pi_id = self.config["device"]["id"]
        base = f"camera/{self.pi_id}"
        self.topic_control = f"{base}/control"
        self.topic_status = f"{base}/status"
        self.topic_reply = f"{base}/reply"

        self.client = None
        self.stream_process = None
        self.stream_details = {}
        self.lock = threading.Lock()

    # ── config ────────────────────────────────────────────────────────────

    def _load_config(self) -> dict:
        try:
            with open(CONFIG_PATH) as f:
                cfg = deep_merge(DEFAULT_CONFIG, yaml.safe_load(f) or {})
                logger.info("Configuration loaded")
                return cfg
        except FileNotFoundError:
            logger.warning("config.yaml not found, using defaults")
            return dict(DEFAULT_CONFIG)
        except Exception as e:
            logger.error(f"Failed to load config: {e}, using defaults")
            return dict(DEFAULT_CONFIG)

    def _save_config(self):
        with open(CONFIG_PATH, "w") as f:
            yaml.safe_dump(self.config, f, default_flow_style=False, sort_keys=False)
        logger.info("Configuration persisted to config.yaml")

    # ── MQTT publishing ───────────────────────────────────────────────────

    def publish_status(self, status: str, error_msg: str = None):
        payload = {
            "status": status,
            "pi_id": self.pi_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "cpu_temp": get_cpu_temp(),
        }
        if status == "streaming" and self.stream_details:
            payload.update(self.stream_details)
        if status == "error" and error_msg:
            payload["error"] = error_msg
        try:
            self.client.publish(self.topic_status, json.dumps(payload),
                                qos=1, retain=True)
            logger.info(f"Published status: {status}")
        except Exception as e:
            logger.error(f"Failed to publish status: {e}")

    def publish_reply(self, action: str, data: dict, request_id=None):
        payload = {"action": action, "pi_id": self.pi_id,
                   "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"), **data}
        if request_id is not None:
            payload["request_id"] = request_id
        try:
            self.client.publish(self.topic_reply, json.dumps(payload), qos=1)
        except Exception as e:
            logger.error(f"Failed to publish reply: {e}")

    # ── FFmpeg pipeline ───────────────────────────────────────────────────

    def _drawtext_filter(self):
        ov = self.config.get("overlay", {})
        if not ov.get("enabled", True):
            return None
        font = ov.get("fontfile", DEFAULT_CONFIG["overlay"]["fontfile"])
        size = ov.get("fontsize", 24)
        fmt = ov.get("time_format", "%Y-%m-%d %H:%M:%S")
        if fmt == "%Y-%m-%d %H:%M:%S":
            # No-arg %{localtime} defaults to exactly this format and avoids
            # colon-escaping entirely (escaping rules vary across ffmpeg
            # versions; the Pi ships 5.x).
            text = "%{localtime}"
        else:
            # Custom format: colons need three backslashes — one level eaten
            # by the filtergraph parser, one by drawtext's argument splitter.
            text = f"%{{localtime\\:{fmt.replace(':', chr(92) * 3 + ':')}}}"
        return (
            f"drawtext=fontfile={font}:text='{text}'"
            f":x=10:y=h-th-10:fontsize={size}:fontcolor=white"
            f":box=1:boxcolor=black@0.4"
        )

    def _srt_url(self, host: str, port: int) -> str:
        srt = self.config["stream"]["srt"]
        path = srt.get("path", "birdcam")
        user, pw = srt.get("username"), srt.get("password")
        streamid = f"publish:{path}"
        if user and pw:
            streamid += f":{user}:{pw}"
        return f"srt://{host}:{port}?mode=caller&streamid={streamid}"

    def _build_ffmpeg_cmd(self, host, port, width, height, fps, bitrate,
                          device, use_hw):
        vf = self._drawtext_filter()
        url = self._srt_url(host, port)
        audio = self.config.get("audio") or {}
        audio_on = bool(audio.get("enabled", False))

        if sys.platform == "darwin":  # macOS testing
            avf_input = f"{device}:{audio.get('device', '0')}" if audio_on \
                else f"{device}:none"
            cmd = ["ffmpeg", "-f", "avfoundation", "-framerate", str(fps),
                   "-i", avf_input,
                   "-c:v", "libx264", "-preset", "ultrafast",
                   "-tune", "zerolatency"]
        else:  # Linux / Raspberry Pi
            cmd = ["ffmpeg", "-f", "v4l2", "-input_format", "mjpeg",
                   "-video_size", f"{width}x{height}", "-framerate", str(fps),
                   "-i", device]
            if audio_on:
                # Second input: ALSA mic (webcam mic). List devices: arecord -l
                cmd += ["-f", "alsa",
                        "-channels", str(audio.get("channels", 1)),
                        "-i", audio.get("device", "default")]
            if use_hw:
                cmd += ["-c:v", "h264_v4l2m2m"]
            else:
                cmd += ["-c:v", "libx264", "-preset", "ultrafast",
                        "-tune", "zerolatency"]

        if vf:
            cmd += ["-vf", vf]
        # Force 4:2:0: MJPEG cams deliver yuvj422p and browsers can't decode
        # H264 4:2:2 profiles (also breaks the Pi's v4l2m2m HW encoder).
        cmd += ["-pix_fmt", "yuv420p",
                "-b:v", bitrate, "-g", str(int(fps) * 2)]
        if audio_on:
            # Opus @48k: the codec WebRTC/WHEP requires — passes through
            # MediaMTX untouched (mpegts carries opus fine).
            cmd += ["-c:a", "libopus",
                    "-b:a", audio.get("bitrate", "64k"),
                    "-ar", "48000",
                    "-ac", str(audio.get("channels", 1)),
                    "-application", "audio"]
        cmd += ["-f", "mpegts", url]
        return cmd

    def start_stream(self, params: dict):
        self.stop_stream()
        with self.lock:
            cam = self.config["camera"]
            srt = self.config["stream"]["srt"]
            host = params.get("srt_host") or srt.get("host")
            port = params.get("srt_port") or srt.get("port", 8890)
            if not host:
                self.publish_status(
                    "error",
                    "No SRT host (param srt_host or config stream.srt.host)")
                return

            width = params.get("width", cam["width"])
            height = params.get("height", cam["height"])
            fps = params.get("fps", cam["fps"])
            bitrate = params.get("bitrate", cam["bitrate"])
            device = params.get("device", cam["device"])
            use_hw = cam.get("use_hw_acceleration", True)

            cmd = self._build_ffmpeg_cmd(host, port, width, height, fps,
                                         bitrate, device, use_hw)
            logger.info(f"Running: {' '.join(cmd)}")
            try:
                self.stream_process = subprocess.Popen(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                time.sleep(1)
                poll = self.stream_process.poll()
                if poll is not None:
                    _, stderr = self.stream_process.communicate()
                    msg = f"FFmpeg failed to start (exit {poll}): {stderr[-200:].strip()}"
                    logger.error(msg)
                    self.publish_status("error", msg)
                    self.stream_process = None
                    return
                self.stream_details = {
                    "srt_destination": f"srt://{host}:{port}",
                    "path": srt.get("path", "birdcam"),
                    "width": width, "height": height, "fps": fps,
                    "bitrate": bitrate, "device": device,
                    "audio": bool((self.config.get("audio") or {}).get("enabled")),
                }
                self.publish_status("streaming")
                threading.Thread(target=self._read_stderr,
                                 args=(self.stream_process,), daemon=True).start()
            except Exception as e:
                logger.error(f"Failed to spawn FFmpeg: {e}")
                self.publish_status("error", str(e))

    def stop_stream(self):
        with self.lock:
            if not self.stream_process:
                return
            logger.info("Stopping stream process...")
            try:
                self.stream_process.terminate()
                self.stream_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.stream_process.kill()
                self.stream_process.wait()
            except Exception as e:
                logger.error(f"Error terminating stream: {e}")
            finally:
                self.stream_process = None
                self.stream_details = {}

    def _read_stderr(self, process):
        tail = deque(maxlen=15)  # keep the last lines for crash reporting
        while process.poll() is None:
            line = process.stderr.readline()
            if not line:
                break
            tail.append(line.strip())
            logger.debug(f"FFmpeg: {line.strip()}")
        exit_code = process.poll()
        if exit_code:
            stderr_tail = " | ".join(tail)[-400:]
            logger.error(f"FFmpeg crashed (exit {exit_code}): {stderr_tail}")
            with self.lock:
                if self.stream_process == process:
                    self.stream_process = None
                    self.stream_details = {}
                    self.publish_status(
                        "error",
                        f"Stream crashed (exit {exit_code}): {stderr_tail}")

    def _is_streaming(self) -> bool:
        return self.stream_process is not None and self.stream_process.poll() is None

    # ── control actions ───────────────────────────────────────────────────

    def action_set_camera(self, payload):
        changes = {k: v for k, v in payload.get("params", payload).items()
                   if k in CAMERA_KEYS}
        if not changes:
            self.publish_reply(
                "set_camera",
                {"ok": False,
                 "error": f"No valid keys; allowed: {sorted(CAMERA_KEYS)}"},
                payload.get("request_id"))
            return
        self.config["camera"].update(changes)
        self._save_config()
        restarted = False
        if self._is_streaming():
            self.start_stream({})
            restarted = True
        self.publish_reply(
            "set_camera",
            {"ok": True, "applied": changes, "restarted": restarted},
            payload.get("request_id"))

    def action_set_controls(self, payload):
        """Set V4L2 controls (brightness, contrast, exposure, focus, ...)."""
        controls = payload.get("controls", {})
        device = self.config["camera"]["device"]
        if not shutil.which("v4l2-ctl"):
            self.publish_reply(
                "set_controls",
                {"ok": False,
                 "error": "v4l2-ctl not installed (apt install v4l-utils)"},
                payload.get("request_id"))
            return
        results = {}
        for name, value in controls.items():
            r = subprocess.run(
                ["v4l2-ctl", "-d", device, "-c", f"{name}={value}"],
                capture_output=True, text=True)
            results[name] = "ok" if r.returncode == 0 else r.stderr.strip()
        self.publish_reply("set_controls", {"ok": True, "results": results},
                           payload.get("request_id"))

    def action_get_controls(self, payload):
        device = self.config["camera"]["device"]
        if not shutil.which("v4l2-ctl"):
            self.publish_reply("get_controls",
                               {"ok": False, "error": "v4l2-ctl not installed"},
                               payload.get("request_id"))
            return
        r = subprocess.run(["v4l2-ctl", "-d", device, "-l"],
                           capture_output=True, text=True)
        self.publish_reply("get_controls",
                           {"ok": r.returncode == 0, "controls": r.stdout},
                           payload.get("request_id"))

    def action_get_config(self, payload):
        cfg = json.loads(json.dumps(self.config))  # deep copy
        if cfg.get("mqtt", {}).get("password"):
            cfg["mqtt"]["password"] = "***"
        if cfg.get("stream", {}).get("srt", {}).get("password"):
            cfg["stream"]["srt"]["password"] = "***"
        self.publish_reply("get_config", {"ok": True, "config": cfg},
                           payload.get("request_id"))

    def action_update(self, payload):
        """git pull, reinstall deps, exit — systemd restarts the agent."""
        parent = os.path.dirname(AGENT_DIR)
        repo_dir = parent if os.path.isdir(os.path.join(parent, ".git")) else AGENT_DIR
        r = subprocess.run(["git", "-C", repo_dir, "pull", "--ff-only"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            self.publish_reply("update",
                               {"ok": False, "error": r.stderr.strip()},
                               payload.get("request_id"))
            return
        uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
        py = os.path.join(AGENT_DIR, ".venv", "bin", "python")
        if os.path.exists(uv) and os.path.exists(py):
            subprocess.run([uv, "pip", "install", "-q", "--python", py, "-r",
                            os.path.join(AGENT_DIR, "requirements.txt")],
                           capture_output=True)
        else:
            logger.warning("uv or venv not found, skipping dependency sync")
        self.publish_reply("update",
                           {"ok": True, "output": r.stdout.strip(),
                            "restarting": True},
                           payload.get("request_id"))
        logger.info("Update complete, exiting for systemd restart...")
        self.stop_stream()
        self.publish_status("offline")
        threading.Timer(1.0, lambda: os._exit(0)).start()

    def action_reboot(self, payload):
        self.publish_reply("reboot", {"ok": True}, payload.get("request_id"))
        self.stop_stream()
        self.publish_status("offline")
        r = subprocess.run(["sudo", "-n", "reboot"], capture_output=True, text=True)
        if r.returncode != 0:
            self.publish_status(
                "error",
                f"Reboot failed: {r.stderr.strip()} "
                "(re-run install.sh --allow-reboot to add the sudoers rule)")

    # ── MQTT callbacks (paho 2.x, VERSION2 signatures) ───────────────────

    def on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code == 0:
            logger.info("Connected to MQTT broker")
            client.subscribe(self.topic_control, qos=1)
            self.publish_status("streaming" if self._is_streaming() else "idle")
        else:
            logger.error(f"MQTT connect failed: {reason_code}")

    def on_message(self, client, userdata, msg):
        logger.info(f"Message on {msg.topic}")
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception as e:
            logger.error(f"Bad control payload: {e}")
            return
        action = payload.get("action")
        handlers = {
            "start": lambda: self.start_stream(payload),
            "stop": lambda: (self.stop_stream(), self.publish_status("idle")),
            "set_camera": lambda: self.action_set_camera(payload),
            "set_controls": lambda: self.action_set_controls(payload),
            "get_controls": lambda: self.action_get_controls(payload),
            "get_config": lambda: self.action_get_config(payload),
            "update": lambda: self.action_update(payload),
            "reboot": lambda: self.action_reboot(payload),
        }
        handler = handlers.get(action)
        if handler:
            try:
                handler()
            except Exception as e:
                logger.exception(f"Action '{action}' failed")
                self.publish_reply(action, {"ok": False, "error": str(e)},
                                   payload.get("request_id"))
        else:
            logger.warning(f"Unknown action: {action}")

    # ── main loop ─────────────────────────────────────────────────────────

    def _heartbeat(self):
        while True:
            time.sleep(10)
            try:
                if self._is_streaming():
                    self.publish_status("streaming")
                elif self.stream_process:  # exists but died
                    code = self.stream_process.poll()
                    self.stream_process = None
                    self.publish_status("error",
                                        f"FFmpeg exited with code {code}")
                else:
                    self.publish_status("idle")
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    def run(self):
        m = self.config["mqtt"]
        self.client = mqtt.Client(
            callback_api_version=CallbackAPIVersion.VERSION2,
            client_id=f"pi_camera_agent_{self.pi_id}",
            protocol=mqtt.MQTTv5,
        )
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message

        lwt = json.dumps({"status": "offline", "pi_id": self.pi_id,
                          "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")})
        self.client.will_set(self.topic_status, lwt, qos=1, retain=True)

        if m.get("username"):
            self.client.username_pw_set(m["username"], m.get("password"))
        tls = m.get("tls") or {}
        if tls.get("enabled"):
            self.client.tls_set(ca_certs=tls.get("ca_cert"))

        logger.info(f"[{self.pi_id}] Connecting to {m['host']}:{m.get('port', 1883)}")
        try:
            self.client.connect(m["host"], m.get("port", 1883),
                                m.get("keepalive", 60))
        except Exception as e:
            logger.critical(f"Could not connect to MQTT broker: {e}")
            sys.exit(1)

        threading.Thread(target=self._heartbeat, daemon=True).start()

        if self.config["stream"].get("auto_start") and \
                self.config["stream"]["srt"].get("host"):
            logger.info("auto_start enabled, starting stream")
            self.start_stream({})

        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.stop_stream()
            self.publish_status("offline")
            self.client.disconnect()


if __name__ == "__main__":
    CameraAgent().run()
