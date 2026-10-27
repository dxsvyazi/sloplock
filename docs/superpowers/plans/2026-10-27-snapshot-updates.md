# Snapshot Updates Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution.

**Goal:** Persist domain mutations from snapshots without weakening concurrency.

**Architecture:** Use cases fetch, snapshot, and mutate. Services detect changed
domain fields. Repositories perform restricted SQL writes with existing guards.

**Tech Stack:** Python 3.13+, SQLAlchemy, PostgreSQL, pytest.

**Spec:** ../specs/2026-10-27-snapshot-updates-design.md

## Global Constraints

- Preserve asynchronous ports, UUID conventions, UTC timestamps, and two-space indentation.
- Keep SQLAlchemy out of domain/application code; retain application transaction boundaries.
- Preserve existing uncommitted work; do not commit or reset unrelated changes.

## Review Focus

- No-op detail/stock saves must not issue an update or advance timestamps.
- Snapshot/entity identity mismatch must fail before persistence.
- Detail writes must not replace stock; stock writes must not replace details.
- Terminal saves must recheck database deadlines and active state.
- Stock corrections must query active holds after acquiring the product lock.

### Task 1: Product snapshots and restricted saves

Files: product repository port, service, adapter, application use cases,
tests/service_doubles.py, tests/test_snapshot_updates.py, existing product tests.

Interfaces: ProductDetailsSnapshot.capture(product), ProductStockSnapshot.capture(product),
ProductService.save_details(product, original=...), save_stock(product, original=...),
active_held_quantity(id); repository save_details(product, changed_fields=...),
save_stock(product), active_held_quantity(id).

- [x] Add regression tests for immutable snapshots, no-op persistence, timestamps,
      mismatched identity, and detail/stock field isolation; observe failures.
- [x] Implement snapshots, service comparison, use-case mutation, and restricted saves.
- [x] Migrate doubles/direct callers; run product, service, and use-case tests.

### Task 2: Reservation status snapshots

Files: reservation repository port, service, adapter, reservation/confirmation use
cases, test doubles, direct callers, and tests/test_snapshot_updates.py.

Interfaces: ReservationSnapshot.capture(reservation),
ReservationService.save_transition(reservation, original=...),
IReservationRepository.save_transition(reservation, previous_status=...).

- [x] Add tests for unchanged/terminal snapshots, deadline rejection, and rollback;
      observe failures before implementing.
- [x] Move terminal domain mutations into use cases, including best-effort cleanup.
- [x] Replace adapter transition orchestration with guarded status persistence.
- [x] Migrate direct callers; retain existing PostgreSQL race/deadline tests.

### Task 3: Documentation and complete verification

Files: docs/repositories.md, docs/services.md, docs/time-policies.md if needed.

- [x] Update contracts and explain specialized stock and immutable confirmation paths.
- [x] Run the full pytest suite and Ruff; run PostgreSQL tests using a disposable
      schema when a local database is available.
- [x] Review changes against the saved pre-task working-tree baseline and report gaps.

## Execution results

Implemented inline against the existing working tree, with the pre-task code,
tests, and docs saved under `/tmp/stocklock-snapshot-baseline` for scoped review.
Existing uncommitted work was preserved; no commits or branch changes were made.

Snapshot regression tests were observed failing before implementation, then
passing. Reverted detail/stock changes also exposed a timestamp mismatch, fixed
by returning the snapshot's persisted timestamp on a net no-op.

Final verification: `pytest -q` against disposable PostgreSQL 18: **420 passed**.
Ruff lint, formatting checks for all changed Python files, and `git diff --check`
passed. API thread-pool timeouts inside the sandbox disappear when the same tests
run outside sandbox restrictions. The final complete run used that environment.
An independent read-only review of the scoped baseline diff found no actionable
regressions. The disposable database was removed after verification.
