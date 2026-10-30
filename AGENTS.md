# StockLock agent guide

## Project scope

StockLock is a monolithic inventory and time-limited reservation service with a
hexagonal architecture. Keep business rules independent of HTTP, persistence,
and dependency injection frameworks.

The repository implements product management, atomic reservations, confirmations,
expiration, historical retention, soft/hard deletion, product cleanup, and a
database readiness endpoint. Domain entities, use cases, HTTP adapters,
PostgreSQL repositories, migrations, and worker CLIs have test coverage. Verify
the relevant implementation and checks rather than assuming a module is scaffolding.
See README.md for setup, configuration, command equivalents, and current API behavior.

## Functional requirements

### Products and inventory

- Create a product with an initial stock quantity.
- List products with their current available stock.
- Retrieve product details and available stock.
- Adjust product details.
- Adjust available stock for administrative inventory corrections.
- Retrieve reservations associated with a product.
- Administrators may soft-delete products or explicitly hard-delete them with
  cascading reservation and confirmation history erasure. Hard deletion rejects
  any stored active reservation, including overdue holds. Soft deletion is allowed
  with active reservations: it blocks new reservations and edits while existing
  holds may confirm before expiry, cancel, or expire normally. Lifecycle stock
  returns remain atomic. Soft deletion preserves history and confirmation retries.
- Product lists hide deleted products by default; administrative visibility
  filters and detail inclusion require bearer authentication. Reservation history
  remains accessible after soft deletion; global lists default to all products.

### Reservations

- Reserve a positive quantity of a product for a limited period of time.
- Retrieve a reservation's status, quantity, and expiration time.
- Cancel an active reservation and return its reserved units to available stock.
- List all reservations, optionally filtered by status.
- List a product's reservations, optionally filtered by status.

### Confirmations

- Confirm an active reservation before it expires.
- Retrieve the confirmation result when one exists.
- Return the existing result for repeated successful confirmation requests.
  This guarantee lasts while the reservation and confirmation are retained;
  after retention cleanup, lookups and confirmation retries return not found.

### Historical retention

- Keep terminal reservations and their confirmations for 30 days by default,
  measured from the persisted UTC terminal transition time (`finalized_at`).
- Configure retention separately for expired, cancelled, and confirmed states;
  zero means keep that state's history indefinitely.
- Delete eligible records in bounded transactions through a separate retention
  worker. Delete confirmations with their associated reservations atomically.
- Reservation retention never purges active reservations or products and never
  changes stock. Overdue active reservations must first be expired normally.
- A separate product cleanup worker may remove soft-deleted products after their
  configured deletion retention period only when no reservations remain. Zero
  disables product cleanup. It never removes visible products or changes stock.
- Explicit authenticated hard deletion intentionally overrides terminal-history
  retention and erases associated reservations and confirmations atomically.
- Idempotency keys become reusable after their reservation is deleted. Operators
  own historical exports and retention of externally collected logs.

## Inventory and transaction invariants

- Product reservation must be atomic: decrement available stock and create the
  reservation within one database transaction, or persist neither change.
- Available stock must never be negative. Competing transactions must not reserve
  more units than are available. Use database-level concurrency control, such as
  row locks or a conditional atomic update; a separate read followed by an
  unprotected write is insufficient.
- Initial stock must be nonnegative; reservation quantities must be positive.
  Administrative stock corrections must preserve the nonnegative stock invariant
  and participate in the same concurrency controls as reservations.
- Reservation states are `active`, `confirmed`, `expired`, and `cancelled`, as
  defined in `stocklock/shared/enums.py`. Terminal states must not return to active.
- Only an active, unexpired reservation may be confirmed. Treat a reservation as
  expired when the current time is greater than or equal to `expires_at`, even if
  an expiration cleanup process has not yet changed its stored status.
- Reserving removes units from available stock. Confirmation consumes the held
  units without decrementing available stock a second time.
- Repeated or concurrent confirmations for the same reservation must not create
  duplicate purchases or confirmations, or consume stock again. Enforce one
  confirmation per reservation in the database as well as in application logic.
- Cancellation and expiration may restore a reservation's units only once.
  Transition the reservation state and restore stock in the same transaction,
  conditional on the reservation still being active.
- Confirmation, cancellation, and expiration must coordinate on the same
  reservation so only one terminal transition succeeds under concurrency.
- Use timezone-aware UTC timestamps consistently for expiration comparisons and
  persistence. Define transaction boundaries in the application layer and provide
  database transaction support through infrastructure adapters.

## HTTP API contract

