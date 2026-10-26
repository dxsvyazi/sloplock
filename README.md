# StockLock

An asynchronous inventory and time-limited reservation API using FastAPI,
PostgreSQL, SQLAlchemy and Wireup. Python 3.13 or newer is required.

## Run locally

Copy `.env.example` to `.env`, replace the example credentials, and keep the two
database URLs consistent. Local processes use `localhost`; Compose processes use
`postgres`. Percent-encode special characters in URL credentials. `.env` and its
variants are excluded from Git and Docker; `.env.example` remains shareable.

```sh
uv sync --locked
uv run alembic upgrade head
uv run python main.py
```

Run the expiration worker in a separate process:

```sh
uv run python -m stocklock.infrastructure.workers.expiration
```

`SERVICE_HOST` defaults to `0.0.0.0`, `SERVICE_PORT` to `8000`, and
`SERVICE_RELOAD` to `false`. Enable reload explicitly for local development.
`SERVICE_SSL` describes a public URL behind a TLS proxy; it does not configure
an HTTPS listener. API documentation is at `/api/docs`; resource paths begin
with `/api/v1`.

## Run with Docker

```sh
docker compose up --build
```

Compose waits for PostgreSQL health, applies Alembic migrations, then starts the
API and expiration worker. Both `dev` and `prod` image targets install locked
runtime dependencies. PostgreSQL is pinned to version 18 and stores its cluster
under the volume mounted at `/var/lib/postgresql`; migrate an existing cluster
before reusing a volume initialized by a different major version or layout.

## Inventory behavior

`stock_quantity` means available units, excluding reservations. Stock corrections
set an absolute available quantity and must leave enough numeric capacity to
return every stored active hold, including overdue holds. Conflicting corrections
return HTTP 409 without changing inventory.

Reservation `key` values are opaque and case-sensitive, scoped to a product:
1–256 Unicode characters, at most 1,024 UTF-8 bytes, without NUL or surrounding
whitespace. Matching retries return the original reservation without extending
its deadline. Migration `0002_reservation_keys` rejects incompatible existing
keys for operator review; it never truncates them or changes retry identities.

Confirmation rejects holds at or after their deadline even before cleanup.
Stored status and available inventory update when the expiration worker runs;
GET/list endpoints expose that stored state. The default sweep interval is
60 seconds. Run the worker alongside the API in deployments outside Compose.
Retention deletion remains unimplemented.

See [services](docs/services.md), [transactions](docs/repositories.md), and
[time policies](docs/time-policies.md) for details.

## Verification

```sh
uv run ruff check .
uv run pytest -q
```

Set `STOCKLOCK_TEST_DATABASE_URL` to a disposable PostgreSQL database with schema
creation permission to include database, migration, and independent transaction
race tests. Tests use isolated schemas and remove them afterward. Without the
URL, PostgreSQL tests are explicitly skipped.

Worker database operations have a 30-second timeout. A locked or failed hold
rolls back and is revisited on a later sweep; later candidates continue. Compose
allows 35 seconds for graceful worker shutdown.
