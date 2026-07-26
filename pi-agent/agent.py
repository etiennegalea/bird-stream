#!/usr/bin/env python3
"""Birdstream Pi agent.

Auto-detects V4L2 cameras, captures each enabled camera with its own FFmpeg
process (timestamp overlay burned in on-device), and pushes independent SRT
streams to MediaMTX. Controlled over MQTT v5 with per-device topics:

    camera/<pi_id>/control   (subscribe)  start | stop | set_camera | set_controls
                                          get_config | get_controls | update | reboot
    camera/<pi_id>/status    (publish, retained)  aggregate + streams[] details
    camera/<pi_id>/reply     (publish)    responses to get_* / update actions
"""

import datetime
import glob
import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from collections import deque
from logging.handlers import RotatingFileHandler

import yaml
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

AGENT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(AGENT_DIR, "config.yaml")
# Persist logs (esp. stream errors) to disk so failures can be inspected after
# the fact — journald isn't always available/retained on a headless Pi.
LOG_PATH = os.environ.get("BIRDSTREAM_LOG", os.path.join(AGENT_DIR, "agent.log"))

_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
_handlers = [logging.StreamHandler()]


class _AgentFileFilter(logging.Filter):
    """Keep the persistent log terse, except for the streaming audit entry."""

    def filter(self, record):
        return (
            record.levelno >= logging.WARNING
            or getattr(record, "store_in_agent_log", False)
        )


try:
    _file_handler = RotatingFileHandler(
        LOG_PATH, maxBytes=2_000_000, backupCount=5)
    _file_handler.addFilter(_AgentFileFilter())
    _handlers.append(_file_handler)
except OSError as _e:  # read-only fs / permissions — fall back to console only
    print(f"Could not open log file {LOG_PATH}: {_e}", file=sys.stderr)

logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT, handlers=_handlers)
logger = logging.getLogger("pi_camera_agent")

# ── Stream auto-recovery ──────────────────────────────────────────────────
# Each failed FFmpeg child is restarted independently. After MAX consecutive
# failures that camera is left in an error state without disrupting healthy
# cameras; an operator can retry it from the admin panel.
STREAM_RESTART_DELAY = 5     # seconds to wait before an auto-restart attempt
STREAM_MAX_RESTARTS = 5      # consecutive failures before exiting for systemd
V4L2_CAP_VIDEO_CAPTURE = 0x00000001
V4L2_CAP_VIDEO_CAPTURE_MPLANE = 0x00001000
V4L2_CAPABILITY_CACHE_SECONDS = 60

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
        # Every detected V4L2 capture device is streamed independently.
        # `devices` can override the generated id/label/enabled state for a
        # stable /dev/v4l/by-id path. Existing single-camera configs continue
        # to work through `device`.
        "auto_detect": True,
        "enabled_by_default": True,
        "primary_id": None,
        "devices": [],
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
    "schedule": {
        # The device only broadcasts inside its daily window and rests (idle,
        # ffmpeg stopped → cools down) the rest of the day. ON by default, in
        # "sun" mode: it wakes at sunrise and sleeps at sunset.
        #   mode "sun"   → sunrise..sunset for the device's location
        #                  (auto-detected via IP; override with lat/long below)
        #   mode "fixed" → the start/end clock times (Pi LOCAL time, HH:MM;
        #                  start > end wraps past midnight, e.g. 22:00–06:00)
        # start/end also serve as the fallback window if sun times can't be
        # computed (no location / polar day/night).
        "enabled": True,
        "mode": "sun",
        "start": "06:00",
        "end": "20:00",
        "latitude": None,
        "longitude": None,
    },
}

# Camera keys settable via the set_camera action
CAMERA_KEYS = {
    "device", "width", "height", "fps", "bitrate", "use_hw_acceleration",
}
CAMERA_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# How often the scheduler re-checks whether the current local time is inside
# the broadcast window.
SCHEDULE_CHECK_SECONDS = 30


