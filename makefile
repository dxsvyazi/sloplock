.PHONY: all

DC = docker compose --env-file '.env'
UP = up
STORAGES = ./docker-compose.yml
SERVICES = ./docker-compose.yml

migration:
	uv run alembic revision --autogenerate -m="${m}"

push-migrations:
	uv run alembic upgrade head

drop-migration:
	uv run alembic downgrade -1

all-up-cold:
	docker desktop start
	${DC} -f ${SERVICES} ${UP} -d

all-up:
	${DC} -f ${SERVICES} ${UP} -d

all-down:
	${DC} -f ${SERVICES} down

service-up:
	${DC} -f ${SERVICES} ${UP} ${name} -d

format:
	uv run ruff check --fix --select I

test:
	uv run pytest

test-full:
	uv run --env-file .env sh -c 'STOCKLOCK_TEST_DATABASE_URL="$$STOCKLOCK_DATABASE_URL" uv run --no-sync pytest -ra'