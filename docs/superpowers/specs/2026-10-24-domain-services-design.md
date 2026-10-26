# Domain services and individual use cases

## Intent and scope

Implement the user's architecture: domain services enforce invariants and expose individual domain operations; application use cases compose those operations into business flows. Each use case is an individual class. This covers product, reservation, and confirmation operations described in AGENTS.md. HTTP handlers, an expiration scheduler, and new API policies are outside this change.

## Approach

The user selected repository-backed domain services composed by application use cases. Pure entity-only services would leave repository-dependent rules in use cases; services owning entire transactional workflows would conflict with the requested division of responsibilities. Services depend on domain repository ports and framework-independent validation only. They neither open nor commit transactions. Use cases depend on services and the existing application unit-of-work port, never on concrete repositories.

No additional service or use-case interfaces are needed while each has one implementation. Introduce interfaces when there is an actual need for interchangeable implementations. Dependency injection remains in project/persistence.py; no wireup, SQLAlchemy, FastAPI, or application imports enter the domain.

## Domain operations

### ProductService

- Create a product: validate name, SKU, and nonnegative initial stock, then persist it.
- Get a product, optionally requesting a repository lock: raise NotFound when absent.
- List products using the existing UUID pagination contract.
- Update supplied product details, validating the patch and raising NotFound when absent.
- Correct stock to an absolute nonnegative quantity using the existing serialized set_stock operation.
- Hold a positive quantity using the repository's conditional atomic decrement; raise InsufficientStock on insufficient units.
- Return a positive quantity using the repository's conditional increment; raise StockLimitExceeded on overflow.

Stock mutations must not replace stock using a read entity. Holding and returning stock are individual operations; reservation lifecycle orchestration belongs in use cases.

### ReservationService

- Get a reservation, optionally requesting a lock; raise NotFound when absent.
- List reservations with optional product/status filters and existing pagination.
- Look up a product-scoped idempotency key and enforce matching quantity when a result exists.
- Obtain authoritative UTC time from the repository, including time spent waiting on locks.
- Create an active reservation with positive quantity, valid key, aware UTC timestamps, and future expiration.
- Confirm an eligible reservation through the repository's guarded transition; raise ReservationUnavailable when ineligible.
- Cancel or expire through guarded transitions, returning the changed reservation or None when missing/ineligible.
- Preserve the existing pure can_transition rule and enforce terminal eligibility through the repository's lock and conditional write.

Creation does not decrement stock; terminal transitions do not return stock or create confirmations. Those related operations must be composed within a use-case transaction.

### ConfirmationService

- Find a confirmation by reservation ID, returning None when unavailable.
- Require an existing result for a confirmed reservation; absence indicates inconsistent persisted state.
- Create or retrieve the unique immutable confirmation for a confirmed reservation. Reject an ineligible reservation before persistence and retain database uniqueness and repository-side status enforcement.

## Application flows

Each class exposes execute and uses one explicit unit-of-work transaction, including reads because the current adapters require an active transaction. Group modules by resource while keeping every flow a separate class:

- CreateProductUseCase, GetProductUseCase, ListProductsUseCase, UpdateProductUseCase, CorrectProductStockUseCase.
- ReserveProductUseCase, GetReservationUseCase, ListReservationsUseCase, ListProductReservationsUseCase, CancelReservationUseCase, ExpireReservationUseCase.
- ConfirmReservationUseCase, GetConfirmationUseCase.

Use existing application command dataclasses where available. Reservation creation additionally accepts an explicit aware expires_at; the lifetime policy remains the caller's responsibility. Expiration accepts a reservation identifier. No new lifetime default or HTTP contract is introduced.

Reserve: lock and require the product, inspect the idempotency key without locking an existing reservation, return a matching original reservation, otherwise obtain current time, validate expiration, hold units, and create the reservation.

Confirm: lock and require the reservation. If already confirmed, require and return its original confirmation. Otherwise perform the eligible confirmation transition, then create/retrieve its confirmation. Never decrement stock again.

Cancel/expire: perform the guarded terminal transition; return None if it did not succeed. If successful, return the held units. A failure returning stock rolls back the transition.

Product reservation listing first requires the product, then lists its reservations. GetConfirmation requires the reservation and returns its result or None. Other read/update flows delegate to the corresponding domain service.

## Compatibility and persistence

Replace the grouped ReservationUseCases class and migrate its internal callers, wiring, documentation, and tests to individual classes. No external application integration currently uses it. Preserve existing retry semantics and cancel/expire None results.

Reconcile ConfirmationRepository.create with IConfirmationRepository.create_or_find, preserving the existing direct repository entry point if required by repository tests. Correct outdated product patch calls in tests to use details. These are required integration fixes, not schema changes.

Keep existing database constraints and lock ordering: reserve locks product then inserts a new reservation; confirm locks reservation; cancel/expire lock reservation then product. Never lock an existing reservation after locking its product. The existing post-lock database clock and conditional transition remain authoritative against expiration races. No schema migration is needed.

## Validation

Add framework-independent domain service tests using repository doubles to cover validation, missing entities, stock bounds, lifecycle eligibility, idempotency conflicts, and immutable confirmation results. Add use-case tests that check orchestration, transaction ownership, and error propagation rather than merely duplicating implementation calls. Update and run existing PostgreSQL race/rollback tests through the individual use cases, and verify composition wiring. Run Ruff and the available test suite. Report database skips explicitly if PostgreSQL is unavailable; mocks do not demonstrate database race safety.

## Implementation choices and risks

The execute method name, resource-grouped modules, absolute stock correction, and no speculative interfaces are proposed implementation choices. Absolute correction and caller-provided expiration preserve existing command/workflow behavior. Domain validation must remain independent of application command types; reusable business validation can move into domain modules with application commands delegating to it. Standalone service writes require a caller-owned transaction and are deliberately not complete cross-resource flows. Document this contract to prevent accidental partial workflows.
