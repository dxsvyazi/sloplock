# Rich Domain Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement task by task.

**Goal:** Entities protect their invariants; use cases construct them.
**Architecture:** Validated dataclasses with read-only fields and explicit mutation methods;
services coordinate persistence and adapters preserve concurrency protections.
**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy, PostgreSQL, wireup, pytest.
**Spec:** docs/superpowers/specs/2026-10-26-rich-domain-design.md

## Global Constraints

Keep asynchronous repository ports, UUID identifiers, two-space indentation, UTC timestamps,
HTTP behavior and transaction boundaries. No schema or dependency changes.

## Review Focus

- Failed multi-field updates must leave the entity untouched.
- Historical hydration must accept overdue holds and valid terminal states.
- Confirmation cannot race expiration after a lock wait.
- Stock correction must reserve capacity for all stored active holds.
- Creation failures must roll back all stock changes.

## Task 1: Entity invariants

- [x] Add tests/test_entities.py for construction, direct assignment, mutation atomicity,
  stock bounds/capacity, lifecycle boundaries, retries and confirmation factory.
- [x] Run the tests and observe failures before implementing.
- [x] Implement Product.update_details, correct_stock, adjust_stock and stock input rules;
  Reservation.can_transition, transition, confirm, cancel, expire, ensure_retry and
  ensure_new; Confirmation.from_reservation. Validate constructors and normalize UTC.
- [x] Run entity tests.

## Task 2: Workflow integration

- [x] Change services create signatures to create(entity); move construction to use cases.
- [x] Delegate entity rules from services and repositories; preserve SQL predicates/locks.
- [x] Update doubles and existing tests to use valid entity construction and methods.
- [x] Fix stale plural use-case imports discovered by the baseline collection run.
- [x] Run full pytest and ruff, update existing workflow documentation.

## Task 3: Verification

- [x] Run PostgreSQL concurrency tests when a database is available; report skipped checks.
- [x] Review the diff for invariant bypasses, business rules left in services, and lost locks.
- [x] Record actual verification results and any environment limitations.

## Verification results

- Entity regression tests initially failed (24 cases), then passed after implementation.
- Invalid timestamp type tests initially failed (9 cases), then passed after validation fix.
- Final full suite against disposable PostgreSQL 18: 380 passed, no skips (4.78 seconds).
- Ruff: all checks passed; 23 relevant files pass format checks; git diff --check passes.
- Independent review: no Important or Critical findings; 111 focused tests also passed.
- Deferred minor: stock persistence generates updated_at in SQL while detail changes
  persist the entity timestamp. This preserves existing stock timestamp behavior and
  is documented as a persistence exception; no correctness regression was identified.
- The sandbox blocked HTTP dependency thread execution; the full suite passed outside it.
- Baseline plural use-case import mismatches were repaired to make the suite collect.
