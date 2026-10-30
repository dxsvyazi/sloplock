# Soft deletion with active reservations implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan.

**Goal:** Stop new holds with soft deletion while existing holds finish normally.

**Architecture:** Keep transaction ownership and product locks in current use cases.
Limit the domain deletion guard to hard deletion and permit positive stock returns
in the persistence adapter even after soft deletion.

**Tech Stack:** Python 3.13+, SQLAlchemy, PostgreSQL, FastAPI, pytest.

**Spec:** docs/superpowers/specs/2026-10-30-soft-delete-active-reservations-design.md

## Global Constraints

- Hard deletion rejects stored active holds, including overdue holds.
- Hidden products reject new holds, edits, and administrative corrections.
- Lifecycle transitions and bounded stock returns remain atomic and exactly once.
- Preserve history, retention, idempotent deletion timestamps, and lock ordering.

## Review Focus

- Soft deletion racing reservation creation preserves a hold committed first.
- Positive returns succeed on deleted products; negative adjustments still fail.
- Cancellation and both individual and worker expiration restore stock once.
- Failed stock restoration rolls back the reservation terminal transition.
- Hard deletion still blocks active holds on already hidden products.

### Task 1: Soft deletion and lifecycle stock restoration

**Files:** ProductService, ProductRepository, repository port docstrings,
service doubles, tests/test_product_deletion.py, tests/test_product_deletion_postgres.py,
AGENTS.md, README.md, docs/services.md, docs/repositories.md, docs/time-policies.md.

**Interfaces:** Keep delete(product, mode, at) and adjust_stock(id, delta) signatures.
Positive deltas represent lifecycle returns; decrements require visible products.

- [x] Update active-hold and serialization tests; add post-deletion lifecycle,
  worker expiration, stock-return rollback, and HTTP coverage.
- [x] Run regression tests and observe failures from the old deletion guard and
  the deleted-product stock predicate.
- [x] Limit active-hold guard to hard deletion; allow bounded positive returns on
  deleted products, reflecting that persistence behavior in the test double.
- [x] Update current contract docs and repository comments.
- [x] Run full pytest with disposable PostgreSQL, ruff check, and git diff --check.
- [x] Review the complete diff and commit only feature changes locally.

## Verification record

The full PostgreSQL suite reports 688 passed and five pre-existing failures:
`test_cleanup_repository_rejects_unbounded_batch_sizes[0/True/101]` and
`test_repository_rejects_unsafe_cleanup_cutoffs[cutoffs0/cutoffs2]`.
All five reproduce on unchanged base commit 49e22d0 in a temporary checkout.
All 56 focused deletion/application/HTTP/PostgreSQL tests pass. Independent
code review found no actionable issues. Ruff and whitespace checks pass. The user explicitly approved committing with these five pre-existing failures
under feature-workflow on 2026-10-30.