def _parse_hhmm(value) -> int | None:
    """Parse 'HH:MM' into minutes-since-midnight, or None if malformed."""
    try:
        hh, mm = str(value).strip().split(":")
        h, m = int(hh), int(mm)
    except (ValueError, AttributeError):
        return None
    if 0 <= h <= 23 and 0 <= m <= 59:
        return h * 60 + m
    return None


def _fmt_hhmm(minutes: int) -> str:
    minutes %= 1440
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


# ── Sunrise/sunset (NOAA algorithm, pure stdlib — no extra deps) ───────────
# Returns local minutes-since-midnight for a given date/location, or None when
# the sun doesn't cross the horizon that day (polar day/night).

def _sun_event(lat, lon, year, month, day, rising, tz_offset_hours,
               zenith=90.833) -> int | None:
    N = datetime.date(year, month, day).timetuple().tm_yday
    lng_hour = lon / 15.0
    t = N + (((6 if rising else 18) - lng_hour) / 24.0)
    M = (0.9856 * t) - 3.289
    L = M + (1.916 * math.sin(math.radians(M))) \
        + (0.020 * math.sin(math.radians(2 * M))) + 282.634
    L %= 360
    RA = math.degrees(math.atan(0.91764 * math.tan(math.radians(L)))) % 360
    # Put RA in the same quadrant as L, then convert to hours.
    RA += (math.floor(L / 90) * 90) - (math.floor(RA / 90) * 90)
    RA /= 15.0
    sin_dec = 0.39782 * math.sin(math.radians(L))
    cos_dec = math.cos(math.asin(sin_dec))
    cos_h = (math.cos(math.radians(zenith)) - (sin_dec * math.sin(math.radians(lat)))) \
        / (cos_dec * math.cos(math.radians(lat)))
    if cos_h > 1 or cos_h < -1:
        return None  # sun never rises / never sets on this day
    H = (360 - math.degrees(math.acos(cos_h))) if rising \
        else math.degrees(math.acos(cos_h))
    H /= 15.0
    T = H + RA - (0.06571 * t) - 6.622
    UT = (T - lng_hour) % 24
    local = (UT + tz_offset_hours) % 24
    return int(round(local * 60)) % 1440


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def redact_command_secrets(command: list[str]) -> str:
    """Render a process command without exposing SRT stream credentials."""
    safe = []
    marker = "streamid=publish:"
    for argument in command:
        if isinstance(argument, str) and argument.startswith("srt://") \
                and marker in argument:
            prefix, stream_id = argument.split(marker, 1)
            fields = stream_id.split(":", 2)
            if len(fields) == 3:
                argument = f"{prefix}{marker}{':'.join(fields[:2])}:***"
        safe.append(argument)
    return " ".join(safe)


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
        # camera_id -> process/details/recovery state. One agent supervises
        # one independent FFmpeg/SRT publisher per detected camera.
        self.streams: dict[str, dict] = {}
        self._capture_devices: set[str] = set()
        self._logged_streaming_ids: set[tuple[str, str]] = set()
        self.lock = threading.Lock()

        # Auto-recovery state
        self.should_stream = False      # True while streaming is desired
        self.last_start_params = {}     # params to reuse on auto-restart

        # Cached IP-geolocation for the sunrise/sunset schedule
        self._geo = None                # (lat, lon), False (failed), or None
        self._geo_ts = 0.0

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

    # ── camera discovery ─────────────────────────────────────────────────

    @staticmethod
    def _camera_slug(value: str, fallback: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-_").lower()
        return slug or fallback

    def _is_capture_device(self, device: str) -> bool:
        """Accept only V4L2 nodes whose device capabilities include capture.

        Raspberry Pi media drivers expose codec, ISP and metadata nodes under
        the same /dev/video* namespace as webcams. Querying the current video
        format is not sufficient to distinguish all of them; VIDIOC_QUERYCAP
        (reported by ``v4l2-ctl --info``) is authoritative.
        """
        if not os.path.exists(device):
            return False
        real = os.path.realpath(device)
        now = time.monotonic()
        cache = getattr(self, "_capture_device_cache", {})
        cached = cache.get(real)
        if cached and cached["expires_at"] > now:
            return cached["is_capture"]

        ctl = shutil.which("v4l2-ctl")
        if not ctl:
            if not getattr(self, "_warned_missing_v4l2_ctl", False):
                logger.warning(
                    "v4l2-ctl is unavailable; automatic camera discovery "
                    "cannot safely distinguish capture and helper nodes")
                self._warned_missing_v4l2_ctl = True
            return False

        try:
            result = subprocess.run(
                [ctl, "-d", device, "--info"],
                capture_output=True, text=True, timeout=3,
                env={**os.environ, "LC_ALL": "C"},
            )
            output = f"{result.stdout}\n{result.stderr}"
            # When V4L2_CAP_DEVICE_CAPS is present, "Device Caps" describes
            # this specific node. The broader "Capabilities" block can include
            # capture support belonging to another node in the same device.
            match = re.search(
                r"(?mi)^\s*Device Caps\s*:\s*0x([0-9a-f]+)", output)
            if not match:
                match = re.search(
                    r"(?mi)^\s*Capabilities\s*:\s*0x([0-9a-f]+)", output)
            flags = int(match.group(1), 16) if match else 0
            is_capture = (
                result.returncode == 0
                and bool(flags & (
                    V4L2_CAP_VIDEO_CAPTURE
                    | V4L2_CAP_VIDEO_CAPTURE_MPLANE
                ))
            )
        except (OSError, subprocess.TimeoutExpired):
            is_capture = False

        cache[real] = {
            "is_capture": is_capture,
            "expires_at": now + V4L2_CAPABILITY_CACHE_SECONDS,
        }
        self._capture_device_cache = cache
        return is_capture

    def discover_cameras(self) -> list[dict]:
        """Return deterministic camera specs and MediaMTX paths.

        Stable `/dev/v4l/by-id/*-video-index0` links are preferred. Configured
        `camera.devices` entries override id, label and enabled state.
        """
        cam_cfg = self.config.get("camera") or {}
        configured = cam_cfg.get("devices") or []
        overrides_by_real = {}
        explicit = []
        for item in configured:
            if not isinstance(item, dict) or not item.get("device"):
                continue
            spec = dict(item)
            overrides_by_real[os.path.realpath(spec["device"])] = spec
            explicit.append(spec["device"])

        candidates = []
        if cam_cfg.get("auto_detect", True):
            candidates.extend(sorted(glob.glob("/dev/v4l/by-id/*-video-index0")))
            candidates.extend(sorted(
                glob.glob("/dev/video*"),
                key=lambda p: int(re.search(r"\d+$", p).group())
                if re.search(r"\d+$", p) else 9999,
            ))
        candidates.extend(explicit)
        # Backward-compatible single-camera fallback, including tests and
        # systems without /dev/v4l/by-id.
        if not candidates and cam_cfg.get("device"):
            candidates.append(cam_cfg["device"])

        unique = []
        seen_real = set()
        for candidate in candidates:
            real = os.path.realpath(candidate)
            if real in seen_real or not self._is_capture_device(candidate):
                continue
            seen_real.add(real)
            unique.append((candidate, real))

        base_path = (self.config.get("stream", {}).get("srt", {})
                     .get("path", "birdcam"))
        specs = []
        used_ids = set()
        primary_id = cam_cfg.get("primary_id")
        for index, (candidate, real) in enumerate(unique):
            override = overrides_by_real.get(real, {})
            detected_name = os.path.basename(candidate).removesuffix(
                "-video-index0")
            original = self._camera_slug(
                str(override.get("id") or detected_name),
                f"cam-{index + 1}",
            )[:32]
            camera_id = original
            suffix = 2
            while camera_id in used_ids:
                camera_id = f"{original}-{suffix}"
                suffix += 1
            used_ids.add(camera_id)
            is_primary = camera_id == primary_id or (
                primary_id is None and index == 0)
            path = base_path if is_primary else \
                f"{base_path}-{self.pi_id}-{camera_id}"
            specs.append({
                "id": camera_id,
                "label": override.get("label") or f"Camera {index + 1}",
                "device": override.get("device") or candidate,
                "real_device": real,
                "enabled": bool(override.get(
                    "enabled", cam_cfg.get("enabled_by_default", True))),
                "path": self._camera_slug(path, f"{base_path}-{index + 1}"),
                "index": index,
                **{k: override[k] for k in CAMERA_KEYS if k in override},
            })
        return specs

    def _ensure_primary_camera(self):
        """Persist the first detected camera as the legacy `birdcam` stream."""
        cam_cfg = self.config.get("camera") or {}
        if cam_cfg.get("primary_id"):
            return
        cameras = self.discover_cameras()
        if cameras:
            cam_cfg["primary_id"] = cameras[0]["id"]
            self._save_config()
            logger.info(
                "Registered %s as the primary camera", cameras[0]["id"])

    # ── MQTT publishing ───────────────────────────────────────────────────

    def publish_status(self, status: str | None = None, error_msg: str = None):
        stream_items = []
        for camera in self.discover_cameras():
            state = self.streams.get(camera["id"], {})
            process = state.get("process")
            running = process is not None and process.poll() is None
            camera_status = "streaming" if running else state.get("status", "idle")
            stream_items.append({
                "camera_id": camera["id"],
                "label": camera["label"],
                "device": camera["device"],
                "enabled": camera["enabled"],
                "status": camera_status,
                "path": camera["path"],
                **dict(state.get("details") or {}),
                **({"error": state["error"]} if state.get("error") else {}),
            })
        if status is None:
            if any(s["status"] == "streaming" for s in stream_items):
                status = "streaming"
            elif any(s["status"] == "error" for s in stream_items):
                status = "error"
            else:
                status = "idle"
        payload = {
            "status": status,
            "pi_id": self.pi_id,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "cpu_temp": get_cpu_temp(),
            "streams": stream_items,
        }
        # Preserve old top-level details for clients that only know one stream.
        live = next((s for s in stream_items if s["status"] == "streaming"), None)
        if live:
            payload.update({k: v for k, v in live.items()
                            if k not in {"status", "error", "enabled"}})
        if status == "error" and error_msg:
            payload["error"] = error_msg
        # Always advertise the schedule so the admin panel can render it, and
        # flag when the device is idle specifically because it's outside its
        # broadcast window (resting) rather than merely stopped.
        sched = self.config.get("schedule") or {}
        if sched.get("enabled"):
            info = {"enabled": True, "mode": sched.get("mode", "sun")}
            bounds = self._window_bounds()
            if bounds:
                # Report the *effective* window (today's sunrise/sunset in sun
                # mode) so the panel shows the real hours.
                info["start"], info["end"] = _fmt_hhmm(bounds[0]), _fmt_hhmm(bounds[1])
            else:
                info["start"], info["end"] = sched.get("start"), sched.get("end")
            payload["schedule"] = info
            payload["resting"] = status == "idle" and not self._in_window()
        else:
            payload["schedule"] = {"enabled": False,
                                   "mode": sched.get("mode", "sun")}
        try:
            self.client.publish(self.topic_status, json.dumps(payload),
                                qos=1, retain=True)
            if status == "streaming":
                logged_ids = getattr(self, "_logged_streaming_ids", set())
                for stream in stream_items:
                    if stream["status"] != "streaming":
                        continue
                    stream_id = stream["path"]
                    key = (self.pi_id, stream_id)
                    if key in logged_ids:
                        continue
                    logger.info(
                        "published status: streaming | stream_id=%s | device_id=%s",
                        stream_id,
                        self.pi_id,
                        extra={"store_in_agent_log": True},
                    )
                    logged_ids.add(key)
                self._logged_streaming_ids = logged_ids
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

    def _srt_url(self, host: str, port: int, path: str | None = None) -> str:
        srt = self.config["stream"]["srt"]
        path = path or srt.get("path", "birdcam")
        user, pw = srt.get("username"), srt.get("password")
        streamid = f"publish:{path}"
        if user and pw:
            streamid += f":{user}:{pw}"
        return f"srt://{host}:{port}?mode=caller&streamid={streamid}"

    def _build_ffmpeg_cmd(self, host, port, width, height, fps, bitrate,
                          device, use_hw, path=None, audio_enabled=None):
        vf = self._drawtext_filter()
        url = self._srt_url(host, port, path)
        audio = self.config.get("audio") or {}
        audio_on = bool(audio.get("enabled", False)) if audio_enabled is None \
            else bool(audio_enabled)

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
        """Start one camera (`camera_id`) or every enabled detected camera."""
        if params:
            self.last_start_params = params
        if not self._in_window():
            logger.info("Outside broadcast window — resting (stream not started)")
            self.stop_stream(manual=True)
            self.publish_status("idle")
            return
        self.should_stream = True
        requested_id = params.get("camera_id")
        cameras = self.discover_cameras()
        if requested_id:
            cameras = [c for c in cameras if c["id"] == requested_id]
            if not cameras:
                self.publish_reply("start", {
                    "ok": False, "error": f"Unknown camera: {requested_id}"})
                return
        for camera in cameras:
            if camera["enabled"]:
                if camera["id"] in self.streams:
                    self.streams[camera["id"]]["restart_attempts"] = 0
                self._start_camera(camera, params)
        self.publish_status()

    def _start_camera(self, camera: dict, params: dict):
        camera_id = camera["id"]
        state = self.streams.setdefault(camera_id, {
            "process": None, "details": {}, "status": "idle",
            "desired": True, "restart_attempts": 0, "restart_timer": None,
        })
        state["desired"] = True
        self._stop_camera(camera_id, clear_intent=False)

        cam = self.config["camera"]
        srt = self.config["stream"]["srt"]
        host = params.get("srt_host") or srt.get("host")
        port = params.get("srt_port") or srt.get("port", 8890)
        if not host:
            state.update(status="error", error="No SRT host")
            self.should_stream = False
            return
        width = params.get("width", camera.get("width", cam["width"]))
        height = params.get("height", camera.get("height", cam["height"]))
        fps = params.get("fps", camera.get("fps", cam["fps"]))
        bitrate = params.get("bitrate", camera.get("bitrate", cam["bitrate"]))
        use_hw = camera.get(
            "use_hw_acceleration", cam.get("use_hw_acceleration", False))
        # One ALSA device cannot generally be opened by multiple FFmpeg
        # processes. Keep audio on the primary camera stream only.
        primary_id = self.config["camera"].get("primary_id")
        is_primary = camera["id"] == primary_id or (
            primary_id is None and camera["index"] == 0)
        audio_enabled = is_primary and bool(
            (self.config.get("audio") or {}).get("enabled", False))
        cmd = self._build_ffmpeg_cmd(
            host, port, width, height, fps, bitrate, camera["device"], use_hw,
            path=camera["path"], audio_enabled=audio_enabled,
        )
        logger.info("[%s] Running: %s", camera_id,
                    redact_command_secrets(cmd))
        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
            )
            state["process"] = process
            time.sleep(1)
            poll = process.poll()
            if poll is not None:
                _, stderr = process.communicate()
                state["process"] = None
                self._schedule_restart(
                    camera_id,
                    f"FFmpeg failed to start (exit {poll}): "
                    f"{stderr[-200:].strip()}",
                )
                return
            state.update(
                status="streaming",
                error=None,
                restart_attempts=0,
                details={
                    "srt_destination": f"srt://{host}:{port}",
                    "width": width, "height": height, "fps": fps,
                    "bitrate": bitrate, "audio": audio_enabled,
                },
            )
            threading.Thread(
                target=self._read_stderr,
                args=(camera_id, process),
                daemon=True,
            ).start()
        except Exception as e:
            state["process"] = None
            self._schedule_restart(camera_id, f"Failed to spawn FFmpeg: {e}")

    def stop_stream(self, manual: bool = False, camera_id: str | None = None):
        if manual and camera_id is None:
            self.should_stream = False
        ids = [camera_id] if camera_id else list(self.streams)
        for current_id in ids:
            self._stop_camera(current_id, clear_intent=manual)

    def _stop_camera(self, camera_id: str, clear_intent: bool):
        state = self.streams.get(camera_id)
        if not state:
            return
        if clear_intent:
            state["desired"] = False
        timer = state.get("restart_timer")
        if timer:
            timer.cancel()
            state["restart_timer"] = None
        process = state.get("process")
        if process:
            logger.info("[%s] Stopping stream process", camera_id)
            try:
                process.terminate()
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            except Exception as e:
                logger.error("[%s] Error terminating stream: %s", camera_id, e)
        state.update(process=None, details={}, status="idle", error=None)

    # ── auto-recovery supervisor ──────────────────────────────────────────

    def _schedule_restart(self, camera_id: str, reason: str):
        """Log a stream failure and, if streaming is still desired, restart it
        after a short delay. After STREAM_MAX_RESTARTS consecutive failures,
        leave only that camera in an error state."""
        state = self.streams.get(camera_id)
        if not state:
            return
        logger.error("[%s] Stream failure: %s", camera_id, reason)
        state.update(status="error", error=reason, process=None, details={})
        self.publish_status()
        if not state.get("desired"):
            return  # operator stopped it — don't fight the intent

        state["restart_attempts"] = state.get("restart_attempts", 0) + 1
        if state["restart_attempts"] > STREAM_MAX_RESTARTS:
            logger.critical(
                "[%s] Stream failed %s times; giving up until the service "
                "or camera is restarted", camera_id, state["restart_attempts"])
            state["desired"] = False
            self.stop_stream(manual=True, camera_id=camera_id)
            state.update(
                status="error", error=f"{reason} — retry limit reached")
            self.publish_status()
            return

        logger.info(
            "[%s] Auto-restarting in %ss (attempt %s/%s)",
            camera_id, STREAM_RESTART_DELAY,
            state["restart_attempts"], STREAM_MAX_RESTARTS)
        camera = next(
            (c for c in self.discover_cameras() if c["id"] == camera_id), None)
        if not camera:
            return
        timer = threading.Timer(
            STREAM_RESTART_DELAY,
            lambda: self._start_camera(camera, self.last_start_params),
        )
        timer.daemon = True
        state["restart_timer"] = timer
        timer.start()

    def _read_stderr(self, camera_id, process):
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
            with self.lock:
                state = self.streams.get(camera_id, {})
                is_current = state.get("process") == process
                if is_current:
                    state.update(process=None, details={})
            if is_current:
                self._schedule_restart(
                    camera_id,
                    f"Stream crashed (exit {exit_code}): {stderr_tail}")

    def _is_streaming(self, camera_id: str | None = None) -> bool:
        states = [self.streams.get(camera_id)] if camera_id else self.streams.values()
        return any(
            state and state.get("process") is not None
            and state["process"].poll() is None
            for state in states
        )

    def _sync_cameras(self):
        """Hot-plug reconciliation, called from the heartbeat."""
        detected = {c["id"]: c for c in self.discover_cameras()}
        for camera_id in list(self.streams):
            if camera_id not in detected:
                self._stop_camera(camera_id, clear_intent=True)
                del self.streams[camera_id]
        if self.should_stream and self._in_window():
            for camera in detected.values():
                if camera["enabled"] and camera["id"] not in self.streams:
                    self._start_camera(camera, {})

    # ── broadcast schedule ────────────────────────────────────────────────

    def _resolve_location(self):
        """(lat, lon) for the sunrise/sunset calc: explicit config if set,
        otherwise IP-geolocated once and cached (retried every 30 min on
        failure). Returns None if location is unknown."""
        sched = self.config.get("schedule") or {}
        lat, lon = sched.get("latitude"), sched.get("longitude")
        if lat is not None and lon is not None:
            try:
                return float(lat), float(lon)
            except (TypeError, ValueError):
                pass
        now = time.time()
        if self._geo is not None and (now - self._geo_ts) < 1800:
            return self._geo or None
        self._geo_ts = now
        try:
            with urllib.request.urlopen("http://ip-api.com/json/", timeout=5) as r:
                info = json.loads(r.read().decode())
            if info.get("status") == "success":
                self._geo = (float(info["lat"]), float(info["lon"]))
                logger.info(f"Auto-detected location {self._geo} for sun schedule")
            else:
                self._geo = False
        except Exception as e:
            logger.warning(f"IP geolocation failed ({e}); sun schedule will use "
                           "the fixed fallback window")
            self._geo = False
        return self._geo or None

    def _window_bounds(self):
        """Effective (start_min, end_min) for today, or None to not restrict
        (schedule disabled / unresolvable). Sun mode computes sunrise/sunset
        and falls back to the fixed start/end when that isn't possible."""
        sched = self.config.get("schedule") or {}
        if not sched.get("enabled"):
            return None
        if sched.get("mode", "sun") == "sun":
            loc = self._resolve_location()
            if loc:
                now = time.localtime()
                tz = (now.tm_gmtoff or 0) / 3600.0
                sr = _sun_event(loc[0], loc[1], now.tm_year, now.tm_mon,
                                now.tm_mday, True, tz)
                ss = _sun_event(loc[0], loc[1], now.tm_year, now.tm_mon,
                                now.tm_mday, False, tz)
                if sr is not None and ss is not None:
                    return sr, ss
        # Fixed mode, or sun fallback.
        start = _parse_hhmm(sched.get("start"))
        end = _parse_hhmm(sched.get("end"))
        if start is None or end is None or start == end:
            return None
        return start, end

    def _in_window(self) -> bool:
        """True if the current LOCAL time is inside the broadcast window (or if
        no schedule is active). Handles windows that wrap past midnight."""
        bounds = self._window_bounds()
        if bounds is None:
            return True
        start, end = bounds
        now = time.localtime()
        cur = now.tm_hour * 60 + now.tm_min
        if start < end:
            return start <= cur < end
        # Overnight window, e.g. 22:00–06:00
        return cur >= start or cur < end

    def _apply_schedule(self):
        """Enforce the broadcast window: stream while inside it, rest (idle)
        while outside. No-op when scheduling is disabled."""
        if not (self.config.get("schedule") or {}).get("enabled"):
            return
        if self._in_window():
            if not self._is_streaming():
                logger.info("Schedule window open — starting stream")
                self.start_stream({})
        else:
            if self._is_streaming() or self.should_stream:
                logger.info("Schedule window closed — resting (stream stopped)")
                self.stop_stream(manual=True)
            self.publish_status("idle")

    def _schedule_loop(self):
        while True:
            time.sleep(SCHEDULE_CHECK_SECONDS)
            try:
                self._apply_schedule()
            except Exception as e:
                logger.error(f"Schedule check error: {e}")

    # ── control actions ───────────────────────────────────────────────────

    def action_set_schedule(self, payload):
        """Set (or clear) the daily broadcast window. Applied immediately.

        Params: enabled (bool), mode ('sun' | 'fixed'), start/end ('HH:MM',
        used in fixed mode and as the sun-mode fallback), and optional
        latitude/longitude to override IP geolocation for sunrise/sunset."""
        cur = self.config.get("schedule") or {}
        enabled = bool(payload.get("enabled", False))
        mode = payload.get("mode", cur.get("mode", "sun"))
        if mode not in ("sun", "fixed"):
            self.publish_reply(
                "set_schedule",
                {"ok": False, "error": "mode must be 'sun' or 'fixed'"},
                payload.get("request_id"))
            return
        start = payload.get("start", cur.get("start"))
        end = payload.get("end", cur.get("end"))
        # Fixed mode needs valid clock times; sun mode still keeps them as the
        # fallback window, so validate whenever they're provided.
        if mode == "fixed" and (_parse_hhmm(start) is None or _parse_hhmm(end) is None):
            self.publish_reply(
                "set_schedule",
                {"ok": False, "error": "start/end must be 'HH:MM' (00:00–23:59)"},
                payload.get("request_id"))
            return
        lat = payload.get("latitude", cur.get("latitude"))
        lon = payload.get("longitude", cur.get("longitude"))
        self.config["schedule"] = {
            "enabled": enabled, "mode": mode, "start": start, "end": end,
            "latitude": lat, "longitude": lon,
        }
        self._geo = None  # re-resolve location on next check
        self._save_config()
        self.publish_reply(
            "set_schedule",
            {"ok": True, "schedule": self.config["schedule"]},
            payload.get("request_id"))
        # Enforce right away; if disabled and not streaming, fall back to a
        # normal start so turning the schedule off resumes broadcasting.
        if enabled:
            self._apply_schedule()
        elif not self._is_streaming() and \
                self.config["stream"]["srt"].get("host"):
            self.start_stream({})

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

    def action_set_camera_enabled(self, payload):
        """Persistently include/exclude a detected camera from broadcasting."""
        camera_id = payload.get("camera_id")
        enabled = payload.get("enabled")
        if not CAMERA_ID_RE.match(camera_id or "") or not isinstance(enabled, bool):
            self.publish_reply(
                "set_camera_enabled",
                {"ok": False, "error": "camera_id and boolean enabled are required"},
                payload.get("request_id"))
            return
        camera = next(
            (c for c in self.discover_cameras() if c["id"] == camera_id), None)
        if not camera:
            self.publish_reply(
                "set_camera_enabled",
                {"ok": False, "error": f"Unknown camera: {camera_id}"},
                payload.get("request_id"))
            return

        entries = self.config["camera"].setdefault("devices", [])
        real = camera["real_device"]
        entry = next(
            (item for item in entries
             if os.path.realpath(item.get("device", "")) == real),
            None,
        )
        if entry is None:
            entry = {
                "id": camera_id,
                "label": camera["label"],
                "device": camera["device"],
            }
            entries.append(entry)
        entry["enabled"] = enabled
        self._save_config()

        if enabled and self.should_stream and self._in_window():
            refreshed = next(
                c for c in self.discover_cameras() if c["id"] == camera_id)
            if camera_id in self.streams:
                self.streams[camera_id]["restart_attempts"] = 0
            self._start_camera(refreshed, {})
        elif not enabled:
            self.stop_stream(manual=True, camera_id=camera_id)
        self.publish_status()
        self.publish_reply(
            "set_camera_enabled",
            {"ok": True, "camera_id": camera_id, "enabled": enabled},
            payload.get("request_id"))

    def action_set_controls(self, payload):
        """Set V4L2 controls (brightness, contrast, exposure, focus, ...)."""
        controls = payload.get("controls", {})
        camera_id = payload.get("camera_id")
        camera = next(
            (c for c in self.discover_cameras()
             if not camera_id or c["id"] == camera_id), None)
        device = camera["device"] if camera else self.config["camera"]["device"]
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
        camera_id = payload.get("camera_id")
        camera = next(
            (c for c in self.discover_cameras()
             if not camera_id or c["id"] == camera_id), None)
        device = camera["device"] if camera else self.config["camera"]["device"]
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
        self.stop_stream(manual=True)
        self.publish_status("offline")
        threading.Timer(1.0, lambda: os._exit(0)).start()

    def action_reboot(self, payload):
        self.publish_reply("reboot", {"ok": True}, payload.get("request_id"))
        self.stop_stream(manual=True)
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
            self.publish_status()
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
            "stop": lambda: (
                self.stop_stream(
                    manual=True, camera_id=payload.get("camera_id")),
                self.publish_status(),
            ),
            "set_camera": lambda: self.action_set_camera(payload),
            "set_camera_enabled": lambda: self.action_set_camera_enabled(payload),
            "set_schedule": lambda: self.action_set_schedule(payload),
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
                self._sync_cameras()
                self.publish_status()
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    def run(self):
        self._ensure_primary_camera()
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
        threading.Thread(target=self._schedule_loop, daemon=True).start()

        if (self.config.get("schedule") or {}).get("enabled"):
            logger.info("Schedule enabled — enforcing broadcast window")
            self._apply_schedule()
        elif self.config["stream"].get("auto_start") and \
                self.config["stream"]["srt"].get("host"):
            logger.info("auto_start enabled, starting stream")
            self.start_stream({})

        try:
            self.client.loop_forever()
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            self.stop_stream(manual=True)
            self.publish_status("offline")
            self.client.disconnect()


if __name__ == "__main__":
    CameraAgent().run()
