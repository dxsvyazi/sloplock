# Product Deletion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Protected administrative product deletion, visibility filters, and independent product garbage collection.

**Architecture:** Application use cases own transactions and coordinate domain services and repository ports. PostgreSQL product locks serialize deletion with reservation creation. Infrastructure workers share a base retry loop.

**Tech Stack:** Python 3.13+, FastAPI, PostgreSQL, SQLAlchemy, Wireup, Alembic, pytest.

**Spec:** docs/superpowers/specs/2026-10-29-product-deletion-design.md (including approved worker amendment).

## Global Constraints

- Two-space indentation, double quotes, 120-character lines.
- Both deletion modes reject stored active reservations, including overdue holds.
- Soft deletion preserves history; explicit hard deletion overrides retention.
- No pushing, deployment, or new administrative CLI.
- Use existing checkout on a dedicated branch; feature-workflow forbids worktree creation without consent.

## Review Focus

- Concurrent reserve/delete must produce a hold or a deletion, never a hidden active hold.
- Overdue stored active reservations block deletion until expiration commits.
- Confirmation retries survive soft deletion and return 404 after hard deletion.
- Automatic product cleanup must wait for indefinitely retained history.
- Worker exceptions retry, while task cancellation propagates and rolls back.

### Task 1: Product lifecycle and deletion transactions

**Files:** domain entity/product service/repository ports; product commands/usecases; product ORM/mapper/repository; reservation visibility port/service/repository; migration `0004_product_deletion.py`; tests `test_product_deletion.py`.

**Interfaces:** Produce `Product.deleted_at`, `Product.soft_delete(at)`, `DeleteProductCommand(product_id, mode)`, `DeleteProductUseCase.execute(command) -> None`, `ProductVisibility`, and `DeletionMode`. Repository `save_deletion(product)`, `hard_delete(id)`, and `purge_deleted(cutoff, limit)` require product locks. Existing find-by-ID returns full entity; services enforce visibility. Extend list methods with visibility before pagination.

- [x] Write tests for idempotent domain deletion, rejection of active/overdue holds, blocked mutations, retained history and confirmation retries, atomic hard cascade, rollback, list filters, and PostgreSQL races.
- [x] Run focused tests; observe failures for missing lifecycle/deletion behavior.
- [x] Implement entity lifecycle, application transaction, port/adapter operations, enum validation, visibility filtering, and cascade migration.
- [x] Run focused tests plus existing usecase/repository/migration/race coverage; expect passing behavior.

### Task 2: HTTP protection and contracts

**Files:** `api/v1/security.py`, product/reservation schemas/mappers/handlers/errors; `project/configs/admin.py`, `project/container.py`; tests `test_product_deletion_api.py` and HTTP test helper.

**Interfaces:** Consume Task 1 commands/usecases/enums. Produce admin bearer verification with secret `ADMIN_API_TOKEN`, conditional authentication for deleted visibility, `DELETE /products/{id}?mode=soft|hard`, product `visibility` and `include_deleted`, reservation `product_visibility`.

- [x] Write HTTP tests asserting empty 204, 401 invalid/missing token, 503 unconfigured token, 404 missing/deleted products, 409 active reservations, 422 invalid filters, and protected hidden product inspection.
- [x] Run focused HTTP tests; observe missing endpoint/protection failures.
- [x] Implement thin handlers, schema/command mapping, security dependency, DI factories, and response `deleted_at`.
- [x] Run HTTP, mapping, wiring and startup tests; expect passing behavior.

### Task 3: Shared workers and independent garbage collection

**Files:** `infrastructure/workers/base.py`, existing worker modules, new `product_cleanup.py`; product cleanup policy/usecase; time settings/container; tests `test_base_worker.py`, `test_product_cleanup.py`.

**Interfaces:** Produce `BaseWorker._run_once(stop=...)`, compatibility `run_once`, defined `run(stop)`, and `exception_message` class attribute. `ProductCleanupPolicy` and `CleanupProductsUseCase.execute(limit=100) -> int` consume Task 1 purge adapter. Dedicated cleanup settings use defaults 30 days/86400 seconds/100 rows/100 batches/30 seconds.

- [x] Write tests for shared abstract interface, validation, retries/logging, stop and cancellation; cleanup cutoff, bounded/overlapping sweeps, locked rows, retained history, rollback, and disabled CLI with no SQL.
- [x] Run focused tests; observe missing worker/cleanup failures.
- [x] Extract base without changing expiration fallback/cursor or retention batching. Add separate cleanup worker and settings/DI.
- [x] Run all worker/time-policy/cleanup tests; expect passing behavior.

### Task 4: Delivery and verification

**Files:** README, service/repository/time-policy docs, `.env.example`, `docker-compose.yml`, AGENTS.md.

- [x] Document API/authentication, retention, separate cleanup worker, and explicit history erasure; configure Compose service and example settings.
- [x] Run `uv run ruff check .`, full `uv run pytest -q` with disposable PostgreSQL if available, and `git diff --check`.
- [x] Request fresh whole-change review, fix material findings, and re-run affected checks.
- [x] Review and stage only this feature, create final local commit, and report branch/hash and checks.

## Execution ledger

- Design approved; worker amendment explicitly authorized. Native execution selected to keep tightly coupled interfaces in one context. No extra approval needed for already authorized implementation.
- Base: main at c802e57. Pre-existing untracked file is this feature's design created in the prior turn; include it in delivery.

- Verification: 685 passed with disposable PostgreSQL 18; no skipped tests. Ruff and whitespace checks passed. Compose configuration validated with `.env.example`.
- Whole-change reviewer found a malformed Compose insertion; corrected it and verified configuration. Follow-up review found no remaining material issues.
- Ruling: corrected pre-existing reservation cleanup validation failures (active/string status cutoffs), using domain target validation and bounded page validation in cleanup adapters. Existing failing tests prove the correction.
- Product cleanup is its own process as approved; each worker inherits the shared base loop. Administrative exceptions intentionally supersede the old product-retention prohibition in the guide.
