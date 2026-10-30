.DEFAULT_GOAL := help

UV ?= uv
DC ?= docker compose --env-file .env -f docker-compose.yml

.PHONY: all

help:
	@printf '%s\n' \
	  'Local:      env sync db-up migrate run expiration retention product-cleanup' \
	  'Compose:    up down logs service-up name=SERVICE' \
	  'Quality:    lint format test test-full (requires STOCKLOCK_TEST_DATABASE_URL)' \
	  'Migrations: migration m="description" | push-migrations | drop-migration' \
	  'Aliases:    all-up all-up-cold all-down'

env:
	@test -e .env || cp .env.example .env

sync:
	$(UV) sync --locked

db-up:
	$(DC) up -d --wait postgres

migrate:
	$(UV) run alembic upgrade head

run:
	$(UV) run python main.py

expiration:
	$(UV) run python -m stocklock.infrastructure.workers.expiration

retention:
	$(UV) run python -m stocklock.infrastructure.workers.retention

product-cleanup:
	$(UV) run python -m stocklock.infrastructure.workers.product_cleanup

migration:
	@test -n "$(m)" || { echo 'Usage: make migration m="description"' >&2; exit 1; }
	$(UV) run alembic revision --autogenerate -m "$(m)"

push-migrations: migrate

drop-migration:
	$(UV) run alembic downgrade -1

up:
	$(DC) up --build -d

down:
	$(DC) down

logs:
	$(DC) logs -f

service-up:
	@test -n "$(name)" || { echo 'Usage: make service-up name=SERVICE' >&2; exit 1; }
	$(DC) up -d $(name)

all-up: up

all-up-cold:
	docker desktop start
	$(MAKE) up

all-down: down

lint:
	$(UV) run ruff check .

format:
	$(UV) run ruff check --fix --select I .
	$(UV) run ruff format .

test:
	$(UV) run pytest -q

test-full:
	@test -n "$$STOCKLOCK_TEST_DATABASE_URL" || { echo 'Set STOCKLOCK_TEST_DATABASE_URL to a disposable PostgreSQL database' >&2; exit 1; }
	$(UV) run pytest -ra
