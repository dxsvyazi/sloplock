# Retention Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Delete terminal reservation history after configurable retention through a bounded standalone worker.

**Architecture:** Application policy computes status-specific cutoffs using IClock. An application-owned transaction invokes a repository operation that locks eligible terminal reservations, deletes confirmations, then reservations. A separate infrastructure worker controls scopes, sweep bounds, timeouts, retries, and shutdown.

**Tech Stack:** Python 3.13, PostgreSQL 18, SQLAlchemy async, Alembic, Wireup, pytest.

**Spec:** `docs/superpowers/specs/2026-10-28-retention-cleanup-design.md`

## Global Constraints

- Default retention is 2,592,000 seconds (30 days); zero means unlimited.
- Preserve all four pre-existing edited files and their exact changes.
- Products and active reservations are never deleted; cleanup never changes stock.
- Use timezone-aware UTC and keep SQLAlchemy and Wireup out of domain rules.
- No partitioning, lifetime cap, ETL, or external log rotation.
- One final local feature commit after required checks; no push or merge.

## Review Focus

- A locked oldest row must not starve other eligible records; verify skip-locked behavior.
- A repeated terminal transition must not reset finalized_at; verify failed retries.
- A confirmation deletion followed by failure must restore both records on rollback.
- Old records with unknown transition dates must receive a full migration grace window.
- Fully disabled retention must issue no cleanup or clock queries.

### Task 1: Retention policy and configuration

**Files:** `stocklock/application/policies/retention.py`, `stocklock/project/configs/time_policy.py`, `tests/test_retention_policy.py`, `tests/test_time_policies.py`.

**Interfaces:** Produce `RetentionPolicy(expired: timedelta | None, cancelled: timedelta | None, confirmed: timedelta | None)`, `.enabled: bool`, and `.cutoffs(now: datetime) -> dict[ReservationStatus, datetime]`. Add `RETENTION_BATCH_SIZE=100`, `RETENTION_MAX_BATCHES=100`, and `RETENTION_OPERATION_TIMEOUT_SECONDS=30` settings and a timedelta timeout property.

- [x] Write tests for 30-day defaults, zero disablement, invalid worker limits, UTC cutoff boundaries, duration validation, and underflow.
- [x] Run `.venv/bin/pytest -q tests/test_retention_policy.py tests/test_time_policies.py`; observe failures for missing behavior.
- [x] Implement configuration and policy, clamping unrepresentable historical cutoffs to aware datetime.min (nothing earlier can exist).
- [x] Run the same tests and confirm success.

### Task 2: Finalization timestamps and transactional cleanup

**Files:** `stocklock/infrastructure/models/reservation.py`, `stocklock/infrastructure/repositories/reservation_repository.py`, `stocklock/domain/ports/repositories/reservation_repository.py`, `stocklock/application/usecases/retention.py`, `stocklock/project/container.py`, `migrations/versions/0003_retention.py`, `tests/test_retention.py`, `tests/test_migrations.py`, `tests/service_doubles.py`.

**Interfaces:** Add `IReservationRepository.purge_terminal(cutoffs: dict[ReservationStatus, datetime], *, limit: int) -> int`. Produce `CleanupRetentionUseCase(uow, reservations, policy, clock).execute(*, limit: int = 100) -> int`. Reuse Task 1 policy and configure it as a singleton in the composition root.

- [x] Write PostgreSQL tests for individual and bulk timestamps, unchanged timestamps on retries, eligibility across statuses and exact cutoff, active/recent/disabled preservation, confirmation deletion, stock preservation, skipped locks, overlapping workers, rollback, and confirmation retries racing cleanup. Add migration backfill/constraint tests and HTTP 404 behavior after deletion.
- [x] Run the new tests against disposable PostgreSQL; observe missing behavior failures.
- [x] Add nullable UTC finalized_at with lifecycle constraint and a partial terminal index on (status, finalized_at, id). Backfill terminal rows using migration time.
- [x] Set finalized_at=clock_timestamp() in individual and bulk terminal updates. Keep timestamps out of domain/transport models.
- [x] Implement bounded skip-locked cleanup with explicit child-first deletion and same-reservation lock order. Validate cutoffs prohibit active status and naive timestamps. Wire the policy and use case. Give existing domain test doubles an explicit unsupported cleanup operation; database tests cover persistence behavior.
- [x] Run retention, migration, expiration, repository, and workflow tests; confirm success.

### Task 3: Standalone worker and operator documentation

**Files:** `stocklock/infrastructure/workers/retention.py`, `tests/test_retention_worker.py`, `docker-compose.yml`, `.env.example`, `README.md`, `docs/time-policies.md`, `AGENTS.md`.

**Interfaces:** Produce `RetentionWorker(container, interval, batch_size=100, max_batches=100, operation_timeout=timedelta(seconds=30))`, `.run_once(*, stop: asyncio.Event | None = None) -> None`, `.run(stop: asyncio.Event) -> None`, and module CLI `main() -> None`.

- [x] Write tests for multiple batches, sweep bounds, zero-query disablement, concurrency, rollback/retry after failure, timeout, cancellation, stop requests, and worker validation. Run and observe missing worker failures.
- [x] Implement worker scopes per batch, bounded transactions, count logging, signal handling, and graceful container closure. Use existing settings; exit CLI immediately when all retention is disabled.
- [x] Add Compose retention service after migrations with a 35-second grace period; document increasing that grace when raising the timeout. Update defaults and finite idempotency/not-found contract in docs and agent guide.
- [x] Run worker tests and full suite against PostgreSQL, Ruff, migration parity, Compose configuration, and `git diff --check`.
- [x] Review the final feature diff, isolate initial user edits when staging, commit only feature changes, and verify the remaining diff matches the initial patch.
