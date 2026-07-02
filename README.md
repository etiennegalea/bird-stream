# Bird Live Stream

A self-hosted WebRTC bird watching stream with live chat, user authentication, viewer queue management, and an admin panel.

## Features

- Live video stream via WebRTC (camera passthrough)
- Real-time chat with rate limiting and guest restrictions
- User authentication with JWT
- Viewer queue with WebSocket-based position updates
- Admin panel for user and session management
- TURN server (coturn) for NAT traversal
- PostgreSQL database with Alembic migrations

## Prerequisites

### macOS
- Docker Desktop
- Git
- A webcam connected to your system

### Linux (e.g. Proxmox VM, Ubuntu)
- Docker Engine
- Docker Compose plugin
- `make` (via `build-essential`)
- Git
- A webcam or video device (e.g. `/dev/video0`)

Install dependencies on Debian/Ubuntu:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin build-essential git
sudo systemctl enable --now docker
# Add your user to the docker group to run without sudo
sudo usermod -aG docker $USER
newgrp docker
```

## Setup

```bash
git clone https://github.com/etiennegalea/bird-stream.git
cd bird-stream
```

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

Key environment variables in `.env`:

| Variable | Description |
|----------|-------------|
| `VITE_API_URL` | Backend URL visible to the browser (e.g. `http://<host>:8051`) |
| `VITE_NODE_ENV` | `production` or `development` |
| `VITE_OPENRELAY_TURN_USERNAME` | TURN server username |
| `VITE_OPENRELAY_TURN_CREDENTIAL` | TURN server credential |
| `SECRET_KEY` | JWT signing secret |

## Running

### macOS

```bash
make up
```

### Linux

```bash
make up
```

The Makefile auto-detects the OS. On Linux it runs:

```bash
docker compose -f docker-compose.yml -f docker-compose.linux.yml up --build
```

The Linux override switches the backend and coturn containers to `network_mode: host` and maps `/dev/video0` into the backend container.

> **Note:** Make sure your video device exists before starting: `ls /dev/video*`

### Stop

```bash
make down
```

### View logs

```bash
make logs
```

## Access Points

| Service | URL / Port |
|---------|-----------|
| Frontend | `http://localhost:8050` |
| Backend API | `http://localhost:8051` |
| TURN (STUN/TURN) | Ports `3478`, `5349` |
| Database | Port `5432` (internal) |

## Development

Run the backend and frontend locally without Docker:

```bash
# Backend (requires uv)
make dev-backend

# Frontend
make dev-frontend
```

Run database migrations (requires the DB container to be up):

```bash
make migrate
```

Run backend tests:

```bash
make test-backend

# Unit tests only
make test-backend ARGS=tests/unit/

# Filter by name
make test-backend ARGS="-k rate"
```

## Architecture

| Component | Stack |
|-----------|-------|
| Frontend | Svelte + Vite, served via Nginx |
| Backend | Python 3.14, Litestar, aiortc, OpenCV |
| Database | PostgreSQL 17 |
| TURN server | coturn |
| Package manager | uv |

## Troubleshooting

**`/dev/video0` not found on Linux**
Ensure a camera is attached and the `v4l2` kernel module is loaded:
```bash
sudo modprobe v4l2
ls /dev/video*
```

**`make` not found on Linux**
```bash
sudo apt-get install build-essential
```

**Docker permission denied**
```bash
sudo usermod -aG docker $USER && newgrp docker
```

**Migrations fail on first boot**
The backend waits for the DB healthcheck to pass before running `alembic upgrade head`. If it still fails, run manually:
```bash
make migrate
```
