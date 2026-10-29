# Time policies

`stocklock/project/configs/time_policy.py` defines `TimePolicySettings`. Settings
load when `create_persistence_container` is called, so importing modules does not
capture environment values. Explicit constructor values override environment
variables, which override `.env` values, which override defaults.

All durations are **whole seconds**, using ASCII digits. Lifetime and sweep intervals
must be in `1..2147483647`; retention values allow `0..2147483647`. Negative,
fractional, boolean, empty, and out-of-range values fail configuration validation.
The upper bound keeps durations representable and limits them to about 68 years.
Retention `0` means keep indefinitely; the corresponding Python property is `None`.

| Environment variable | Default | Typed property | Purpose |
| --- | --- | --- | --- |
| `RESERVATION_LIFETIME_SECONDS` | `900` | `reservation_lifetime: timedelta` | Lifetime of new reservations |
| `EXPIRATION_CLEANUP_INTERVAL_SECONDS` | `60` | `expiration_cleanup_interval: timedelta` | Expiration worker sweep interval |
| `RETENTION_CLEANUP_INTERVAL_SECONDS` | `86400` | `retention_cleanup_interval: timedelta` | Retention worker sweep interval |
| `EXPIRED_RESERVATION_RETENTION_SECONDS` | `2592000` | `expired_reservation_retention: timedelta \| None` | Retention after finalization as expired |
| `CANCELLED_RESERVATION_RETENTION_SECONDS` | `2592000` | `cancelled_reservation_retention: timedelta \| None` | Retention after finalization as cancelled |
| `CONFIRMATION_RETENTION_SECONDS` | `2592000` | `confirmation_retention: timedelta \| None` | Retention of confirmations and associated confirmed reservations after finalization |
| `RETENTION_BATCH_SIZE` | `100` | `RETENTION_BATCH_SIZE: int` | Reservations per cleanup transaction, 1–100 |
| `RETENTION_MAX_BATCHES` | `100` | `RETENTION_MAX_BATCHES: int` | Maximum cleanup transactions per sweep |
| `RETENTION_OPERATION_TIMEOUT_SECONDS` | `30` | `retention_operation_timeout: timedelta` | Per-batch timeout |

For example, a two-minute hold:

```dotenv
RESERVATION_LIFETIME_SECONDS=120
```

Or provide explicit settings at the composition boundary:

```python
from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.project.persistence import create_persistence_container

settings = TimePolicySettings(RESERVATION_LIFETIME_SECONDS=120)
container = create_persistence_container(session_maker, time_settings=settings)
```

The HTTP request and application command contain only product ID (from the URL),
quantity, and idempotency key. The application receives a framework-independent
`ReservationTimePolicy`. Inside its transaction, it locks the product, checks for
a retry, holds stock, and reads PostgreSQL `clock_timestamp()`. This reading is
both `created_at` and the base for calculating `expires_at`. A failed calculation
or insert rolls back the stock hold. Direct callers construct a validated `Reservation` with explicit creation and
expiration timestamps, then pass it to `ReservationService.create(reservation)`;
those callers own lifetime policy and must hold stock in the same transaction.

Time-dependent use cases receive `IClock` from `application/ports/clock.py`.
The scoped `PostgresClock` adapter uses the same `SessionManager` as repositories
and the unit of work, and requires an active transaction. Its `now()` returns
timezone-aware UTC wall time, including time spent waiting for locks. Creation,
confirmation, and individual expiration read the clock after locking; tests can
inject a controllable clock. Repository SQL still rechecks deadlines when saving
transitions and selecting or expiring due reservations.

Changing settings affects new containers and new holds. Existing deadlines are
persisted and never recomputed. Matching idempotent retries return the original
reservation, including its original deadline and terminal status, without holding
more stock. Confirmation still requires `now < expires_at`; expiration applies at
`now >= expires_at` even before a future sweep marks a reservation expired.

