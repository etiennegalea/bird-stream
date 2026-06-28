#!/usr/bin/env python3
"""
Bird Stream project CLI.

Run from the project root via:
    uv run --project backend python cli.py <command> [options]

Or via make:
    make cli ARGS="<command> [options]"
"""

import platform
import subprocess
import sys
from pathlib import Path

import typer

app = typer.Typer(
    name="birb",
    help="Manage the Bird Stream project — dev servers, migrations, and Docker.",
    no_args_is_help=True,
)

_ROOT = Path(__file__).resolve().parent
_BACKEND = _ROOT / "backend"
_FRONTEND = _ROOT / "frontend"
_IS_LINUX = platform.system() == "Linux"


def _run(cmd: list[str], cwd: Path = _ROOT) -> None:
    """Run a command and forward its exit code."""
    result = subprocess.run(cmd, cwd=cwd)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def _compose(*args: str) -> list[str]:
    """Build a docker compose command, adding the Linux override file when needed."""
    base = ["docker", "compose"]
    if _IS_LINUX:
        base += ["-f", "docker-compose.yml", "-f", "docker-compose.linux.yml"]
    return base + list(args)


# ── local dev ─────────────────────────────────────────────────────────────────

@app.command("dev-backend")
def dev_backend():
    """Run the backend development server locally (uvicorn via uv)."""
    _run(["uv", "run", "python", "server.py"], cwd=_BACKEND)


@app.command("dev-frontend")
def dev_frontend():
    """Run the Vite frontend development server."""
    _run(["npm", "run", "dev"], cwd=_FRONTEND)


# ── database ──────────────────────────────────────────────────────────────────

@app.command()
def migrate(
    revision: str = typer.Argument("head", help="Alembic revision target."),
):
    """Run Alembic migrations against the local database."""
    _run(["uv", "run", "alembic", "upgrade", revision], cwd=_BACKEND)


# ── docker ────────────────────────────────────────────────────────────────────

@app.command()
def up(
    detach: bool = typer.Option(False, "--detach", "-d", help="Run containers in the background."),
    no_build: bool = typer.Option(False, "--no-build", help="Skip rebuilding images."),
    service: str = typer.Argument("", help="Start only this service (default: all)."),
):
    """Build and start Docker services."""
    args: list[str] = []
    if not no_build:
        args.append("--build")
    if detach:
        args.append("-d")
    if service:
        args.append(service)
    _run(_compose("up", *args))


@app.command()
def down(
    volumes: bool = typer.Option(False, "--volumes", "-v", help="Also remove named volumes."),
):
    """Stop and remove Docker containers."""
    args = ["-v"] if volumes else []
    _run(_compose("down", *args))


@app.command()
def build(
    no_cache: bool = typer.Option(False, "--no-cache", help="Build without Docker layer cache."),
    service: str = typer.Argument("", help="Build only this service (default: all)."),
):
    """Build Docker images."""
    args: list[str] = []
    if no_cache:
        args.append("--no-cache")
    if service:
        args.append(service)
    _run(_compose("build", *args))


@app.command()
def logs(
    follow: bool = typer.Option(True, "--follow/--no-follow", "-f/-F", help="Stream log output."),
    tail: int = typer.Option(50, "--tail", "-n", help="Number of recent lines to show."),
    service: str = typer.Argument("", help="Service to inspect (default: all)."),
):
    """Tail Docker service logs."""
    args = [f"--tail={tail}"]
    if follow:
        args.append("--follow")
    if service:
        args.append(service)
    _run(_compose("logs", *args))


if __name__ == "__main__":
    app()
