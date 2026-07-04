# Birdstream Pi Agent

Camera transmitter for Raspberry Pi. FFmpeg captures the camera, burns in a
timestamp overlay, and pushes SRT to MediaMTX on the server. Controlled
remotely over MQTT v5.

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
{"action": "start", "srt_host": "10.0.0.5", "srt_port": 8890, "fps": 25}
{"action": "stop"}
{"action": "set_camera", "params": {"width": 1920, "height": 1080, "bitrate": "3000k"}}
                                             // persists to config.yaml, restarts stream if live
{"action": "set_controls", "controls": {"brightness": 60, "exposure_auto": 1}}
                                             // v4l2-ctl; list names with get_controls
{"action": "get_controls"}
{"action": "get_config"}
{"action": "update"}                         // git pull + pip install, systemd restarts agent
{"action": "reboot"}                         // needs install.sh --allow-reboot
```

## Files

- `agent.py` — the agent
- `config.yaml.example` — template; real `config.yaml` is gitignored
- `install.sh` — idempotent installer (apt deps, venv, config, systemd)
- `birdstream-agent.service.template` — unit templated with actual user/path
- `requirements.txt` — pinned deps
