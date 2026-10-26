# Project Review Fixes Implementation Plan

**Goal:** Resolve the eight validated review findings while preserving HTTP field names and atomic inventory workflows.

**Architecture:** Application use cases own transactions; domain ports describe inventory operations; infrastructure owns SQL, session management, and worker scheduling. Preserve PostgreSQL READ COMMITTED and reservation-before-product terminal lock order.

**Decisions:** Keep existing `key` and `stock_quantity` wire names. Accept opaque case-sensitive keys up to 256 Unicode characters (1024 UTF-8 bytes), rejecting NUL and surrounding whitespace. Keep stored status semantics with eventual expiry through a separately runnable worker enabled in Compose. Stock corrections must leave capacity for every stored active hold. Keep retention disabled until a deletion contract exists.

**Workspace:** Work in the supplied checkout: all project files are currently untracked, so a Git worktree would omit the project. Do not stage secrets or create commits as part of this task.

- [x] Exclude local environment files; repair dev/prod dependency installation and startup; use configured bind host and explicit development reload.
- [x] Add regression tests for idempotency key limits, then shared validation, HTTP documentation, ORM constraints, and a new Alembic revision. Never rewrite initial migration or truncate existing keys.
- [x] Move concrete unit of work to infrastructure, delete obsolete session manager, remove unused domain dumping and unused mapping helpers.
- [x] Standardize service `require`/`list` and product patch names; introduce an expiration command; repair stale tests and documentation.
- [x] Test correction capacity, then enforce it after acquiring the product lock and reading active held quantity in a fresh statement. Add independent transaction races and lock-wait checks.
- [x] Test bounded due-reservation selection and expiration sweep failure isolation; implement application sweep plus infrastructure worker with graceful shutdown, scoped dependencies and Compose wiring.
- [x] Run Ruff, full unit/API/PostgreSQL suites, migration parity and upgrade checks, and dev/prod image smoke checks where available. Independently review changes, address defects, and report remaining limitations.

## Verification risks

- Count overdue stored-active reservations when reserving stock-return headroom.
- Do not lock reservation rows after the product lock in corrections.
- Expiry selection must advance past failed candidates so one failure cannot starve later holds.
- Worker failures roll back one hold, log the error, and retry on later sweeps; cancellation must close scopes and the container.
- Tests run outside the sandbox when necessary: sandbox thread execution caused unrelated API timeouts during review.

## Progress

Baseline from review: PostgreSQL 18 full suite 277 passed / 13 failed; all failures traced to stale test names, removed pagination code, or an enum assertion. Ruff passed. Implementation authorized by user after independent validation.

## Final evidence

- Full suite with disposable PostgreSQL 18: **347 passed**, no skips/failures.
- Ruff lint and format check passed (94 Python files formatted).
- Dev and prod image targets built successfully; production imports passed and
  local environment files were absent from the image.
- Isolated Compose smoke verified database health -> migrations -> API/worker,
  published HTTP access, unattended expiry, stock restoration, and rejection of
  expired confirmation. Host automatic subnet exhaustion was bypassed only in
  the temporary verification override with an explicit private subnet.
- Independent combined review and focused concurrency review found no blockers.
  Review raised unbounded worker lock waits; added 30-second operation bounds
  and a PostgreSQL regression proving rollback/progress past a locked hold.
- Stale service/cursor/enum tests repaired. Legacy overflow rollback coverage
  retained using deliberately inconsistent raw state.
- No commits/staging, live database migrations, or publication. Secret contents
  were not printed or committed.
  Keys and stock quantity retain existing HTTP field names; tightened key
  validation and correction capacity are documented behavior changes.
