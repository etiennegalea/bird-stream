# Bird Live Stream

A self-hosted bird-watching live stream. Raspberry Pi transmitters automatically
detect attached webcams and push one independent SRT stream per camera to a
home server, where MediaMTX re-broadcasts them to the public via WebRTC (WHEP,
sub-second latency) with an optional HLS fallback — no transcoding on the
server. Live chat, accounts, viewer count, an admin panel, and optional
on-server bird detection (YOLO) round it out.

## Architecture

![Architecture diagram](https://www.plantuml.com/plantuml/proxy?cache=no&fmt=svg&src=https://raw.githubusercontent.com/etiennegalea/rp_bodycam/main/docs/architecture.puml)

Source: [`docs/architecture.puml`](docs/architecture.puml) — rendered live by the PlantUML proxy from the `main` branch (edit the URL if viewing another branch), or render locally with `plantuml docs/architecture.puml` / any IDE PlantUML plugin.

<details>
<summary>Text version</summary>

```
Raspberry Pi                      Server (Proxmox box)                    Viewers
┌──────────────────┐   SRT/LAN   ┌──────────────────────────────┐
│ pi-agent          │ ─────────► │ MediaMTX ──► WHEP (WebRTC) ───┼──► browser (via 8189/udp)
│  FFmpeg: v4l2 cam │   :8890    │    │     └─► HLS (fallback) ──┼──► browser (via tunnel)
│  + ALSA mic       │            │    └─► RTSP (internal only)   │
│  libx264 + opus   │   MQTT     │         └─► detection (YOLO)  │
│  timestamp overlay│ ◄────────► │ mosquitto                     │
└──────────────────┘   :1883    │ traefik :80 ◄── cloudflared ───┼──► https://stream.…com
                                 │   ├─ /      → frontend (SPA)  │      (Cloudflare Zero
                                 │   ├─ /api   → backend         │       Trust tunnel)
                                 │   ├─ /birdcam → WHEP          │
                                 │   └─ /hls   → HLS             │
                                 │ backend (Litestar) + postgres │
                                 └──────────────────────────────┘
```

</details>

Only HTTP rides the Cloudflare tunnel. WebRTC media flows directly through **one forwarded UDP port (8189)**. The Pi→server leg (SRT 8890, MQTT 1883) stays inside the LAN.

| Component | Stack |
|-----------|-------|
| Transmitter | Python agent + FFmpeg, controlled over MQTT v5 |
| Media server | MediaMTX (SRT in, WHEP/HLS out, no transcode) |
| Frontend | Svelte + Vite (WHEP player, hls.js fallback), nginx |
| Backend | Python 3.14, Litestar (auth, chat, queue, detection) |
| Edge | traefik v3.6+ behind a Cloudflare Zero Trust tunnel |
| Database | PostgreSQL 17 + Alembic |
| Detection | Ultralytics YOLO (optional, motion-gated) |

## Prerequisites

Server: Docker Engine + compose plugin, `make`, git. A Cloudflare account with a Zero Trust tunnel for your domain. Router access to forward one UDP port.

Raspberry Pi: Raspberry Pi OS, a USB camera (MJPEG-capable) with mic, LAN access to the server. Everything else is installed by `install.sh`.

## Server setup

### 1. Configure environment

```bash
git clone https://github.com/etiennegalea/bird-stream.git && cd bird-stream
cp .env.template .env
```

Edit `.env` — everything is controlled from this one file. The critical values:

| Variable | What it does |
|----------|--------------|
| `WEBRTC_PUBLIC_HOSTS` | Public IP **+** LAN IP, comma-separated, advertised to WebRTC viewers. Update when your ISP rotates your IP! Never a Cloudflare-proxied domain. |
| `MEDIAMTX_PUBLISH_USER` / `MEDIAMTX_PUBLISH_PASSWORD` | SRT publish credentials — must match the Pi's `config.yaml` |
| `JWT_SECRET_KEY`, `ADMIN_*`, `POSTGRES_*`, `DATABASE_URL` | Auth + database secrets |
| `VITE_HLS_FALLBACK` | HLS fallback on/off (build-time: rebuild frontend after changing) |
| `INSTALL_DETECTION` / `DETECTION_ENABLED` | Bird detection (see below) |

### 2. Start the stack

```bash
docker compose up -d --build
```

### 3. Create MQTT users (once)

```bash
docker exec mosquitto mosquitto_passwd -b /mosquitto/config/passwd pi-01 <mqtt-password>
docker restart mosquitto
```

### 4. Cloudflare tunnel

In Zero Trust → Tunnels, point your public hostname (e.g. `stream.example.com`) at `http://<server-LAN-IP>:80` (traefik). Or run cloudflared inside compose: uncomment the `cloudflared` service and set `CLOUDFLARE_TUNNEL_TOKEN` in `.env`.

### 5. Router port forward

Forward **`8189/udp` → server LAN IP**. That's the only forwarded port needed; everything else rides the tunnel or stays on the LAN.

### 6. Admin user

An admin is seeded from `ADMIN_*` env on first boot. To add/promote later:

```bash
docker exec stream-backend python scripts/create_admin.py admin:somepassword
```

## Raspberry Pi setup

```bash
git clone https://github.com/etiennegalea/bird-stream.git ~/apps/bird-stream
cd ~/apps/bird-stream/pi-agent
./install.sh                # add --allow-reboot to enable remote reboot via MQTT
nano config.yaml            # see below
sudo systemctl restart birdstream-agent
```

`install.sh` is idempotent (apt deps, uv-managed venv, systemd unit templated to your user/path); upgrade with `git pull && ./install.sh`. In `config.yaml` set:

```yaml
device:
  id: "pi-01"                     # unique per Pi -> topics camera/pi-01/...
mqtt:
  host: "<server-LAN-IP>"
  username: "pi-01"
  password: "<mqtt-password>"     # from mosquitto_passwd above
audio:
  enabled: true                   # deliberate opt-in — audio is OFF by default
                                  # everywhere (Pi capture AND the admin panel
                                  # broadcast toggle must both be enabled).
                                  # Find the mic device with: arecord -l
stream:
  srt:
    host: "<server-LAN-IP>"
    username: "picam"             # = MEDIAMTX_PUBLISH_USER
    password: "<srt-password>"    # = MEDIAMTX_PUBLISH_PASSWORD
```

Every V4L2 capture device is enabled automatically. The first detected camera
keeps the `birdcam` path; additional cameras publish as
`birdcam-<pi-id>-<camera-id>`. Their enabled state is persisted in
`config.yaml`, and enabled live cameras appear automatically in the public
camera picker. For stable names and labels, use `/dev/v4l/by-id/...` entries:

```yaml
camera:
  auto_detect: true
  enabled_by_default: true
  devices:
    - id: feeder
      label: Feeder camera
      device: /dev/v4l/by-id/usb-Example-video-index0
      enabled: true
    - id: nest
      label: Nest box
      device: /dev/v4l/by-id/usb-Other-video-index0
      enabled: false
```

List stable camera paths with `ls -l /dev/v4l/by-id/`. The installer adds the
agent user to the `video` and `audio` groups. Each camera is a separate
software H.264 encoder, so monitor Pi CPU temperature and lower FPS/resolution
or bitrate when attaching several cameras.

With `auto_start: true` (default) the Pi streams on boot. Control it over MQTT
(`camera/<id>/control`): `start`/`stop` (all cameras or one with `camera_id`),
`set_camera_enabled`, `set_camera`, `set_controls`, `get_config`, `update`, and
`reboot`. Status heartbeats contain a `streams[]` entry for every attached
camera. The admin stream panel exposes the same per-camera status, enable,
start, and stop controls. See `pi-agent/README.md` for payload examples.

## Bird detection (optional)

Runs inside the backend container: motion-gated YOLO over MediaMTX's internal RTSP feed. In `.env` set `INSTALL_DETECTION="true"` (bakes ultralytics/torch into the image — large) and `DETECTION_ENABLED="true"`, then:

```bash
docker compose build backend && docker compose up -d backend
curl localhost:8051/detection/status     # or /detection/latest, /detection/events
```

Tune with `DETECTION_FPS`, `DETECTION_CONF`, `DETECTION_CLASSES`.

## Verifying the pipeline

```bash
# 1. Pi is streaming? (retained MQTT status, includes CPU temp + stream details)
docker exec mosquitto mosquitto_sub -u pi-01 -P <pw> -t 'camera/pi-01/status' -C 1 -v

# 2. MediaMTX receiving? Expect one "is publishing" line per enabled camera.
docker logs mediamtx --tail 20

# 3. Watch the primary camera on LAN: http://<server-LAN-IP>:8889/birdcam
#    Additional path names are in the MQTT streams[] status payload.

# 4. Public: https://stream.example.com — watch mediamtx logs for
#    "peer connection established" per viewer.
```

## Development

```bash
make dev-backend      # local backend via uv
make dev-frontend     # vite dev server (set VITE_API_URL/VITE_STREAM_URL in .env)
make migrate          # alembic migrations
make test-backend     # pytest (ARGS=tests/unit/ or ARGS="-k name")
```

## Troubleshooting

**Video connects but never renders (eternal spinner, no errors).** H264 profile problem: browsers can't decode 4:2:2. The agent forces `-pix_fmt yuv420p`; if you hand-roll FFmpeg commands, keep that flag. Check `chrome://webrtc-internals`: `packetsReceived` climbing while `framesDecoded` stays 0 confirms it.

**WHEP session `deadline exceeded while waiting connection`.** The browser can't reach the media port: check `WEBRTC_PUBLIC_HOSTS` matches your *current* public IP (`curl -4 ifconfig.me` — ISPs rotate it), the `8189/udp` forward, and `sudo tcpdump -i any -n udp port 8189` while a viewer connects.

**Pi status `error` on MQTT.** The message includes FFmpeg's stderr tail. Usual suspects: `use_hw_acceleration: true` on a Pi where `h264_v4l2m2m` is broken (keep it false), missing `/dev/video0`, or wrong SRT credentials (backend logs show `Deny publish`).

**Backend can't resolve `db` after compose changes.** Orphaned containers hold the old network: `docker compose down --remove-orphans && docker compose up -d`.

**Frontend flag changes (VITE_*) have no effect.** They're baked at build time: `docker compose build frontend && docker compose up -d frontend`, then hard-refresh (the old bundle is cached).

**Slow backend builds / `Building numpy` in the log.** A pinned dependency has no wheels for the image's Python version and is compiling from source — bump the pin and `uv lock`.
