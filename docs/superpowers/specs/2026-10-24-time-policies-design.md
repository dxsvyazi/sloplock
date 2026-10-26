# Environment-driven time policies

The reservation HTTP request supplies quantity and an idempotency key. The application
owns expiration and derives it from authoritative database UTC time after acquiring
the product lock. Matching retries keep their original timestamps even when settings
change. Stock and reservation creation remain in one transaction.

Add `TimePolicySettings` under `stocklock/project/configs`, following the existing
Pydantic environment/dotenv configuration. Settings are loaded at container creation,
not module import. Inject an immutable, framework-independent reservation policy into
the use case through Wireup. Domain services accept the creation instant explicitly
so creation and expiration use one clock reading; their existing direct-call clock
behavior remains available.

## Approaches

Client-supplied deadlines would change the HTTP contract and let callers control hold
length. Server policy is the chosen direction from the conversation. Computing the
deadline in the HTTP mapper would start the hold before product-lock waits; computing
it in the transaction after locking preserves the configured lifetime.

## Settings and scope

All settings use whole seconds in `0..2147483647`; lifetime and worker intervals
must be strictly positive. This bound keeps conversion to timedelta safe.

| Environment variable | Default | Meaning |
| --- | --- | --- |
| RESERVATION_LIFETIME_SECONDS | 900 | New hold lifetime |
| EXPIRATION_CLEANUP_INTERVAL_SECONDS | 60 | Future expiration sweep cadence |
| RETENTION_CLEANUP_INTERVAL_SECONDS | 86400 | Future retention sweep cadence |
| EXPIRED_RESERVATION_RETENTION_SECONDS | 0 | Future expired reservation retention |
| CANCELLED_RESERVATION_RETENTION_SECONDS | 0 | Future cancelled reservation retention |
| CONFIRMATION_RETENTION_SECONDS | 0 | Future confirmation and associated confirmed reservation retention |

Zero retention means keep indefinitely. Worker settings are configuration only,
as explicitly requested; no scheduler, deletion, or finite retry window is implemented.
Future retention workers need terminal timestamps and an explicit retry/deletion
contract before deleting anything. Existing terminal transition boundaries remain
unchanged. No database schema changes are needed.

Default values and field names are implementation choices. Environment values override
dotenv values. Invalid settings fail at composition. New and changed production
interfaces and test helpers receive explicit annotations.

Verify settings parsing, bounds, dotenv precedence, UTC timestamps, configured lifetime,
lock-wait timing, retries under changed policy, rollback, DI, and existing PostgreSQL
race tests. Report unrelated baseline failures and unavailable database checks.
