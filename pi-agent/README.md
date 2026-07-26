# Birdstream Pi Agent

Multi-camera transmitter for Raspberry Pi. The agent detects every V4L2
capture device, supervises one FFmpeg/SRT process per enabled camera, and
reports them together over MQTT. Cameras can be hot-plugged and appear in the
public application automatically.

## Install (on the Pi)

```bash
git clone git@github.com:etiennegalea/rp_bodycam.git
cd rp_bodycam/pi-agent
./install.sh                 # add --allow-reboot to enable the remote reboot action
nano config.yaml             # set device id, MQTT broker, SRT host + creds
sudo systemctl restart birdstream-agent
```

Re-running `install.sh` is safe — use `git pull && ./install.sh` to upgrade.

## MQTT topics

Each Pi uses its `device.id` from `config.yaml` (e.g. `pi-01`):

| Topic                  | Direction | Purpose                                  |
| ---------------------- | --------- | ---------------------------------------- |
| `camera/<id>/control`  | → Pi      | commands (JSON, see below)               |
| `camera/<id>/status`   | Pi →      | retained: idle / streaming / error / offline + CPU temp |
| `camera/<id>/reply`    | Pi →      | responses to get_* / set_* / update      |

## Actions

Publish JSON to `camera/<id>/control`. Optional `request_id` is echoed in replies.

```jsonc
{"action": "start"}                          // uses stream.srt from config
{"action": "start", "camera_id": "cam-2"}    // one camera only
{"action": "start", "srt_host": "10.0.0.5", "srt_port": 8890, "fps": 25}
{"action": "stop"}
{"action": "stop", "camera_id": "cam-2"}
{"action": "set_camera_enabled", "camera_id": "cam-2", "enabled": false}
{"action": "set_camera", "params": {"width": 1920, "height": 1080, "bitrate": "3000k"}}
                                             // persists to config.yaml, restarts stream if live
{"action": "set_controls", "controls": {"brightness": 60, "exposure_auto": 1}}
                                             // v4l2-ctl; list names with get_controls
{"action": "get_controls"}
{"action": "get_config"}
{"action": "update"}                         // git pull + pip install, systemd restarts agent
{"action": "reboot"}                         // needs install.sh --allow-reboot
```

An explicit `start` is an operator override: it starts immediately even when
the Pi is currently resting outside its scheduled broadcast window. The
configured schedule is not changed or disabled. Automatic schedule control
resumes when the next active window begins, and the stream stops at that
window's normal closing time. A device-level `stop` cancels the override.

## Multiple webcams

Run `ls -l /dev/v4l/by-id/` to find stable names. With
`camera.auto_detect: true`, every capture-capable webcam is enabled by default.
Configured `camera.devices` entries override matching devices but do not limit
automatic discovery. Set `camera.auto_detect: false` to make `camera.devices`
an explicit allowlist.
The first registered camera publishes to `birdcam`; subsequent cameras use
`birdcam-<pi-id>-<camera-id>`. The first camera identity is persisted as
`camera.primary_id`, so unplugging it does not make another camera steal the
legacy path.

Use `camera.devices` in `config.yaml` to give cameras stable labels, override
quality settings, or keep one disabled:

```yaml
camera:
  auto_detect: false          # only the two configured cameras below
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
      width: 1920
      height: 1080
      bitrate: 2500k
```

Only the primary camera process opens the configured ALSA microphone. This
avoids multiple FFmpeg processes competing for the same audio device. Audio
capture and public playback remain off by default.

## Files

- `agent.py` — the agent
- `config.yaml.example` — template; real `config.yaml` is gitignored
- `install.sh` — idempotent installer (apt deps, uv-managed venv, config, systemd)
- `birdstream-agent.service.template` — unit templated with actual user/path
- `requirements.txt` — pinned deps
- `test_agent.py` — unit tests; run with `python -m unittest test_agent -v` (no extra deps)
