# Controller error handling implementation plan

**Goal:** Controllers only map transport inputs and successful outputs; use cases classify failed operations.

**Architecture:** Keep existing domain exceptions and centralized HTTP translation. Required cancellation and expiration
lock the reservation before distinguishing absence from ineligibility. A separate TryExpireReservationUseCase preserves
optional worker cleanup. Confirmation retrieval raises a new ConfirmationNotFound, leaving MissingConfirmation for
an inconsistent confirmed reservation.

**Constraints:** Preserve current workspace changes, row locks, conditional SQL updates, UTC comparisons, transaction
boundaries, and two-space Python indentation. No schema or dependency changes.

- [x] Add failing use-case tests for missing/ineligible operations and confirmation retrieval; retain stock-once and rollback checks.
- [x] Make cancellation and explicit expiration return Reservation or raise; add optional cleanup use case and wire the worker.
- [x] Raise ConfirmationNotFound for an absent requested confirmation and remove all controller HTTPException branches.
- [x] Exercise real use cases through HTTP and update concurrency expectations for typed failures.
- [x] Update service documentation and run pytest, PostgreSQL race tests if available, and Ruff on changed files.

Verification: `.venv/bin/pytest -q` against an isolated PostgreSQL 18 database: 400 passed.
`.venv/bin/ruff check stocklock tests migrations` and `git diff --check`: passed.
API tests required execution outside the sandbox because thread-pool callbacks timed out inside it.
The temporary PostgreSQL container was stopped and automatically removed after verification.
Independent focused code review: no findings.
