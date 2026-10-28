# Bulk Expiration Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expire a page of reservations atomically and return stock exactly once.
**Architecture:** Application-owned transaction, repository-owned bulk SQL,
domain service grouping, existing individual workflow fallback.
**Tech Stack:** Python 3.13, PostgreSQL, SQLAlchemy async, wireup, pytest.
**Spec:** docs/superpowers/specs/2026-10-28-bulk-expiration-design.md

## Global Constraints

Preserve user edits, asynchronous interfaces, UUIDs, and domain framework isolation.
Two-space indentation, double quotes, 120-character lines. No retention/schema/API changes.

## Review Focus

- Multiple holds on one product must restore their sum exactly once.
- Locked, terminal, and future reservations must not contribute stock.
- Stock restoration failure must roll back every transition and increment.
- Overlapping batches must coordinate with cancellation and confirmation.
- Failed batches and timeouts must not starve later pages; cancellation propagates.

### Task 1: Bulk workflow and worker integration

**Files:** application/commands/reservation.py, application/usecases/expiration.py,
domain/ports/repositories/reservation_repository.py,
domain/services/{reservation,product}_service.py,
infrastructure/repositories/reservation_repository.py,
infrastructure/workers/expiration.py, project/container.py, tests/test_bulk_expiration.py,
tests/test_expiration_worker.py, tests/service_doubles.py.

**Interfaces:** ExpireReservationsCommand(reservation_ids: tuple[UUID, ...]);
ExpireReservationsUseCase.execute(command) -> list[UUID];
IReservationRepository.expire_due(reservation_ids: tuple[UUID, ...]) -> list[Reservation];
ReservationService.expire_due(reservation_ids) -> list[Reservation];
ProductService.return_stock_many(reservations: list[Reservation]) -> None.

- [x] Write PostgreSQL tests for bulk grouping/filtering, rollback, locked rows,
  concurrent workers, terminal races, worker fallback, cancellation, and limits.
- [x] Run tests and confirm failures reflect missing bulk behavior.
- [x] Implement bulk repository primitive, domain coordination, application command/use case,
  DI registration, and worker bulk attempt with individual fallback.
- [x] Run PostgreSQL integration tests and domain tests; inspect complete diff.
- [x] Run ruff and git diff --check; review and commit only feature changes.

Expected verification: .venv/bin/pytest -q tests/test_bulk_expiration.py
tests/test_expiration_worker.py tests/test_expiration_candidates.py, then the full
suite with STOCKLOCK_TEST_DATABASE_URL pointing to disposable PostgreSQL.

Validation: 529 tests passed against disposable PostgreSQL 18; ruff check,
format checks on changed Python files, and git diff --check passed. Independent
code review found no concrete defects. The initial API timeout under sandbox
restrictions disappeared when the same tests ran with normal local access.
