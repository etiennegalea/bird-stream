UNAME := $(shell uname -s)

.PHONY: up down build logs

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
