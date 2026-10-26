# Concurrent repositories implementation plan

> Execute inline with superpowers:executing-plans; use test-driven development.

**Goal:** Implement product, reservation, and confirmation persistence without lost stock updates or competing terminal outcomes.

**Architecture:** Framework-independent asynchronous ports expose explicit operations rather than whole-entity replacement. Repositories use PostgreSQL row locks and conditional updates inside a task-owned application unit of work. Small application workflows coordinate stock and reservation/confirmation changes in the same transaction.

**Tech stack:** Python 3.13+, SQLAlchemy async, asyncpg, PostgreSQL, Alembic, pytest.

**Spec:** AGENTS.md and the user's approval of the recommended explicit-operation approach.

## Global constraints

- Keep SQLAlchemy, FastAPI, and wireup out of domain modules.
- Preserve UUIDs, UTC timestamps, asynchronous APIs, two-space indentation, and 120-character lines.
- No HTTP endpoints or reservation lifetime policy in this change.
- Repositories never commit; the application unit of work owns transactions.
- Existing files are untracked and there is no HEAD; work in place and do not commit or stage unrelated files.

## Review focus

- Refresh previously read ORM rows when acquiring locks.
- Evaluate expiration after acquiring the reservation lock, including lock waits across the deadline.
- Bound integer stock changes without overflowing database integers.
- Scope reservation idempotency keys by product and reject mismatched quantities.
- Roll back both state and stock/confirmation after any later failure.

### Task 1: Repair transaction scopes

Files: `stocklock/infrastructure/session_manager.py`, `stocklock/application/ports/uow.py`, `stocklock/application/uow.py`, `tests/test_session_manager.py`.

- [x] Reproduce existing transaction-entry failure; preserve strict repository session access and optional no-session inspection.
- [x] Implement the smallest fix and a framework-independent `IUnitOfWork.begin()` port.
- [x] Run `pytest tests/test_session_manager.py -q`; expect all tests passing.

### Task 2: Implement repository contracts and adapters

Files: domain repository ports, domain pagination/errors/lifecycle rules, three infrastructure repository adapters, ORM constraints, Alembic environment and initial revision, `tests/test_repositories.py`.

Interfaces: `ProductRepository(SessionManager)` offers create/find/list, partial detail updates, absolute stock correction, locked reads and conditional stock deltas. `ReservationRepository(SessionManager)` offers create/find/list with product/status filters, scoped idempotency lookup and active-only terminal transitions. `ConfirmationRepository(SessionManager)` offers find/create with one immutable result per reservation. All return detached domain values.

- [x] Write and run failing PostgreSQL tests for CRUD/filtering/pagination, constraints, invalid quantities, duplicate confirmation and terminal transitions.
- [x] Replace SQL-dependent pagination in domain ports, remove unsafe generic update/delete methods, implement adapters and explicit database constraints.
- [x] Add an initial migration and configure model metadata and an environment-supplied database URL.
- [x] Run repository tests against an isolated PostgreSQL database; expect passing results.

### Task 3: Coordinate atomic workflows and prove races

Files: `stocklock/application/usecases/reservations.py`, `tests/test_reservation_workflows.py`, repository documentation.

Interfaces: `ReservationUseCases(uow, products, reservations, confirmations)` offers reserve (caller supplies aware expiration), confirm, cancel, expire. `reserve` locks product before checking scoped idempotency/decrementing stock; terminal operations lock reservation before deciding eligibility and updating related rows. Expiration comparisons use database wall time after lock acquisition.

- [x] Write and run failing independent-transaction tests for oversubscription, stock corrections/details during reservations, retries, competing confirmation/cancellation/expiration, lock waits across expiration, and rollback after injected database failures.
- [x] Implement workflows using only ports and domain values; no framework imports.
- [x] Run the full test suite, Ruff, Alembic upgrade/downgrade/schema comparison; review concurrency and rollback behavior.
- [x] Document transaction/lock ordering, API changes, database setup, results and remaining limits.

## Execution record

- Baseline: mapping tests pass; transaction-scope tests fail because `begin()` calls strict `get_session()` before a session exists. The cancellation test waits forever after that entry failure.
- Workspace decision: no HEAD exists, so a linked worktree cannot preserve the existing untracked project. Modify in place; do not create an initial commit on the user's behalf.
- Authorization: user approved proceeding with the recommended approach; execute without another approval gate.
- Task 1 complete: existing transaction failure reproduced, optional session access repaired, 8 session tests passed.
- Task 2 complete: constructor failure reproduced before adapters; 13 repository tests passed on PostgreSQL 18.
- Task 3 complete: missing workflows/domain rules and unsupported migration connection reproduced first; application workflows, pure lifecycle rule, Wireup composition, and migration implemented. Full PostgreSQL suite: 132 passed.
- Independent review: `review_repositories` inspected implementation/tests and found no actionable issues; reviewer did not rerun database tests.
- Regression sensitivity verified: changing wall clock to transaction-start time makes the expiration lock-wait test fail; disabling ORM refresh makes the cached-row test fail. Both mutations restored before final verification.
- Checks: Ruff lint passed, modified Python files formatted, compileall passed; Alembic offline SQL generated and integration test verified upgrade/model parity/downgrade. Without the test URL: 97 passed, 35 explicitly skipped.
- Decisions: stock corrections retain existing absolute-quantity semantics; idempotency is scoped by product and rejects quantity mismatches; cancellation may release an overdue stored-active hold. All are documented in `docs/repositories.md`.
- Limits: no endpoints or expiration scheduler; custom/batch workflows must follow the documented lock order and transaction contract. No commits, staging, or changes to local credentials.
