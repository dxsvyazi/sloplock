# Bulk expiration

Implement the bulk expiration proposal accepted in chat. Retention is out of scope.

The worker keeps its bounded, cursor-based candidate sweep. Each page is expired
in one application-owned transaction through a new ExpireReservationsUseCase.
A repository operation selects only requested, active, due reservations using
FOR UPDATE SKIP LOCKED, conditionally updates their status, and returns changed
reservations. ProductService groups returned quantities and restores stock once
per product, ordered by UUID, using existing bounded atomic increments.

This preserves reservation-first locking shared with cancellation/confirmation.
Only successfully transitioned rows contribute stock. Any stock return failure
rolls back the entire page. The worker then falls back to existing individual
expiration for that page, preserving failure isolation and cursor advancement.
Timeouts and shutdown cancellation continue to release transactions/scopes.

Alternatives: per-reservation transactions retain current overhead; unbounded
bulk updates retain locks too long. Bounded batches balance transaction overhead,
contention, and rollback size. Stock restoration remains one update per distinct
product to reuse existing stock bounds and guarantee deterministic lock order.

No schema or HTTP changes. Preserve asynchronous ports, UUIDs, Python >=3.13,
framework-independent domain code, and existing user edits. Validate concurrent
workers, locked candidates, terminal/deadline filtering, grouped returns, rollback,
failure fallback, cancellation, and sweep bounds against PostgreSQL.
