# Value Objects Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace entity field validators with immutable domain types and explicit creation factories.

**Architecture:** Frozen dataclass value objects own scalar constraints. Entity constructors require these types,
factories convert primitive creation inputs, and adapters unwrap values. Entities retain relationship and lifecycle rules.

**Tech Stack:** Python 3.13+, dataclasses, pytest, existing FastAPI and SQLAlchemy adapters.

**Spec:** `docs/superpowers/specs/2026-10-27-value-objects-design.md`

## Global Constraints

- No new dependencies or persistence schema changes.
- Preserve HTTP contracts, asynchronous repository operations, UUIDs, and transaction/concurrency controls.
- Preserve UTC normalization, opaque key identity, bounds, and error categories.
- Use two-space indentation and double quotes.

## Review Focus

- Reject booleans, floats, strings, and wrong value-object types at domain boundaries.
- Validate an entire detail patch before changing any entity field or timestamp.
- Hydrate historical terminal reservations without resetting identity, status, or deadline.
- Keep no-op snapshots and timestamps stable with value equality rather than object identity.
- Unwrap all values at HTTP/SQL boundaries, including atomic stock updates and retry lookups.

### Task 1: Scalar value objects

**Files:** Create `stocklock/domain/value_objects/{product,reservation}.py` and `tests/test_value_objects.py`.
**Interfaces:** Frozen slotted ProductName(str), SKU(str), StockQuantity(int), StockDelta(int),
ReservationQuantity(int), IdempotencyKey(str), each exposing `.value`.

- [x] Add failing tests for bounds, strict numeric types, text/key identity, equality and immutability.
- [x] Run `.venv/bin/pytest tests/test_value_objects.py -q` and observe missing types.
- [x] Implement the types with existing scalar validation helpers.
- [x] Run the value-object tests successfully.

### Task 2: Entities and complete boundary migration

**Files:** Modify entities, services, repository ports, use cases, HTTP/ORM mappers,
product persistence adapter, domain/persistence tests, and in-memory doubles.
**Interfaces:** `Product.create(*, name: str, sku: str, stock_quantity: int)`,
`Reservation.create(*, product_id: UUID, quantity: int, key: str, created_at: datetime, expires_at: datetime)`.
Constructors use typed fields; domain mutations and repository scalar operations accept their corresponding value objects.
Confirmation keeps its existing factory.

- [x] Add failing factory/type-boundary tests; update existing domain tests to assert typed values.
- [x] Run focused tests and verify failures identify the absent factories/typed fields.
- [x] Implement factories, strict constructors and typed mutations; remove obsolete scalar static validators.
- [x] Update application conversions, typed snapshots/ports, primitive mappings, and all callers/doubles.
- [x] Run domain, service, mapping, application and API tests; preserve all previous assertions semantically.

### Task 3: Regression verification and delivery

**Files:** Update domain usage documentation; review all feature changes.

- [x] Run the full suite, including PostgreSQL race tests when a test database is available.
- [x] Run Ruff on changed Python files and `git diff --check`.
- [x] Review the final diff against the spec, with an independent reviewer as required by executing-plans.
- [x] Resolve material findings, rerun affected checks, and commit the coherent refactor locally.
- [x] Report branch, commit, actual checks, and any unavailable verification.


## Validation results

- Full PostgreSQL-backed suite: 512 passed, no skips.
- Ruff lint: `stocklock`, `tests`, and `migrations` passed.
- Ruff formatting: all 37 changed/new Python files passed.
- `git diff --check` passed.
- Independent review found no material runtime issues. Corrected the reported
  service-key test coverage regression and added wrong-domain-type service cases.
- PostgreSQL regression tests exposed an existing integer bind overflow for
  negative stock deltas. Clamping the upper query bound to the schema maximum
  preserves the predicate for valid stock and fixes the overflow; both negative
  regression cases failed before the fix and all four signed-bound cases passed
  afterward.
