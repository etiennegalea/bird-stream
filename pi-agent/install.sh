#!/usr/bin/env bash
# Birdstream Pi agent installer — idempotent; re-run after `git pull` to upgrade.
#
#   git clone <repo> && cd <repo>/pi-agent && ./install.sh
#
# Flags:
#   --allow-reboot   add a sudoers rule so the MQTT 'reboot' action works
set -euo pipefail

SERVICE_NAME="birdstream-agent"
AGENT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_USER="${SUDO_USER:-$(whoami)}"
ALLOW_REBOOT=false
[[ "${1:-}" == "--allow-reboot" ]] && ALLOW_REBOOT=true

log() { echo -e "\033[1;32m[install]\033[0m $*"; }

# ── system packages ──────────────────────────────────────────────────────
log "Installing system packages (ffmpeg, v4l-utils, fonts, git, curl)..."
sudo apt-get update -qq
sudo apt-get install -y -qq ffmpeg v4l-utils fonts-dejavu-core git curl
sudo usermod -aG video,audio "$RUN_USER"

# ── uv ───────────────────────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    export PATH="$HOME/.local/bin:$PATH"
  else
    log "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi
log "Using uv $(uv --version | awk '{print $2}')"

# ── python venv (managed by uv) ──────────────────────────────────────────
if [[ ! -d "$AGENT_DIR/.venv" ]]; then
  log "Creating virtualenv with uv..."
  uv venv "$AGENT_DIR/.venv"
fi
log "Installing pinned Python dependencies with uv..."
uv pip install -q --python "$AGENT_DIR/.venv/bin/python" -r "$AGENT_DIR/requirements.txt"

# ── config ───────────────────────────────────────────────────────────────
if [[ ! -f "$AGENT_DIR/config.yaml" ]]; then
  log "Creating config.yaml from example — EDIT IT before relying on the stream."
  cp "$AGENT_DIR/config.yaml.example" "$AGENT_DIR/config.yaml"
else
  log "config.yaml exists, leaving it untouched."
fi

# ── systemd unit (templated from actual clone path + user) ───────────────
log "Installing systemd unit for user '$RUN_USER' at $AGENT_DIR..."
sed -e "s|@USER@|$RUN_USER|g" -e "s|@WORKDIR@|$AGENT_DIR|g" \
  "$AGENT_DIR/${SERVICE_NAME}.service.template" \
  | sudo tee "/etc/systemd/system/${SERVICE_NAME}.service" >/dev/null

# ── optional sudoers rule for remote reboot ──────────────────────────────
if $ALLOW_REBOOT; then
  log "Adding sudoers rule for remote reboot..."
  echo "$RUN_USER ALL=(root) NOPASSWD: /usr/sbin/reboot, /sbin/reboot" \
    | sudo tee /etc/sudoers.d/birdstream-agent >/dev/null
  sudo chmod 440 /etc/sudoers.d/birdstream-agent
fi

# ── enable + (re)start ───────────────────────────────────────────────────
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME" >/dev/null
if systemctl is-active --quiet "$SERVICE_NAME"; then
  log "Restarting $SERVICE_NAME..."
  sudo systemctl restart "$SERVICE_NAME"
else
  log "Starting $SERVICE_NAME..."
  sudo systemctl start "$SERVICE_NAME"
fi

log "Done. Follow logs with: journalctl -u $SERVICE_NAME -f"