**The expiration worker uses `EXPIRATION_CLEANUP_INTERVAL_SECONDS`.**
Run `python -m stocklock.infrastructure.workers.expiration` alongside the API;
Compose starts this worker after migrations. The API process alone does not
start background jobs. Stored statuses and stock update eventually when swept.
The worker processes bounded pages of up to 100 reservations in one transaction
per page. It skips locked reservations, transitions due active holds in bulk,
and restores their quantities once per product in UUID order. Failed pages roll
back and retry individually; failed holds are logged and revisited while later
candidates continue. SIGTERM/SIGINT stop processing between batches (or between
individual fallback attempts) and close dependencies.

Run `python -m stocklock.infrastructure.workers.retention` separately from the
API. Compose starts it after migrations. It sweeps immediately on startup and
then at `RETENTION_CLEANUP_INTERVAL_SECONDS` intervals. Every batch selects only
terminal rows whose UTC `finalized_at` is at or before that status's retention
cutoff, locks them with `FOR UPDATE SKIP LOCKED`, and deletes their confirmations
and reservations in one application-owned transaction. Cleanup never changes
stock, removes products, or removes active holds, even overdue ones. Normal
expiration must first release those holds and record their terminal transition.

`finalized_at` is persistence metadata written by the database during each
successful terminal transition, including bulk expiration. Repeated or failed
transitions never reset it. Migration `0003_retention` sets it to migration time
for existing terminal records, granting them a full retention window. Existing
active records keep a null timestamp. Apply the migration before starting the
updated API and workers; older processes cannot write the required metadata.

The worker bounds each sweep by `RETENTION_MAX_BATCHES` and each transaction by
`RETENTION_BATCH_SIZE` (1–100). Batch count and timeout must be positive whole
integers no greater than 2147483647. Failed or timed-out batches roll back; the
next sweep retries them. Locked records are skipped and revisited later. Sweep
intervals and backlogs can extend actual retention beyond the configured minimum.
When all three retention durations are zero, the CLI exits successfully without
connecting to PostgreSQL; Compose uses restart-on-failure to leave it stopped.
SIGTERM/SIGINT prevent new batches and let the current operation finish or time
out. Compose allows 35 seconds for shutdown; increase this when raising the batch
timeout to allow rollback and resource closure.

Confirmation retrieval and idempotent retries remain available while records
exist. After cleanup, old reservation lookups and confirmation requests return
HTTP 404, and deleted reservation keys may be reused for new holds. Confirmations
and their confirmed reservations share one retention window and are deleted
together. Operators can export or replicate history before deletion and control
external log retention. Increasing retention does not recover deleted history.

No configurable grace period is introduced: confirmation at or after the deadline
would conflict with the service's expiration invariant. See `.env.example` for all
available settings without credentials.

Worker database operations have a 30-second timeout. A timed-out batch rolls back
before individual fallback begins. Skipped or failed holds are revisited on a
later sweep. Compose allows 35 seconds for graceful worker shutdown.

## Soft-deleted product retention

`DELETED_PRODUCT_RETENTION_SECONDS` defaults to 2592000 (30 days) measured from the
persisted UTC `deleted_at`. Zero disables automatic product removal. The separate
`product_cleanup` worker uses `PRODUCT_CLEANUP_INTERVAL_SECONDS` (86400),
`PRODUCT_CLEANUP_BATCH_SIZE` (100, maximum 100), `PRODUCT_CLEANUP_MAX_BATCHES` (100),
and `PRODUCT_CLEANUP_OPERATION_TIMEOUT_SECONDS` (30). All intervals/limits must be
positive whole integers; the retention duration alone permits zero.

Product cleanup waits until no reservations remain, regardless of age. Existing
reservation retention remains in effect for visible and deleted products alike;
indefinitely retained history prevents automatic product removal. Explicit admin
hard deletion is the intentional exception and erases terminal history immediately.
Both administrative deletion modes reject stored active holds, including overdue
holds; product cleanup never expires or cancels holds implicitly.

All three workers derive from `BaseWorker`, which validates common limits,
declares `_run_once`, and provides stop-aware `run_once` and `run`. Failed sweeps
are logged with the subclass's `exception_message` and retried after the configured
interval. Cancellation propagates. Each worker owns its process, signals,
container, timeout, and bounded batching; disabling one does not disable another.
