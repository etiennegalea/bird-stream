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
make configurator
```

Open `http://localhost:8099` and choose the cloned project folder. The
configurator presents a deployment map: select the Proxmox server to edit
server settings, select a Raspberry Pi to edit that transmitter, or use the
**+** beside the Pi fleet to create another device. Server services and all
template-backed files remain available in the sidebar.

The tool discovers every tracked `.example` and `.template`, loads matching
existing generated files, and leaves values empty when the matching key is
absent. New transmitters are generated at
`pi-configs/<device-id>/config.yaml`. It runs entirely in your browser; no
configuration or secret is uploaded.

You can also create the two server files manually:

```bash
cp .env.template .env
cp mediamtx/mediamtx.yml.example mediamtx/mediamtx.yml
```

Generated files, including the complete `pi-configs/` directory, are
gitignored; templates contain no deployment secrets. The consistency panel
compares shared server settings against the currently selected Pi.
The critical `.env` values are:

| Variable | What it does |
|----------|--------------|
| `WEBRTC_PUBLIC_HOSTS` | Public IP **+** LAN IP, comma-separated, advertised to WebRTC viewers. Update when your ISP rotates your IP! Never a Cloudflare-proxied domain. |
| `MEDIAMTX_PUBLISH_USER` / `MEDIAMTX_PUBLISH_PASSWORD` | SRT publish credentials — must match the Pi's `config.yaml` |
| `JWT_SECRET_KEY`, `ADMIN_*`, `POSTGRES_*`, `DATABASE_URL` | Auth + database secrets |
| `STREAM_ACCESS_TOKEN_MINUTES` | Lifetime of the narrow MediaMTX read token used when admin-only viewing is enabled |
| `VITE_HLS_FALLBACK` | Opt-in HLS fallback (`true` enables it at build time; default `false`). Rebuild the frontend after changing it. |
| `INSTALL_DETECTION` / `DETECTION_ENABLED` | Bird detection (see below) |

### Configuration values that must agree

The configurator shows these relationships beside each field and in its
**Cross-file consistency** panel.

| Server / `.env` value | Matching value | Rule |
|---|---|---|
| `MEDIAMTX_PUBLISH_USER` | Pi `stream.srt.username` | Must be identical on every Pi |
| `MEDIAMTX_PUBLISH_PASSWORD` | Pi `stream.srt.password` | Must be identical on every Pi |
| `MEDIAMTX_PATH` | Pi `stream.srt.path` | Must be identical for the primary path |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | Mosquitto `backend` password-file entry | Must be the same credentials |
| `POSTGRES_*` | user/password/database embedded in `DATABASE_URL` | URL must be derived from the same values |
| `MEDIAMTX_API_URL` port | MediaMTX `apiAddress` | `:9997` corresponds to `http://mediamtx:9997` |
| `DETECTION_RTSP_BASE_URL` port | MediaMTX `rtspAddress` | `:8554` corresponds to `rtsp://mediamtx:8554` |
| `VITE_HLS_FALLBACK=true` | MediaMTX `hls: yes` | HLS must be enabled when fallback is enabled |
| `WEBRTC_PUBLIC_HOSTS` | MediaMTX advertised hosts | `.env` overrides `webrtcAdditionalHosts`; keep YAML empty |
| `APP_URL` | Cloudflare published application URL | Must use the same public HTTPS origin |

On each Pi:

| Pi value | Matching value | Rule |
|---|---|---|
| `mqtt.username` / `mqtt.password` | That Pi's Mosquitto password-file entry | Must be the same credentials |
| `mqtt.host` | `stream.srt.host` | Both normally use the Proxmox LAN address |
| `stream.srt.port` | MediaMTX `srtAddress` | `8890` corresponds to `:8890` |
| `device.id` | `mqtt.username` | Recommended to be identical for easier auditing |

Some related host values must deliberately differ:

- backend `MQTT_HOST` is `mosquitto`, the Docker service name;
- Pi `mqtt.host` and `stream.srt.host` use the Proxmox LAN IP/DNS name;
- backend MediaMTX URLs use `mediamtx`, the Docker service name;
- `WEBRTC_PUBLIC_HOSTS` contains the raw public/DNS-only address plus the
  Proxmox LAN address—not the Cloudflare-proxied application hostname.

If a real credential was committed before these files became ignored, removing
the file from the current revision does not erase Git history. Rotate that
credential immediately and rewrite repository history if the repository was
shared.

### 2. Create MQTT users

The broker intentionally refuses to start until its password file exists.
Create the backend user and one unique user per Pi. Passwords are prompted
interactively and do not appear in shell history:

```bash
./scripts/mosquitto-user.sh backend
./scripts/mosquitto-user.sh pi-01
```

Use the backend password as `MQTT_PASSWORD` in `.env`. Put each Pi user's
password in that Pi's `pi-agent/config.yaml`.

To replace passwords with client certificates, open the configurator's
**MQTT mutual TLS** section. It prepares one command for the backend and every
Pi, shows the required Pi YAML and backend variables, and links the tracked
`mosquitto/config/mosquitto-mtls.conf.example`,
`mosquitto/config/acl-mtls`, and `docker-compose.mtls.yml` references. The full
migration procedure is in `mosquitto/README.md`.

### 3. Start the stack

```bash
docker compose up -d --build
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

The admin stream panel includes an **Admin-only viewing** switch. Its state is
stored in Postgres and survives restarts. When enabled, public viewers see only
“The stream is not currently available”; admin browsers receive a short-lived
MediaMTX read token automatically. Chat remains public.

## Raspberry Pi setup

For the first transmitter, configure `pi-agent/config.yaml` directly. For
additional transmitters, use the configurator's **+** action and copy the
generated file to the corresponding Pi:

```bash
scp pi-configs/pi-02/config.yaml \
  pi@<pi-host>:~/apps/bird-stream/pi-agent/config.yaml
