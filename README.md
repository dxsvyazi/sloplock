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

Run each worker in a separate process:

```sh
uv run python -m stocklock.infrastructure.workers.expiration
uv run python -m stocklock.infrastructure.workers.retention
uv run python -m stocklock.infrastructure.workers.product_cleanup
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
API, expiration worker, reservation retention worker, and product cleanup worker. Both `dev` and `prod` image targets
install locked runtime dependencies. PostgreSQL is pinned to version 18 and stores its cluster
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

Terminal reservations and their confirmations are retained for **30 days** by
default. Run the retention worker alongside the API; Compose starts it after
migrations. It deletes history in atomic batches without changing stock or
removing active reservations or products. Retention starts at the stored UTC
terminal transition time, including when an overdue hold is actually expired.
Migration `0003_retention` gives existing terminal records a fresh retention
window because their original transition times are unavailable.

Set `EXPIRED_RESERVATION_RETENTION_SECONDS`,
`CANCELLED_RESERVATION_RETENTION_SECONDS`, and `CONFIRMATION_RETENTION_SECONDS`
to configure each terminal state; `0` keeps that state's history indefinitely.
Confirmed reservations and confirmations are deleted together. Retention is a
minimum age for eligibility, not an exact deletion deadline: sweep scheduling,
backlogs, and skipped locks can delay removal. Increasing retention cannot
restore records already deleted.

Reservation retries and confirmation retrieval work while the original records
exist. After deletion, lookups and confirmation retries return HTTP 404, and the
reservation's idempotency key can create a new hold. Operators own historical
exports, replication, backups, and retention for externally collected logs.

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

The expiration worker processes up to 100 reservations per transaction. It skips
locked reservations and returns stock once per affected product; transitions and
stock returns commit together. Failed batches roll back and retry individually
so one failed hold does not prevent other candidates from expiring. Skipped or
failed holds are revisited on later sweeps. Database operations have a 30-second
timeout. Compose allows 35 seconds for graceful worker shutdown.

The retention worker runs immediately on startup, then every 86,400 seconds by
default. Each sweep deletes at most `RETENTION_MAX_BATCHES` (default 100) batches
of `RETENTION_BATCH_SIZE` (default 100, maximum 100). Its per-batch timeout is
`RETENTION_OPERATION_TIMEOUT_SECONDS` (default 30). Locked rows are skipped and
revisited later; failed or timed-out batches roll back and retry on a later sweep.
Set `RETENTION_CLEANUP_INTERVAL_SECONDS` to change the sweep interval. If all
three retention settings are zero, the CLI exits successfully without connecting
to the database. Increase Compose's retention `stop_grace_period` when increasing
the operation timeout; leave time for rollback and connection shutdown.

## Administrative product deletion

Configure `ADMIN_API_TOKEN` with a private bearer token and send it as
`Authorization: Bearer <token>`. Administrative deletion and inspection of hidden
products are disabled (HTTP 503) when the token is unset or blank; missing or
incorrect credentials return 401 with a bearer challenge. Use the deployment's
HTTPS endpoint for administrative requests. This is a shared administrator
credential, with no user accounts or role management.

`DELETE /api/v1/products/{product_id}` soft-deletes by default. Add `?mode=hard`
for explicit, irreversible erasure of the product and its reservations and
confirmations, regardless of their retention settings. Both modes reject any
stored active reservations with HTTP 409, including overdue holds awaiting normal
expiration. Successful deletion returns an empty HTTP 204. Unknown products return
404. Repeating soft deletion preserves its timestamp and returns 204; repeating
hard deletion returns 404.

Soft-deleted products cannot be edited, have stock corrected, or receive new
reservations (including reservation-creation retries). Those operations and normal
product detail requests return 404. Reservation and confirmation history remains
accessible, and successful confirmation retries still return the original result.
Hard deletion makes all those historical lookups and confirmation retries return
404. Deletion does not cancel reservations or adjust stock.

Product lists default to `visibility=visible`; administrators can select `deleted`
or `all`. Administrators can inspect a deleted product using
`GET /api/v1/products/{product_id}?include_deleted=true`. Product responses include
nullable `deleted_at`. Reservation lists default to `product_visibility=all`,
preserving historical results, and support `visible` or `deleted` alongside status
filtering and pagination. Explicit `product_visibility=deleted` requires admin
credentials. A product's reservation list remains available after soft deletion.
There is no restore operation.

Run product garbage collection separately:

```sh
uv run python -m stocklock.infrastructure.workers.product_cleanup
```

Compose starts this worker after migrations. `DELETED_PRODUCT_RETENTION_SECONDS`
defaults to 2592000 (30 days) from `deleted_at`; `0` keeps soft-deleted products
indefinitely. Cleanup removes only eligible soft-deleted products **without any
remaining reservations**. Existing reservation retention policies still apply;
indefinitely retained history also preserves its product. Visible products are
never removed automatically. Product cleanup does not erase history or change
stock, and can run independently of reservation retention.

`PRODUCT_CLEANUP_INTERVAL_SECONDS` defaults to 86400, `PRODUCT_CLEANUP_BATCH_SIZE`
to 100 (maximum 100), `PRODUCT_CLEANUP_MAX_BATCHES` to 100, and
`PRODUCT_CLEANUP_OPERATION_TIMEOUT_SECONDS` to 30. Each sweep is bounded, skips
locked products, and retries failures on a later sweep. A disabled product worker
exits successfully without connecting to PostgreSQL. Increase its Compose
`stop_grace_period` if increasing the operation timeout.

Expiration, reservation retention, and product cleanup share a `BaseWorker` with
common limit validation and a stop-aware `run` loop. Each implements `_run_once`
and declares an `exception_message` used for failure logging. `run_once` remains
available for one sweep and propagates failures; `run` logs failures and retries
after its interval. Task cancellation propagates for transaction rollback.
