# Domain Services Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Expose invariant-enforcing domain operations and compose them in individual transactional use case classes.

**Architecture:** Repository-backed domain services never start transactions. Application use cases depend on these services and IUnitOfWork; composition uses existing Wireup factories.

**Tech Stack:** Python 3.13+, asynchronous repository ports, PostgreSQL, pytest, Wireup.

**Spec:** docs/superpowers/specs/2026-10-24-domain-services-design.md

## Global Constraints

- No web, persistence-framework, DI-framework, or application imports in the domain.
- Services do not commit; each application flow owns one transaction.
- Preserve database locks, UTC expiration boundary, stock bounds, and retry behavior.
- Each use case is an individual class with execute; no speculative interfaces.
- No HTTP endpoints, lifetime default, scheduler, schema change, or credentials in documentation.

## Review Focus

- Invalid inputs must fail even when called directly through a domain service (Task 1).
- Retrying a terminal reservation must retain original identity without holding stock again (Task 2).
- Lock waits must not permit confirmation after expiration (Task 3).
- Failure returning stock must roll back the terminal transition (Tasks 2 and 3).
- Reads require the same transaction-scoped repository context as writes (Tasks 2 and 3).

### Task 1: Domain operations

**Files:** domain/services/{product,reservation,confirmation}_service.py, domain/validation.py, application/commands/common.py, tests/test_domain_services.py.

**Interfaces:** ProductService(products) provides create/get/list/update_details/correct_stock/hold_stock/return_stock. ReservationService(reservations) provides get/list/find_retry/current_time/create/confirm/cancel/expire. ConfirmationService(confirmations) provides get/require/create. Use UUID identifiers and domain entities; defaults match repository pagination. Shared validation belongs in domain/validation.py.

- [x] Add failing tests for stock bounds, missing products, reservation quantity/expiration/key validation, retry conflicts, ineligible terminal operations, and confirmation eligibility/identity.
- [x] Run `.venv/bin/pytest tests/test_domain_services.py -q`; confirm missing service implementations fail.
- [x] Implement operations against domain repository ports with no unit-of-work dependency. Reuse pure can_transition.
- [x] Run service tests and reservation rule tests; require all pass.

### Task 2: Individual application flows

**Files:** application/usecases/{products,reservations,confirmations}.py, tests/test_usecases.py, tests/test_reservation_workflows.py, project/persistence.py, tests/test_persistence_wiring.py.

**Interfaces:** Each named use case in the design exposes execute(command), with ReserveProductUseCase.execute(command, *, expires_at: datetime), and ExpireReservationUseCase.execute(GetReservationCommand). Dependencies are services plus IUnitOfWork. Return domain entities, entity lists, or None as specified by the design.

- [x] Add failing tests through real services with transaction-aware repository doubles for reserve/confirm/release effects, retry behavior, and rollback on multi-step failure. Exercise product/read flows through their commands.
- [x] Confirm these tests fail before implementing use cases.
- [x] Replace ReservationUseCases with individual classes and compose only service operations inside uow.begin().
- [x] Migrate test callers and Wireup providers to those individual classes. Reconcile confirmation create_or_find naming while retaining create compatibility; correct product patch test calls.
- [x] Run service/use-case/wiring tests and require success.

### Task 3: Integration, documentation, and review

**Files:** docs/repositories.md, docs/services.md, existing PostgreSQL integration tests.

**Interfaces:** Existing database race tests execute individual use cases via services; containers resolve all services/use cases sharing the same SessionManager.

- [x] Run the full pytest suite and Ruff; classify existing versus introduced failures.
- [x] Run PostgreSQL race/rollback tests if a disposable local database is available. Never substitute mocks for concurrency evidence.
- [x] Document service transaction contracts and migration from grouped workflows.
- [x] Request a fresh review, address material findings, rerun affected checks, and report exact verification and gaps.

## Execution ledger

Ruling: Execute in the current checkout because source files are untracked and a new worktree would omit them. Preserve all existing files and do not commit the user's unrelated untracked content.
Ruling: Approval to proceed covers implementation; continue inline without another plan approval gate.
Pre-flight: Task 2 consumes Task 1 domain operations; Task 3 verifies Task 2 through existing repository adapters. Keep repository ports and concurrency contracts intact.

Task 1: complete — 37 new domain service cases and 36 existing lifecycle rule cases passed.
Task 2: complete — 16 use-case behavior cases and composition wiring passed; PostgreSQL scenarios now invoke individual use cases through a test-only driver.
Task 3: complete — final full PostgreSQL 18 suite: 186 passed; Ruff clean. Fresh review found no material issues.
Ruling: Fix existing adapter integration blockers in scope: missing BaseORM package export, confirmation create_or_find implementation, and boolean assignment precedence in product detail validation. Existing integration tests demonstrated each failure before correction.
Ruling: Update six stale session cleanup tests to explicitly request get_session(raises=False), preserving the current production contract. No session manager behavior changed.
Ruling: Reservation creation validates expiration within the domain create operation after the stock hold, with any validation failure rolling the entire transaction back; use cases do not duplicate the domain comparison rule.

Review complete — no material findings. Added the reviewer's optional lock-wait scenario through ConfirmReservationUseCase, retaining the repository-level scenario as well.

Final cleanup: temporary PostgreSQL container stopped and removed; changes remain in the current checkout.