```

Then install or update the agent on that Pi:

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

With `camera.auto_detect: true`, every V4L2 capture device is enabled
automatically. Configured entries are overrides, not an allowlist; use
`auto_detect: false` when only explicitly configured cameras should appear.
The first detected camera keeps the `birdcam` path; additional cameras publish
as `birdcam-<pi-id>-<camera-id>`. Their enabled state is persisted in
`config.yaml`, and enabled live cameras appear automatically in the public
multi-stream player. The first available configured stream is the main view;
the remaining live streams are grouped by Pi in a bottom-right thumbnail tray.
Selecting a thumbnail swaps it with the main view in that browser only. For
stable names and labels, use `/dev/v4l/by-id/...` entries:

```yaml
camera:
  auto_detect: false             # restrict this Pi to the entries below
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
start, and stop controls. A manual start overrides a current scheduled resting
period without disabling the schedule; normal schedule control resumes at the
next active window. See `pi-agent/README.md` for payload examples.

## Bird detection (optional)

Runs inside the backend container: motion-gated YOLO over MediaMTX's internal RTSP feed. In `.env` set `INSTALL_DETECTION="true"` (bakes ultralytics/torch into the image — large) and `DETECTION_ENABLED="true"`, then:

```bash
docker compose build backend && docker compose up -d backend
curl localhost:8051/detection/status     # or /detection/latest, /detection/events
```

The lightweight model recognizes only `bird`, `cat`, and `human` for this
application. Bird alerts are sent to verified, unblocked subscribers only after
a bird remains visible for `BIRD_LINGER_SECONDS` (3 seconds by default). The
snapshot taken at that point is cropped around all visible birds with a
configurable `BIRD_SNAPSHOT_BORDER`, embedded in the prepared email, and
attached as a JPEG. Tune sampling and recognition with `DETECTION_FPS`,
`DETECTION_CONF`, and `DETECTION_CLASSES`; tune brief missed detections with
`BIRD_PRESENCE_GAP_SECONDS` and repeat-alert suppression with
`BIRD_NOTIFICATION_COOLDOWN_SECONDS`.
With `DETECTION_STREAM_URL=auto`, the worker queries MediaMTX and follows the
first active camera path, preferring the legacy `birdcam` path. Set an explicit
internal RTSP URL such as `rtsp://mediamtx:8554/birdcam-pi-01-feeder` to pin
detection to one camera.
`DETECTION_MODEL` defaults to `yolo11n.pt`. On first use, its weights are
downloaded into the persistent `detection_models` Docker volume mounted at
`DETECTION_MODEL_DIR=/var/lib/birdstream/models`, so container rebuilds do not
download the model again.

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
make test-configurator
make configurator     # local config builder at http://localhost:8099
```

## Troubleshooting

**Video connects but never renders (eternal spinner, no errors).** H264 profile problem: browsers can't decode 4:2:2. The agent forces `-pix_fmt yuv420p`; if you hand-roll FFmpeg commands, keep that flag. Check `chrome://webrtc-internals`: `packetsReceived` climbing while `framesDecoded` stays 0 confirms it.

**WHEP session `deadline exceeded while waiting connection`.** The browser can't reach the media port: check `WEBRTC_PUBLIC_HOSTS` matches your *current* public IP (`curl -4 ifconfig.me` — ISPs rotate it), the `8189/udp` forward, and `sudo tcpdump -i any -n udp port 8189` while a viewer connects.

**Pi status `error` on MQTT.** The message includes FFmpeg's stderr tail. Usual suspects: `use_hw_acceleration: true` on a Pi where `h264_v4l2m2m` is broken (keep it false), missing `/dev/video0`, or wrong SRT credentials (backend logs show `Deny publish`).

**Backend can't resolve `db` after compose changes.** Orphaned containers hold the old network: `docker compose down --remove-orphans && docker compose up -d`.

**Frontend flag changes (VITE_*) have no effect.** They're baked at build time: `docker compose build frontend && docker compose up -d frontend`, then hard-refresh (the old bundle is cached).

**Compose warns that a variable with a random-looking name is not set.** A
password in `.env` contains `$`, which Compose treats as interpolation in
unquoted and double-quoted values. Single-quote the complete value (for
example, `ADMIN_PASSWORD='pa$word'`), then run `docker compose config --quiet`
again. The warning means the password was otherwise changed before reaching
the container.

**Detection logs RTSP `DESCRIBE failed: 404`.** The configured path is not
currently being published to MediaMTX. Use `DETECTION_STREAM_URL=auto` to
follow the first active `birdcam` path, or confirm the Pi is publishing before
pinning an explicit path. `docker logs mediamtx --tail 20` shows active
publishers.

**Slow backend builds / `Building numpy` in the log.** A pinned dependency has no wheels for the image's Python version and is compiling from source — bump the pin and `uv lock`.

**Mosquitto says `Unable to open .../passwd`.** The broker cannot accept users
until its password database exists. Run `./scripts/mosquitto-user.sh backend`
and then add one user per Pi. Do not use `docker exec` for initial creation:
there is no running broker container to execute inside.

**Detection reports `Connection refused` to `mediamtx:8554`.** Check
`docker compose ps mediamtx` and `docker compose logs mediamtx`. Make sure
`mediamtx/mediamtx.yml` exists (generate it with `make configurator` or copy
the example), then recreate it with `docker compose up -d mediamtx backend`.
