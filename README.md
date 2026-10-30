# StockLock

StockLock is an asynchronous inventory and time-limited reservation API. It holds
available stock atomically, lets clients confirm or cancel reservations, and runs
separate workers for expiration and historical cleanup.

Built with **Python 3.13+**, **FastAPI**, **PostgreSQL**, **SQLAlchemy**, and
**Wireup**, with Alembic migrations and uv for dependency management. Business
rules live in a framework-independent domain; application use cases own transactions.

## Contents

- [Development instructions](#development-instructions)
  - [Raw commands](#raw-commands)
  - [Using the Makefile](#using-the-makefile)
- [Try the API](#try-the-api)
- [API reference](#api-reference)
- [Inventory and lifecycle rules](#inventory-and-lifecycle-rules)
- [Configuration](#configuration)
- [Workers and retention](#workers-and-retention)
- [Architecture and contributing](#architecture-and-contributing)
- [Troubleshooting](#troubleshooting)

## Development instructions

Prerequisites: Python 3.13 or newer, uv, and PostgreSQL (the supplied Compose
stack uses PostgreSQL 18). Install Docker with the Compose plugin to use the
container commands, and GNU Make for the optional shortcuts. Run commands from
the repository root. Dependency versions come from `pyproject.toml` and `uv.lock`.

Choose either a local Python API with PostgreSQL in Docker, or the complete
Compose stack. Both workflows below use `.env.example` as their starting point.
Edit `.env` before starting: replace example credentials and keep
`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`, and
`STOCKLOCK_DATABASE_URL` consistent. Local URLs use `localhost` and the published
port; Compose overrides the URL to use `stocklock-postgres:5432` internally.
Percent-encode special characters in URL credentials. Keep real credentials and
admin tokens out of Git; `.env.example` contains shareable placeholders only.

### Raw commands

**1. Prepare the environment and dependencies.** Copy the example only if `.env`
does not already exist, then edit it in your preferred editor:

```sh
test -e .env || cp .env.example .env
uv sync --locked
```

**2. Start PostgreSQL, apply migrations, and run the local API:**

```sh
docker compose --env-file .env -f docker-compose.yml up -d --wait postgres
uv run alembic upgrade head
uv run python main.py
```

An existing PostgreSQL server works too: configure `STOCKLOCK_DATABASE_URL` and
skip the Compose database command. Set `SERVICE_RELOAD=true` for local reload.
The API does not start workers; run each in its own terminal:

```sh
uv run python -m stocklock.infrastructure.workers.expiration
uv run python -m stocklock.infrastructure.workers.retention
uv run python -m stocklock.infrastructure.workers.product_cleanup
```

**3. Alternatively, run the complete stack in containers:**

```sh
docker compose --env-file .env -f docker-compose.yml up --build -d
docker compose --env-file .env -f docker-compose.yml logs -f
```

Compose waits for database health, runs migrations, and starts the API and all
three workers. Stop the local API first to avoid competing for its port. The
container entrypoint currently enables reload and reads `PORT` (default `8000`)
and `WORKERS` (default `1`); it does not use `main.py`'s `SERVICE_RELOAD` setting.
Keep `SERVICE_PORT=8000` for the default Compose setup. If changing it, also set
`PORT` to the same value in `.env` so the listener matches the port mapping.
The `dev` image target installs locked runtime dependencies; use local uv for
linting and tests. The `prod` target currently relies on uv at container startup
and uses the same reload-enabled entrypoint; review it before production use.

Stop containers when finished (the named database volume is preserved):

```sh
docker compose --env-file .env -f docker-compose.yml down
```

**4. Run quality checks:**

```sh
uv run ruff check .
uv run pytest -q
```

PostgreSQL integration, migration, and concurrency tests require an explicit
`STOCKLOCK_TEST_DATABASE_URL`. Use a disposable database whose user can create
schemas. Tests create isolated schemas and remove them afterward. Without the
variable, database tests are skipped; passing unit tests alone does not validate
transaction races. Export your own test connection URL, then run:

```sh
export STOCKLOCK_TEST_DATABASE_URL='postgresql+asyncpg://stocklock:change-me@localhost:5432/stocklock_test'
uv run pytest -ra
```

The example assumes you have separately created `stocklock_test`; Compose creates
only `POSTGRES_DB`. Test code reads the test URL from the process environment,
not automatically from `.env`.

To sort imports and format Python files (these commands modify files):

```sh
uv run ruff check --fix --select I .
uv run ruff format .
```

**5. Create or roll back a migration when needed:**

```sh
uv run alembic revision --autogenerate -m "describe schema change"
uv run alembic upgrade head
# Optional: undo the latest migration; review its downgrade before running.
uv run alembic downgrade -1
```

Autogeneration needs a reachable, current database. Review generated migrations,
including constraints and data changes, before applying them.

### Using the Makefile

These targets wrap the same commands shown above. `make` or `make help` lists
available tasks. `make env` preserves an existing `.env`; edit its credentials
before starting services.

```sh
make env
make sync
make db-up
make migrate
make run
```

Run workers in separate terminals:

```sh
make expiration
make retention
make product-cleanup
```

Or run the full Compose stack:

```sh
make up
make logs
# When finished:
make down
```

Quality checks and schema maintenance:

```sh
make lint
make test
# Export the disposable database URL as in the raw-command instructions first.
make test-full
make format
make migration m="describe schema change"
make migrate
# Optional rollback:
make drop-migration
```

| Target | Purpose |
| --- | --- |
| `env` / `sync` | Create missing `.env` / install locked dependencies, including dev tools |
| `db-up` | Start PostgreSQL and wait for its health check |
| `run` | Start the local API using `main.py` |
| `expiration` / `retention` / `product-cleanup` | Start one worker in the foreground |
| `up` / `down` / `logs` | Build and start the stack / stop it / follow its logs |
| `service-up name=expiration` | Start a named Compose service and its dependencies |
| `lint` / `format` | Check Ruff rules / sort imports and format files |
| `test` | Run tests; PostgreSQL tests skip unless a test URL is exported |
| `test-full` | Require an exported test URL, then run tests with skip/failure summaries |
| `migration m="description"` | Generate a migration for review |
| `migrate` / `push-migrations` | Apply all pending migrations |
| `drop-migration` | Downgrade one revision; may discard data |

Existing `all-up` and `all-down` targets alias `up` and `down`. `all-up-cold`
starts Docker Desktop before `up`; use it only on hosts with Docker Desktop.
Override tools with `make UV=/path/to/uv` or `make DC='docker compose ...'`.

## Try the API

With default settings, open [Swagger UI](http://localhost:8000/api/docs).
OpenAPI is served at `/openapi.json`; resource routes begin with `/api/v1`.

Check database readiness and create a product:

```sh
curl --fail-with-body http://localhost:8000/api/v1/healthcheck
curl --fail-with-body -X POST http://localhost:8000/api/v1/products \
  -H 'Content-Type: application/json' \
  -d '{"name":"Widget","sku":"WIDGET-001","stock_quantity":10}'
```

Copy the returned product `id`, then reserve two units:

```sh
PRODUCT_ID='<product UUID>'
curl --fail-with-body -X POST "http://localhost:8000/api/v1/products/$PRODUCT_ID/reservations" \
  -H 'Content-Type: application/json' \
  -d '{"quantity":2,"key":"example-order-001"}'
```

Copy the reservation `id` and confirm it before its deadline:

```sh
RESERVATION_ID='<reservation UUID>'
curl --fail-with-body -X POST "http://localhost:8000/api/v1/reservations/$RESERVATION_ID/confirm"
curl --fail-with-body "http://localhost:8000/api/v1/reservations/$RESERVATION_ID/confirmation"
```

Repeat the reservation request with the same product, key, and quantity to
retrieve its original result. Repeat confirmation to retrieve the original
confirmation. To exercise cancellation, create a separate active hold and call
`POST /api/v1/reservations/{reservation_id}/cancel`.

## API reference

All paths below are relative to `/api/v1`. Lists return JSON arrays.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/healthcheck` | Database readiness; `200` with `true`, or `503` when unavailable; no caching |
| POST | `/products` | Create with `name`, `sku`, `stock_quantity`; returns `201` |
| GET | `/products` | List available stock; defaults to visible products |
| GET | `/products/{id}` | Product details; optional admin `include_deleted=true` |
| PATCH | `/products/{id}` | Update `name` and/or `sku`; at least one non-null field required |
| PATCH | `/products/{id}/stock` | Set absolute available `stock_quantity` |
| DELETE | `/products/{id}` | Admin soft deletion, or explicit `?mode=hard`; returns empty `204` |
| POST | `/products/{id}/reservations` | Reserve with positive `quantity` and idempotency `key`; returns `201` |
| GET | `/products/{id}/reservations` | Product history, including after soft deletion |
| GET | `/reservations` | List reservations |
| GET | `/reservations/{id}` | Stored status, quantity, and expiration time |
| POST | `/reservations/{id}/cancel` | Cancel a stored active hold and return its stock |
| POST | `/reservations/{id}/expire` | Expire a due active hold and return its stock |
| POST | `/reservations/{id}/confirm` | Confirm before expiry, or return an existing confirmation |
| GET | `/reservations/{id}/confirmation` | Retrieve a retained confirmation |

Pagination uses an exclusive `start_id` UUID cursor and `limit` (default `50`,
maximum `100`) in ascending UUID order. Use the last item's `id` for the next
page. Reservation lists accept `status=active|confirmed|expired|cancelled`.
Product lists accept `visibility=visible|deleted|all` (default `visible`).
Reservation lists accept `product_visibility=visible|deleted|all` (default `all`).

Request bodies reject unknown fields. Names are trimmed and must be 4–256
characters; SKUs are trimmed and nonblank. Quantities are strict JSON integers,
not booleans or numeric strings, bounded by `2147483647`; available stock may be
zero and reservation quantity must be positive. Timestamps use aware UTC.

Errors use a `detail` field: `404` for missing or hidden resources, `409` for
insufficient stock, incompatible retries, ineligible transitions, active holds
blocking hard deletion, or stock-capacity conflicts; `422` for invalid input.
FastAPI validation details may be structured arrays. See OpenAPI for schemas.

### Administrative access and product deletion

Set a private `ADMIN_API_TOKEN` and send `Authorization: Bearer <token>` for
product deletion, `visibility=deleted|all`, `include_deleted=true`, or explicit
`product_visibility=deleted`. An unset/blank admin token disables these operations
with `503`; missing/incorrect credentials return `401` with a bearer challenge.
Use the deployment's HTTPS endpoint. This is one shared credential, without user
accounts or role management. **Product creation, detail edits, stock corrections,
and reservation/confirmation operations currently have no bearer requirement.**
Account for this access model when exposing the service.

Soft deletion is the default and may proceed with active holds. Repeating it
preserves `deleted_at` and returns `204`. Hidden products reject new reservations
(including creation retries), edits, and stock corrections with `404`. Existing
holds may still confirm before expiry, cancel, or expire; their history and
successful confirmation retries remain available. There is no restore operation.

Explicit `mode=hard` irreversibly erases the product and all its reservations and
confirmations atomically, overriding history retention. Any stored active hold,
including an overdue one, blocks it with `409`. Subsequent lookups return `404`;
repeating hard deletion returns `404`. Deletion itself does not adjust stock.

## Inventory and lifecycle rules

- `stock_quantity` is available stock, excluding held units. Reservation creation
  decrements it and inserts the hold in one transaction. Database locks and
  constraints prevent oversubscription and negative stock.
- Confirmation consumes held units without decrementing available stock again.
  Only an active hold with `now < expires_at` may confirm. Cancellation accepts
  any stored active hold; expiration requires `now >= expires_at`.
- Confirmation, cancellation, and expiration coordinate on the same reservation.
  Only one terminal transition succeeds. Stock returns and transitions commit
  together; confirmation has a database uniqueness constraint per reservation.
- Stock correction sets an absolute available quantity. It must leave numeric
  capacity to return all stored active holds, including overdue holds. Conflicts
  return `409` without changing inventory.
- Keys are opaque, case-sensitive, and scoped to a product: 1–256 Unicode
  characters, at most 1,024 UTF-8 bytes, with no NUL or surrounding whitespace.
  A matching retry returns the original reservation, including terminal status,
  without extending expiry. Changing the quantity for a retained key returns `409`.
- GET/list endpoints expose stored status. An overdue hold may still read `active`
  until expiration runs, but cannot confirm. Workers are required to release its
  stock automatically.

## Configuration

Settings load from process environment variables over `.env` over defaults.
Restart affected API/worker processes after changing configuration. Existing
reservation deadlines are persisted and do not change with lifetime settings.

| Variable | Default | Purpose |
| --- | --- | --- |
| `STOCKLOCK_DATABASE_URL` | Required | Async SQLAlchemy URL, `postgresql+asyncpg://...` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | See `.env.example` | Compose database initialization and internal application URL |
| `POSTGRES_PORT` | `5432` | Published database port |
| `SERVICE_HOST` / `SERVICE_PORT` | `0.0.0.0` / `8000` | Local `main.py` listener; Compose also uses the port for mapping |
| `SERVICE_RELOAD` | `false` | Local `main.py` reload |
| `SERVICE_SSL` | `false` | Public URL description only; does not configure HTTPS |
| `ADMIN_API_TOKEN` | Empty | Shared bearer token for administrative endpoints |
| `RESERVATION_LIFETIME_SECONDS` | `900` | Lifetime for new holds (15 minutes) |
| `EXPIRATION_CLEANUP_INTERVAL_SECONDS` | `60` | Expiration sweep interval |
| `EXPIRED_RESERVATION_RETENTION_SECONDS` | `2592000` | Expired history retention (30 days) |
| `CANCELLED_RESERVATION_RETENTION_SECONDS` | `2592000` | Cancelled history retention (30 days) |
| `CONFIRMATION_RETENTION_SECONDS` | `2592000` | Confirmed reservation and confirmation retention (30 days) |
| `RETENTION_CLEANUP_INTERVAL_SECONDS` | `86400` | Reservation retention sweep interval (one day) |
| `RETENTION_BATCH_SIZE` / `RETENTION_MAX_BATCHES` | `100` / `100` | Reservation retention bounds per transaction / sweep |
| `RETENTION_OPERATION_TIMEOUT_SECONDS` | `30` | Reservation retention batch timeout |
| `DELETED_PRODUCT_RETENTION_SECONDS` | `2592000` | Soft-deleted product minimum age for cleanup |
| `PRODUCT_CLEANUP_INTERVAL_SECONDS` | `86400` | Product cleanup sweep interval |
| `PRODUCT_CLEANUP_BATCH_SIZE` / `PRODUCT_CLEANUP_MAX_BATCHES` | `100` / `100` | Product cleanup bounds per transaction / sweep |
| `PRODUCT_CLEANUP_OPERATION_TIMEOUT_SECONDS` | `30` | Product cleanup batch timeout |
| `STOCKLOCK_TEST_DATABASE_URL` | Unset | Opt-in PostgreSQL test connection, exported in the shell |

Durations are whole seconds up to `2147483647`. Intervals, lifetime, batch counts,
and timeouts must be positive; batch size is 1–100. Retention durations permit
`0`, which keeps that history indefinitely or disables automatic product cleanup.
See [.env.example](.env.example) and [time policies](docs/time-policies.md).

## Workers and retention

The API and three workers are separate processes. Compose starts all of them
after migrations. Each worker runs a startup sweep and then repeats on its
configured interval. The shared `BaseWorker` handles stop signals, validates
limits, logs sweep failures, and retries after the interval; cancellation
propagates so transactions can roll back.

| Worker module under `stocklock.infrastructure.workers` | Responsibility |
| --- | --- |
| `expiration` | Transition due active holds and restore stock atomically |
| `retention` | Delete eligible terminal reservations and their confirmations atomically |
| `product_cleanup` | Remove eligible soft-deleted products only when no reservations remain |

Expiration processes up to 100 reservations per transaction, skips locked rows,
and groups stock returns by product. Failed batches roll back before individual
retries so one failed hold does not block later candidates. Operations have a
30-second timeout; skipped/failed holds are revisited on later sweeps.

Reservation retention starts at persisted UTC `finalized_at`, the actual terminal
transition time, including when an overdue hold is processed. It never purges
active holds, changes stock, or removes products. Confirmed reservations and
confirmations share a retention window and are deleted together. Locked rows are
skipped; failed/timed-out batches roll back and retry on a later sweep.

Product cleanup measures age from `deleted_at` and waits for **all** reservations
to be removed. Indefinitely retained history therefore preserves its product.
It never removes visible products, erases remaining history, or changes stock.
Explicit authenticated hard deletion is the intentional history-erasure operation.

Retention is a minimum age, not an exact deletion deadline: intervals, locks, and
backlogs may delay removal. Once history is deleted, old lookups and confirmation
retries return `404`, and its reservation keys become reusable. Increasing
retention cannot recover deleted history. Operators own exports, backups, and
retention of external logs. A retention worker with all history durations zero,
or a product cleanup worker with zero retention, exits without a DB connection.

Compose gives workers 35 seconds for graceful shutdown. Increase the relevant
`stop_grace_period` when raising operation timeouts, leaving time for rollback
and connection closure.

## Architecture and contributing

```text
main.py                         Local process entrypoint
stocklock/
  bootstrap.py                  FastAPI factory and HTTP composition
  api/v1/                       Handlers, schemas, mappers, security, error translation
  application/
    commands/                   Immutable workflow inputs
    ports/                      Unit of work, clock, health-check interfaces
    policies/                   Framework-independent lifetime and cleanup policies
    usecases/                   Workflow orchestration and transaction boundaries
  domain/
    entities/                   Product, Reservation, Confirmation
    value_objects/              Validated domain values
    services/                   Domain operations through repository ports
    ports/repositories/         Async persistence abstractions
  infrastructure/               ORM models, mappers, repositories, unit of work,
                                database clock, health checks, and worker CLIs
  project/                      Configuration and Wireup dependency composition
  shared/                       Shared primitives; sqlalchemy/ is infrastructure code
migrations/                     Alembic revisions
tests/                          Domain, application, HTTP, worker, and PostgreSQL tests
docs/                           Detailed design and operational notes
```

Read [AGENTS.md](AGENTS.md) for repository conventions. Keep HTTP handlers thin,
business rules independent of FastAPI/SQLAlchemy/Wireup, and database queries,
locking, and mappings inside infrastructure. Use cases own unit-of-work scopes;
services expect an existing transaction. Preserve asynchronous ports and UUID
conventions. Use two-space indentation, double quotes, and a 120-character line
length as configured in `ruff.toml`.

For changes, add focused domain/application tests and exercise HTTP behavior at
the boundary. Schema changes need reviewed Alembic revisions. Validate inventory
races using PostgreSQL and independent transactions: oversubscription, concurrent
confirmation, cancellation versus expiration, confirmation versus expiration,
and rollback of failed multi-step operations. Report skipped database checks.

Further reading:

- [Services and use cases](docs/services.md): entity rules, orchestration, and composition.
- [Repositories and transactions](docs/repositories.md): persistence, locking, and race tests.
- [Time policies](docs/time-policies.md): lifetime, cleanup, and retention details.
- [License](LICENSE).

## Troubleshooting

- **Connection refused:** check database health, the published port, and the URL.
  Local Python uses `localhost`; containers use `stocklock-postgres`.
- **Missing tables or columns:** run migrations before starting API and workers.
  `0002_reservation_keys` rejects incompatible existing keys for operator review;
  it never truncates keys. `0003_retention` gives existing terminal records a fresh
  retention window because their original transition times are unavailable.
- **Expired stock remains held:** start the expiration worker and inspect its logs.
  Reads show stored state; confirmation enforces deadlines independently.
- **Database tests skip:** export `STOCKLOCK_TEST_DATABASE_URL`; `make test-full`
  refuses to run without it and does not reuse the application database implicitly.
- **Admin operations return 503/401:** configure a nonblank token, restart the API,
  and provide the matching bearer credential.
- **Container API port mismatch:** keep the default `8000`, or align `.env`'s
  `PORT` and `SERVICE_PORT` as described above.
- **Reusing PostgreSQL volumes:** PostgreSQL 18 stores its cluster under the volume
  at `/var/lib/postgresql`. Migrate existing clusters before reusing a volume from
  another major version/layout. `down` preserves the volume; removing it destroys
  database data.
