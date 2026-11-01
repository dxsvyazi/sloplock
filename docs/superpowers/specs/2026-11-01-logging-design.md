# Consistent operational logging

Scope and design approved in conversation on 2026-11-01.

## Intent and acceptance criteria

Make API requests, committed inventory operations, and worker progress diagnosable
across StockLock's separate processes. Use Python standard-library logging without
adding a logging service or dependency. Preserve domain rules, HTTP status codes,
locking, transaction boundaries, and worker scheduling.

Acceptance criteria:

- The local API, container API, and three worker CLIs use consistent configurable
  logging with UTC timestamps and process roles.
- Requests have server-generated IDs, returned as X-Request-ID and included in
  request and application logs, without leaking context between concurrent tasks.
- Requests record method, matched route template, status and duration, with no
  request bodies, query strings, credentials, or raw idempotency keys.
- Mutation success events occur only after successful transaction exit. Retries
  are distinguishable from newly created reservations and confirmations.
- Worker summaries report actual committed work, failures and elapsed time;
  ordinary races and empty sweeps do not generate warnings.
- Unexpected failures retain useful diagnostic stack information without logging
  arbitrary exception messages or database parameter values.
- Existing tests pass; new tests cover correlation isolation, safe serialization,
  log duplication, worker summaries, and failure/commit ordering.

## Approaches

The user selected shared configuration, request logging, committed mutation events,
worker summaries, tests and documentation. The smaller alternative deferred mutation
events; it was rejected because those events explain inventory changes. External
collectors and a new logging framework add operational work without being needed
for the selected scope.

## Configuration and ownership

Add validated LOG_LEVEL (DEBUG, INFO, WARNING, ERROR, CRITICAL; default INFO) and
LOG_FORMAT (text or json; default text) settings. Deployments opt into JSON through
environment configuration. Configure logging at process startup, never when importing
business modules. Uvicorn configuration must also work with reload subprocesses and
the existing factory entrypoint. Keep existing listener/reload behavior.

Use module loggers, a shared dictConfig builder, and console handlers. One handler
path owns each record; do not duplicate records through propagation. Keep dependency
verbosity separately restrained, disable Uvicorn access logging in favor of the
application request summary, and retain Uvicorn server/startup/shutdown logs.
Workers replace their separate basicConfig calls with this shared setup.

Configuration belongs at the project/composition boundary; formatters and context
helpers belong outside the domain. Application use cases may use standard logging
directly. No logger port, domain logging, database schema change or audit table.

Both formats include UTC timestamp, level, logger, process role and event. Serialize
an explicit set of supported structured fields, including resource UUIDs, quantities,
outcomes, duration, and request/sweep IDs. Never serialize arbitrary objects or all
LogRecord extras. Text formatting escapes control characters; JSON uses proper
encoding and one physical line per event. Missing context is safe for startup logs.

## HTTP requests and failures

Use ASGI middleware with ContextVar context, reset in finally. Generate a fresh UUID
for each request rather than trusting an incoming correlation header. Return the
same ID in X-Request-ID; make it readable to browser callers through CORS. Record
one completion summary, including requests rejected by HTTP/domain validation and
unhandled failures. Use the matched route template, or a fixed unmatched marker,
instead of logging arbitrary URL paths. Measure durations with a monotonic clock.

Successful health checks log at DEBUG; failed health checks remain visible.
Normal HTTP/business rejection summaries use INFO and a bounded reason code where
available. Record rejected administrative authentication at WARNING without tokens
or fabricated actor identities; current authentication remains limited to deletion
and administrative visibility.

Uvicorn remains the sole owner of tracebacks for unhandled HTTP exceptions. Request
middleware records the failure summary and re-raises, without its own traceback.
Workers own tracebacks for failures they catch and recover from. A shared safe
exception formatter records exception types and stack frame locations, omitting
arbitrary exception messages, source lines and local values, including chained
exception messages. This trades some detail for avoiding secret-bearing errors.
Do not log full commands, settings, SQL parameters, bodies, headers or URLs.

## Committed application events

Refactor mutation use cases to capture results inside the existing transaction,
then log and return after context exit. Do not add transactions or move database
operations outside their existing unit of work. Failed commits emit no success.

Record product creation, changed detail field names (not values), stock correction
with previous/new available stock, and deletion mode. Repeated soft deletion is
identified as reused rather than a new deletion. Record reservation creation,
cancellation, explicit expiration, and confirmation with relevant resource IDs and
quantity. Reservation and confirmation retries record reused outcomes without
raw idempotency keys or additional stock effects. Reads use the HTTP summary only.

Bulk cleanup/expiration and best-effort fallback produce worker counts rather than
one application INFO event per item. Count only returned successful transitions;
candidates already processed by another transaction count as skipped. Logs remain
best effort operational evidence: a crash after commit can lose a success record.
Guaranteed auditing/outbox delivery is outside scope.

## Workers and operations

Give each sweep a fresh ID. Include role, processed/changed/skipped/failed counts
where meaningful, duration, and completion outcome. Retention and product cleanup
report deleted counts; expiration reports transitioned holds and fallback failures.
Nonempty or failed sweeps are visible at INFO/ERROR, empty successes at DEBUG.
Preserve existing fallback, cursor, stop, cancellation and timeout behavior.
Log safe startup/shutdown events and disabled-cleanup decisions without settings
dumps. Summaries on partial failure must not claim complete success.

Write to stdout/stderr and document container collection/rotation/retention as an
operator responsibility. No application file rotation, log shipping, metrics,
tracing, new admin authentication, or durable audit guarantee in this feature.

## Validation and existing edits

Test both output formats and sensitive-data exclusion, concurrent request isolation,
correlation headers on success and errors, health-check suppression, and handler
duplication. Test committed outcomes and retries with application doubles, including
an exception raised on transaction exit. Exercise worker success, fallback, empty,
partial failure and cancellation paths. Reuse PostgreSQL lifecycle/race tests for
transaction regressions where an explicit STOCKLOCK_TEST_DATABASE_URL is available.

Run uv run ruff check ., uv run pytest -q, and git diff --check. Report skipped
PostgreSQL validation and obtain any required workflow exception before committing.
Update README and configuration examples with settings and safe example events.

The existing unstaged hide_parameters=True edit in stocklock/project/container.py
belongs to the user. Preserve it and exclude it from the feature commit. Do not
modify that file as part of this feature. Branch from current main after design
approval, implement and validate, then create the already-authorized local commit.
No push, merge or pull request is included.

Builder choices: internal helper/file names, exact event naming, field allowlist
details, and test organization may be settled during implementation within these
constraints.
