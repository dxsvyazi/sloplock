# Time policies

`stocklock/project/configs/time_policy.py` defines `TimePolicySettings`. Settings
load when `create_persistence_container` is called, so importing modules does not
capture environment values. Explicit constructor values override environment
variables, which override `.env` values, which override defaults.

All values are **whole seconds**, using ASCII digits. Lifetime and sweep intervals
must be in `1..2147483647`; retention values allow `0..2147483647`. Negative,
fractional, boolean, empty, and out-of-range values fail configuration validation.
The upper bound keeps durations representable and limits them to about 68 years.
Retention `0` means keep indefinitely; the corresponding Python property is `None`.

| Environment variable | Default | Typed property | Purpose |
| --- | --- | --- | --- |
| `RESERVATION_LIFETIME_SECONDS` | `900` | `reservation_lifetime: timedelta` | Lifetime of new reservations |
| `EXPIRATION_CLEANUP_INTERVAL_SECONDS` | `60` | `expiration_cleanup_interval: timedelta` | Expiration worker sweep interval |
| `RETENTION_CLEANUP_INTERVAL_SECONDS` | `86400` | `retention_cleanup_interval: timedelta` | Future retention sweep interval |
| `EXPIRED_RESERVATION_RETENTION_SECONDS` | `0` | `expired_reservation_retention: timedelta \| None` | Future retention after expiration |
| `CANCELLED_RESERVATION_RETENTION_SECONDS` | `0` | `cancelled_reservation_retention: timedelta \| None` | Future retention after cancellation |
| `CONFIRMATION_RETENTION_SECONDS` | `0` | `confirmation_retention: timedelta \| None` | Future retention of confirmations and associated confirmed reservations |

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

Changing settings affects new containers and new holds. Existing deadlines are
persisted and never recomputed. Matching idempotent retries return the original
reservation, including its original deadline and terminal status, without holding
more stock. Confirmation still requires `now < expires_at`; expiration applies at
`now >= expires_at` even before a future sweep marks a reservation expired.

**The expiration worker uses `EXPIRATION_CLEANUP_INTERVAL_SECONDS`.**
Run `python -m stocklock.infrastructure.workers.expiration` alongside the API;
Compose starts this worker after migrations. The API process alone does not
start background jobs. Stored statuses and stock update eventually when swept.
The worker processes bounded pages and individual transactions; failed holds
are logged and revisited, while later candidates continue. SIGTERM/SIGINT stop
processing between holds and close dependencies.

Retention settings remain configuration for future workers and do not delete records.
The current confirmation retry promise is unchanged, including when finite
retention is configured. A future worker needs a separate deletion contract,
terminal transition timestamps, and an explicit decision about the confirmation
and reservation idempotency windows. Active holds must never be purged, and
confirmation records must be handled with their associated confirmed reservations.

No configurable grace period is introduced: confirmation at or after the deadline
would conflict with the service's expiration invariant. See `.env.example` for all
available settings without credentials.

Worker database operations have a 30-second timeout. A locked or failed hold
rolls back and is revisited on a later sweep; later candidates continue. Compose
allows 35 seconds for graceful worker shutdown.