Paths below are relative to the implemented `/api/v1` prefix. Interactive docs
are at `/api/docs`; OpenAPI is at `/openapi.json`. Keep these consistent with the
router and application factory.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/healthcheck` | Database readiness: 200 with true, or 503; no caching. |
| POST | `/products` | Create a product with an initial stock quantity. |
| GET | `/products` | List products and their current available stock. |
| GET | `/products/{product_id}` | Retrieve product details and available stock; admins may include deleted products. |
| DELETE | `/products/{product_id}` | Admin deletion with `mode=soft` (default) or explicit `mode=hard`; active holds block hard deletion only. |
| PATCH | `/products/{product_id}` | Patch name and/or SKU; reject empty patches and explicit null. |
| PATCH | `/products/{product_id}/stock` | Adjust available stock for an administrative inventory correction. |
| GET | `/products/{product_id}/reservations` | List a product's reservations, optionally filtered by status. |
| POST | `/products/{product_id}/reservations` | Atomically reserve a requested quantity for a limited time. |
| GET | `/reservations/{reservation_id}` | Retrieve status, quantity, and expiration time. |
| POST | `/reservations/{reservation_id}/cancel` | Cancel an active reservation and return its stock. |
| GET | `/reservations` | List reservations, optionally filtered by status. |
| POST | `/reservations/{reservation_id}/expire` | Expire a due active hold and return its stock atomically. |
| POST | `/reservations/{reservation_id}/confirm` | Confirm an active reservation before expiration. |
| GET | `/reservations/{reservation_id}/confirmation` | Retrieve the confirmation result, if available. |

Current API decisions:

- Stock correction sets an absolute `stock_quantity`, not a delta. Reject a
  correction when available stock plus all stored active holds exceeds the stock
  integer limit; overdue active holds still require capacity for stock returns.
- Reservation creation accepts `quantity` and a product-scoped, case-sensitive
  `key`. Matching quantity retries return the original reservation without
  extending its deadline; incompatible retries conflict. Preserve the key rules
  documented in README.md and enforced by domain validation.
- Lifetime is server-configured by `RESERVATION_LIFETIME_SECONDS` (default 900).
  Database UTC wall time is authoritative. Reads expose stored lifecycle status;
  confirmation must independently enforce expiry before cleanup.
- Lists use ascending UUID cursors (`start_id`) and `limit` (default 50, max 100).
  Reservation lists accept status and product visibility filters.
- Bearer authentication currently guards deletion and administrative visibility
  only. Product creation, detail edits, stock corrections, and reservation and
  confirmation operations do not require it. Do not imply broader protection.
- Missing/hidden resources return 404, business conflicts 409, validation errors
  422, invalid admin credentials 401, and disabled admin operations 503.

## Architecture and current folder structure

```text
main.py                              # Process entry point
stocklock/
  bootstrap.py                       # FastAPI application factory / composition root
  api/v1/
    router.py                        # API routing
    handlers/                        # HTTP inbound adapters
    schemas/                         # Request and response schemas
  application/
    commands/                        # Application input models
    usecases/                        # Workflow orchestration and transaction boundaries
    ports/                           # Unit of work, clock, health-check interfaces
    policies/                        # Lifetime and cleanup policies
  domain/
    entities/                        # Product, Reservation, Confirmation
    services/                        # Domain rules spanning entities
    value_objects/                   # Validated domain values
    ports/repositories/              # Repository abstractions
  infrastructure/
    models/                          # SQLAlchemy ORM models
    repositories/                    # Persistence adapters implementing domain ports
    workers/                         # Separate expiration, retention, product cleanup CLIs
  project/configs/                   # Service configuration
  shared/                            # Shared primitives, enums, and utilities
    sqlalchemy/                      # Persistence-specific shared helpers
migrations/                          # Alembic migration environment and revisions
```

- Follow hexagonal architecture: HTTP adapters invoke use cases; use cases depend
  on domain entities and ports; infrastructure implements those ports.
- Apply the Repository pattern. Keep SQLAlchemy queries, sessions, locking, and
  ORM-to-domain mapping inside persistence adapters.
- Use application use cases to coordinate repositories and domain operations.
  Keep HTTP handlers thin and translate application outcomes into HTTP responses.
- Apply DDD: express stock, reservation lifecycle, and confirmation rules in domain
  language. Keep domain entities separate from ORM models and transport schemas.
- Apply SOLID principles, especially single responsibility and dependency
  inversion. Extend existing abstractions when needed to preserve atomic workflows.
- Keep FastAPI, SQLAlchemy, and wireup imports out of the domain. Persistence
  helpers under `shared/sqlalchemy/` remain infrastructure concerns despite their
  shared location.
- Configure dependency injection at the composition boundary using wireup; avoid
  service location inside business logic.

## Technology and development conventions

- Python 3.13 or newer; FastAPI; PostgreSQL; SQLAlchemy; wireup.
- Existing supporting dependencies include asyncpg, Alembic, pydantic-settings,
  Uvicorn, and uuid6. Treat `pyproject.toml` and `uv.lock` as the dependency sources
  of truth. The stack may grow as the project requires.
- Preserve asynchronous repository interfaces and the existing UUID identifier
  conventions.
- Follow `ruff.toml`: two-space indentation, double quotes, and a 120-character
  line length.
- Add Alembic migrations for persistence schema changes, including constraints
  needed for nonnegative stock and unique reservation confirmations.
- Validate stock and reservation races against PostgreSQL using independent
  transactions. Cover oversubscription, repeated/concurrent confirmation,
  cancellation versus expiration, confirmation versus expiration, and rollback
  when a multi-step operation fails.
- Keep domain rule tests independent of web and database frameworks. Exercise HTTP
  validation and response behavior at the API boundary when implementing endpoints.
- Keep README raw commands and makefile targets equivalent when changing developer
  workflows. `make env` must preserve existing local configuration; the default
  target must be help. Preserve existing target aliases when practical.
- Run `uv run ruff check .` and `uv run pytest -q` for relevant changes. PostgreSQL
  tests require an exported `STOCKLOCK_TEST_DATABASE_URL` with schema creation
  permission; they use isolated schemas and skip without it. `make test-full`
  requires this explicit URL and must not implicitly reuse application credentials.
- The API does not start workers. Compose starts all three after migrations.
  Local `main.py` and container `bootstrap.sh` have different listener/reload
  settings; document the actual entrypoint behavior when changing either.
- Report the checks actually run and any relevant gaps, including skipped races.
- Keep credentials and local environment secrets out of documentation and commits.
