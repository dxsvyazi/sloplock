# Time Policies Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Configure present reservation lifetime and future cleanup/retention policies from the environment.

**Architecture:** Pydantic settings stay at the composition boundary. An immutable application policy supplies
expiration from the database clock inside the reservation transaction; domain code stays framework independent.

**Tech Stack:** Python 3.13, Pydantic Settings, Wireup, SQLAlchemy, PostgreSQL, pytest.

**Spec:** `docs/superpowers/specs/2026-10-24-time-policies-design.md`

## Global Constraints

- Two-space indentation, double quotes, 120-character lines; fully annotated changed interfaces.
- No cleanup or deletion workers; retention defaults to indefinite.
- Keep asynchronous ports, database wall clock, atomic transactions, and lock ordering.
- Existing files are uncommitted; work in place without commits or staging unrelated files.

## Review Focus

- Invalid, zero, fractional, boolean, and excessive durations must fail validation.
- Product-lock waiting must not shorten a new hold's lifetime.
- A retry after a settings change must retain original timestamps and stock.
- UTC conversion and datetime overflow must not leave a partial stock decrement.
- Worker settings must not start jobs or change confirmation retry behavior.

### Task 1: Settings and immutable lifetime policy

**Files:** Create `stocklock/project/configs/time_policy.py`, `stocklock/application/policies/reservation.py`,
and `tests/test_time_policies.py`.

**Interfaces:** `TimePolicySettings()` exposes the six documented environment fields and typed duration
properties (retention returns `timedelta | None`). `ReservationTimePolicy(lifetime: timedelta)` exposes
`expiration_for(created_at: datetime) -> datetime` and rejects nonpositive durations.

- [x] Add and run failing tests for settings parsing, range validation, dotenv precedence, UTC and overflow.
- [x] Implement settings and policy without import-time instances; run their tests.

### Task 2: Reservation creation and composition

**Files:** Modify reservation command, use case, domain service, and `project/persistence.py`;
update `tests/test_usecases.py`, `tests/test_persistence_wiring.py`, `tests/usecase_driver.py`,
and `tests/test_reservation_workflows.py`.

**Interfaces:** Command contains only product ID, quantity, and key. Use case adds a required
`time_policy: ReservationTimePolicy`; `execute(command)` derives timestamps after lock/retry/stock hold.
Domain creation adds optional keyword `created_at: datetime | None = None`.
`create_persistence_container(session_maker, *, time_settings: TimePolicySettings | None = None)`
loads configuration at composition and injects its immutable reservation policy.

- [x] Add failing tests for configured creation, lock-delay timing, policy-change retries, and rollback on overflow.
- [x] Wire policy and remove the command deadline; migrate direct callers and integration driver.
- [x] Run mapping, policy, domain, use-case, wiring and PostgreSQL race tests where available.

### Task 3: Documentation and verification

**Files:** Update `docs/services.md`, `docs/repositories.md`, add `docs/time-policies.md` and `.env.example`.

- [x] Document units, bounds, defaults, environment precedence, injection, and future-only worker settings.
- [x] Run the complete suite and lint, check annotations, and review the final changes.
- [x] Report actual results including unrelated baseline failures and skipped PostgreSQL checks.

## Execution and verification

Work was performed in place: the repository has no initial commit and all existing
files were already untracked. No staging or commits were performed. Temporary type
checking tools were installed under `/tmp` without changing project dependencies.

- Settings/policy tests: observed 58 failures before implementation, then 58 passes.
- Creation/DI tests: observed six failures before wiring, then passes.
- Final full suite, with `STOCKLOCK_TEST_DATABASE_URL` pointing at a disposable
  PostgreSQL 18 container: `python -m pytest -q --tb=short` → **255 passed, 3 failed**.
  All database tests ran, including the added real-lock-wait lifetime test.
- The three failures are the existing parameterizations of
  `test_malformed_cursor_raises_custom_exception_with_cause` in `tests/test_exceptions.py`:
  payloads `bad`, `bad.5`, and `01900000-0000-7000-8000-000000000001.bad`. They import
  the absent `stocklock.shared.utils.pagination.cursor` module. The baseline also
  had four reservation mapping failures; those four are fixed.
- `ruff check stocklock tests migrations` passes; formatter checks pass for all
  14 changed Python files.
- Strict mypy, with `--explicit-package-bases --follow-imports=silent` and the
  project Python executable, passes for the six changed/new production modules,
  two new test modules, and `tests/service_doubles.py`, `tests/usecase_driver.py`,
  and `tests/conftest.py` (11 files).
- An additional strict mypy run following imports reported 17 existing errors in
  seven untouched modules: `shared/descriptors.py`, `domain/entities/base.py`,
  `infrastructure/models/base.py`, `infrastructure/session_manager.py`, and the
  three infrastructure repository implementations. These are outside time-policy scope.
- Independent reviewer found no material issues; independently ran the 64 new
  non-database tests successfully.
