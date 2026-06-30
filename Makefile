UNAME := $(shell uname -s)

.PHONY: up down build logs dev-backend dev-frontend migrate test-backend cli

# Run backend locally (uses macOS camera automatically via AVFoundation)
dev-backend:
	cd backend && uv run python server.py

# Run frontend dev server
dev-frontend:
	cd frontend && npm run dev

# Run Alembic migrations (requires DB to be running)
migrate:
	cd backend && uv run alembic upgrade head

up:
ifeq ($(UNAME),Darwin)
	docker compose up --build $(ARGS)
else
	docker compose -f docker-compose.yml -f docker-compose.linux.yml up --build $(ARGS)
endif

build:
ifeq ($(UNAME),Darwin)
	docker compose build $(ARGS)
else
	docker compose -f docker-compose.yml -f docker-compose.linux.yml build $(ARGS)
endif

down:
	docker compose down

logs:
	docker compose logs -f

# Run backend tests (unit + integration). Requires TEST_DATABASE_URL in backend/.env
# Usage: make test-backend                     (all tests)
#        make test-backend ARGS=tests/unit/    (unit only)
#        make test-backend ARGS="-k rate"      (filter by name)
test-backend:
	cd backend && uv run pytest tests/ -v $(ARGS)

# Typer CLI — wraps all commands above with --help support.
# Usage: make cli ARGS="up --detach"  or  make cli ARGS="--help"
cli:
	uv run --project backend python cli.py $(ARGS)
