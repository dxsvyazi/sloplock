# Configurable retention and batched cleanup

## Intent and scope

StockLock is a self-hosted locking service. Operators own historical exports and
external log storage. Keep terminal reservation history for a configurable period,
then delete it through a separately launched cleanup worker. Preserve hexagonal
architecture, existing stock invariants, asynchronous ports, and UUID identifiers.

Products and active reservations are never retention candidates. Retention cleanup
does not expire reservations or change stock. Partitioning, reservation lifetime
limits, ETL, and external log rotation are outside this change.

## Approaches

The user selected bounded transactional deletion. It preserves current primary
keys, idempotency constraints, and confirmation relationships while keeping each
transaction small. Monthly partition dropping offers cheaper bulk removal but
requires redesigning uniqueness and foreign keys and makes retention coarser.
Keeping all records indefinitely remains available through configuration.

## Retention contract

Reuse the existing per-status retention settings for expired reservations,
cancelled reservations, and confirmations. Set each default to 2,592,000 seconds
(30 days); preserve zero as unlimited retention. Confirmation retention controls
the confirmed reservation and its confirmation together.

Measure retention from a timezone-aware UTC finalized_at value recorded by the
database in the same transaction as each successful terminal transition,
including bulk expiration. Keep finalized_at as persistence lifecycle metadata;
domain entities and HTTP responses need no new field. Failed or repeated
transitions do not reset the timestamp. A database constraint requires active
rows to have no finalization timestamp and terminal rows to have one.

An Alembic migration adds the timestamp and an index supporting terminal cleanup.
For existing terminal rows, use the migration timestamp because their actual
transition times are unavailable. This deliberately grants a full retention
window after migration. Existing active rows keep a null timestamp.

Records become eligible when finalized_at is at or before the configured cutoff.
Actual deletion happens on a subsequent worker sweep. Historical lookups and
confirmation retries work while their records exist; after deletion they return
the existing not-found response. Deleted reservation keys may be reused. Document
this finite retention contract in the README and agent guide.

## Application and persistence

Add a retention policy and cleanup use case. The use case owns one transaction
per batch and obtains the current time through the existing clock port. Extend
the asynchronous reservation repository with a bounded cleanup operation;
SQLAlchemy statements and locking stay inside the persistence adapter.

Select only eligible terminal reservations, ordered deterministically, with
FOR UPDATE SKIP LOCKED and a batch limit. Delete associated confirmations first,
then their reservations, in the same transaction. Preserve existing foreign-key
and uniqueness constraints. Return the number of deleted reservations. Concurrent
workers skip each other's locks; failed deletion rolls back the entire batch.
Confirmation workflows and cleanup both acquire reservation locks first.

## Worker and configuration

Launch a standalone retention worker using python -m
stocklock.infrastructure.workers.retention, following the expiration worker's
container scopes, signal handling, shutdown, retry logging, and operation timeout.
Reuse RETENTION_CLEANUP_INTERVAL_SECONDS (default one day). Add configurable
retention batch size (default 100), maximum batches per sweep (default 100), and
operation timeout (default 30 seconds), validating positive values and the existing
page-size limit. A fully disabled retention policy performs no cleanup queries.

Each sweep processes at most the configured batch count. Empty or short batches
end the sweep; skipped locked rows are revisited on a later sweep. Stop requests
prevent starting further batches, and cancellation releases open transactions.
Log deletion counts without record contents or credentials.

## Verification and delivery

Test settings, disabled policies, exact cutoff boundaries, and worker bounds,
failures, timeouts, and shutdown. Use PostgreSQL transactions to verify all three
terminal states, active-row preservation, finalized_at persistence on individual
and bulk transitions, confirmation deletion, rollback, concurrent workers, locked
candidates, confirmation retries versus cleanup, and unchanged stock. Exercise
existing not-found behavior after cleanup at the HTTP boundary. Validate migration
upgrade/backfill/downgrade and run the relevant regression suite and Ruff checks.
Report any unavailable PostgreSQL coverage rather than treating skipped tests as
passing integration checks.

Implementation uses a dedicated feature branch based on the current checkout,
preserving the four pre-existing edited files and their exact changes. After
required checks pass, review and locally commit only the feature changes. No push
or merge is included.
