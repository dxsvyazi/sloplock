# Domain services and application use cases

Update use cases fetch with `for_update=True`, capture an immutable snapshot,
and invoke the entity's domain operation. Services compare the resulting entity
with its snapshot and delegate restricted writes to repositories. The snapshot
types live beside the repository ports: `ProductDetailsSnapshot`,
`ProductStockSnapshot`, and `ReservationSnapshot`. They are scoped to one kind of
mutation and are not optimistic concurrency tokens; the lock must span the whole
operation in the same transaction.

Terminal use cases read database wall time after acquiring the reservation lock,
then invoke `confirm`, `cancel`, or `expire` on the entity and pass the result to
`ReservationService.save_transition`. Cleanup uses the same flow with an optional
locked lookup. Repositories recheck active status and database deadlines before
saving. No second full reservation fetch or adapter-side entity mutation is needed.

Domain entities own business validation and state changes. Domain services coordinate persistence operations.
They depend on asynchronous repository ports, return domain entities, and contain
no HTTP, SQLAlchemy, or Wireup imports. They require a caller-owned transaction;
they never open or commit one themselves.

Use cases compose service operations into a complete business flow. Each is a
separate class with `execute(command)`, and each opens one `IUnitOfWork.begin()`
scope, including read flows because repositories require a transaction. Use cases construct
validated entities before passing them to `ProductService.create(product)`,
`ReservationService.create(reservation)`, or `ConfirmationService.create(confirmation)`.
Services do not choose entity identity, mutation timestamps, or lifetime. A net
no-op returns the persisted update timestamp from its snapshot, even when an
entity was changed and then reverted before saving.

## Rich entities

Public entity fields are read-only. Product and Reservation use frozen dataclass
assignment protection, with internal writes restricted to explicit domain methods.
They remain mutable through those methods and are deliberately unhashable.
Confirmation is immutable. Immutable value objects validate product names, SKUs,
stock quantities, stock deltas, reservation quantities, and idempotency keys.
Constructors require the corresponding value-object types and validate identities,
states, timestamp ordering, and UTC awareness without web or persistence frameworks.

`Product.create(name=..., sku=..., stock_quantity=...)` accepts primitives and
creates new identity and timestamps. `Reservation.create(product_id=...,
quantity=..., key=..., created_at=..., expires_at=...)` accepts primitives and
creates an active hold with a new identity. Its caller supplies the authoritative
clock and policy-derived deadline. `Confirmation.from_reservation` remains the
confirmation creation factory. Repositories hydrate historical entities through
typed constructors, preserving persisted identity, status, and timestamps.

```python
from stocklock.domain.entities.product import Product
from stocklock.domain.value_objects.product import ProductName, StockDelta, StockQuantity

product = Product.create(name="Widget", sku="W1", stock_quantity=5)
product.update_details({"name": ProductName("Renamed")})
product.adjust_stock(StockDelta(-1))
product.correct_stock(StockQuantity(3), held_quantity=1)
assert product.stock_quantity.value == 3
```

Value objects compare by type and value and expose primitives through `.value`.
StockQuantity allows zero; ReservationQuantity requires a positive integer.
StockDelta accepts signed integer adjustments. Booleans and numeric coercion are
rejected. Text and opaque keys are preserved exactly, including case; surrounding
whitespace is rejected at the domain boundary. HTTP schemas retain their existing
normalization behavior. ORM and HTTP mappers explicitly unwrap values; database
columns and public response formats are unchanged.

- `Product.update_details(details)` validates the whole patch before changing anything.
  Actual changes update `updated_at`; no-op patches preserve it.
- `Product.correct_stock(quantity, held_quantity=...)` validates nonnegative stock and
  capacity to return every active hold. `Product.adjust_stock(delta)` enforces stock bounds.
  These methods change the in-memory entity. Persisted deltas still use SQL arithmetic;
  atomic deltas retain database-generated `updated_at` timestamps. Absolute stock
  corrections persist the entity timestamp and skip unchanged writes.
- `Reservation.can_transition(target, now)`, `transition(target, now)`, `confirm(now)`,
  `cancel(now)` and `expire(now)` own lifecycle rules. `transition`, `cancel` and
  `expire` return a success flag; `confirm` raises on an ineligible transition.
  `ensure_retry(quantity)` checks idempotency compatibility.
- `Confirmation.from_reservation(reservation)` requires a confirmed reservation.
  The confirmation use case invokes this factory after the successful transition.

Constructors also support rehydrating valid history: overdue active reservations and
terminal statuses are accepted, with `expires_at > created_at` required. Insertion
additionally calls `Reservation.ensure_new()` to reject terminal reservations.
All aware timestamps normalize to UTC; naive timestamps are rejected.

## Domain services

| Service | Operations |
| --- | --- |
| `ProductService` | `create`, `require`, `list`, `save_details`, `active_held_quantity`, `save_stock`, `hold_stock`, `return_stock` |
| `ReservationService` | `get`, `require`, `list`, `list_due_ids`, `find_retry`, `current_time`, `create`, `save_transition` |
| `ConfirmationService` | `get`, `require`, `create` |

Product value objects validate names, SKUs, and integer stock bounds. Stock correction sets an
absolute available quantity. Holding and returning units require a positive
quantity and use conditional database updates, preventing lost updates and
negative stock. Product patches accept only name and/or SKU and preserve stock.

Reservation value objects validate positive quantities and keys; entities validate aware expiration timestamps.
Application creation supplies one authoritative database instant for creation and
expiration, and stores UTC timestamps. Direct callers construct a `Reservation`
with typed fields and explicit creation and expiration instants, or call its
creation factory with primitive fields; the service accepts that entity.
The pure eligibility rule is `reservation.can_transition(target, now)`. Terminal
use cases mutate the locked entity. The service detects a status change and the
adapter checks time and stored state in the write predicate. Confirmation requires `now < expires_at`, expiration
requires `now >= expires_at`, and cancellation accepts any stored active hold,
including an overdue hold. Terminal states never return to active.

Confirmation creation requires a confirmed reservation. The adapter verifies its
persisted status and enforces one immutable confirmation per reservation.
`get` returns the result or None; `require` raises `MissingConfirmation` when a confirmed
reservation lacks its expected result.

Service operations alone are not complete cross-resource workflows. In
particular, `hold_stock` and reservation `create` must share a transaction;
terminal `save_transition` must share a transaction with `return_stock` for
cancellation/expiration or confirmation `create` for confirmation. Use the
application classes for these flows.

## Application use cases

| Module | Class | Command |
| --- | --- | --- |
| `application/usecases/product.py` | `CreateProductUseCase` | `CreateProductCommand` |
| | `GetProductUseCase` | `GetProductCommand` |
| | `ListProductsUseCase` | `ListProductsCommand` |
| | `UpdateProductUseCase` | `UpdateProductCommand` |
| | `CorrectProductStockUseCase` | `CorrectProductStockCommand` |
| `application/usecases/reservation.py` | `ReserveProductUseCase` | `CreateReservationCommand` |
| | `GetReservationUseCase` | `GetReservationCommand` |
| | `ListReservationsUseCase` | `ListReservationsCommand` |
| | `ListProductReservationsUseCase` | `ListProductReservationsCommand` |
| | `CancelReservationUseCase` | `CancelReservationCommand` |
| | `ExpireReservationUseCase` | `ExpireReservationCommand` |
| | `TryExpireReservationUseCase` | `ExpireReservationCommand` |
| `application/usecases/confirmations.py` | `ConfirmReservationUseCase` | `ConfirmReservationCommand` |
| | `GetConfirmationUseCase` | `GetConfirmationCommand` |

`ReserveProductUseCase.execute(command)` receives a command with product ID,
quantity, and idempotency key. The use case's injected `ReservationTimePolicy`
derives the deadline from database UTC time after acquiring the product lock and
holding stock. Creation and expiration share the same instant, so lock waits do
not shorten the configured lifetime. The default is 900 seconds; see
[time policies](time-policies.md) for environment configuration. A separate expiration worker invokes the guarded expiry workflow; Compose starts it.

Reservation creation locks the product, checks its scoped idempotency key, holds
units, and creates the reservation in one transaction. A matching retry returns
the original reservation, including its terminal status, without changing stock;
a changed quantity raises `IdempotencyConflict`. Retrying does not extend expiry.

Confirmation locks the reservation and returns the original confirmation for an
already confirmed hold. Otherwise it transitions the hold and creates its result
in the same transaction. It never decrements available stock again.

Cancellation and explicit expiration lock the reservation and raise `ReservationNotFound`
when absent or `ReservationUnavailable` when ineligible. Successful requests return
the transitioned reservation. Worker cleanup uses `ExpireReservationsUseCase`
for each page, with `TryExpireReservationUseCase` as fallback on batch failure.
The individual fallback returns None for missing or ineligible candidates,
including holds another transaction already processed. Only a successful transition returns units. A stock overflow
raises `StockLimitExceeded`, rolling back the transition. Other required entity
lookups raise `NotFound`; an ineligible confirmation raises
`ReservationUnavailable`. Invalid input raises `ValidationException` (a `ValueError`). HTTP translation
remains an adapter responsibility.

Read flows preserve optional status filters and ascending UUID pagination.
Product reservation lists require that the product exists. Confirmation retrieval
requires that the reservation exists and raises `ConfirmationNotFound` when no result exists.
This is distinct from `MissingConfirmation`, which signals an inconsistent confirmed hold.
Controllers only map inputs and successful outputs; registered exception handlers map
`NotFound` subclasses to HTTP 404 and `ReservationUnavailable` to HTTP 409.

## Composition and migration

Resolve services and individual use cases through
`project.persistence.create_persistence_container(session_maker)` at the
composition boundary. They share repository adapters and a task-owned
SessionManager. Do not resolve dependencies from inside domain/application code,
and do not wrap a use case in another transaction; nested scopes are rejected.

Container creation loads `TimePolicySettings` from the environment and `.env`.
Pass `time_settings=TimePolicySettings(...)` to supply an explicit configuration.
Wireup injects an immutable application policy; business code does not import
settings or read environment variables.

The grouped `ReservationUseCases` class has been replaced by individual classes.
Replace its `reserve`, `confirm`, `cancel`, and `expire` calls with the corresponding
class's `execute(command)`. Worker cleanup should use `TryExpireReservationUseCase`
when an ineligible candidate is an expected no-op. No service/use-case abstraction is added until there
is an actual need for multiple implementations.

See [repository transactions](repositories.md) for lock order, database isolation,
constraints, and PostgreSQL test setup. Domain tests use in-memory repository
doubles; only the PostgreSQL tests demonstrate concurrent transaction behavior.

## Review fixes

The concrete `SqlAlchemyUnitOfWork` lives in infrastructure and implements the
application port. Domain entities validate construction and expose guarded mutation methods; transport
and persistence mapping remains explicit at each boundary. Product patches use
`ProductDetailsPatch`, defined alongside Product.

Corrections reject `available + stored active held quantity > MAX_STOCK_QUANTITY`.
The adapter reads holds in a fresh statement after locking the product, without
locking reservations. Overdue active holds still need return capacity.

Keys preserve exact identity, with 1–256 Unicode characters and at most 1,024
UTF-8 bytes. NUL and surrounding whitespace are rejected at input boundaries.

`ListDueReservationsUseCase` selects bounded due IDs in a read transaction. The
infrastructure expiration worker releases that scope before invoking
`ExpireReservationsUseCase` once per page. The bulk repository primitive skips
locked rows and transitions only active, due holds. `ProductService.return_stock_many`
groups returned quantities and updates products in UUID order. All changes commit
together; a batch failure rolls back before individual fallback, preserving later
page progress. Confirmation and cancellation coordinate through the same reservation locks.

Worker database operations have a 30-second timeout. Locked holds are skipped;
failed batches roll back and retry individually. Later sweeps revisit skipped
or failed holds. Compose
allows 35 seconds for graceful worker shutdown.

## Validation ownership

Mutation inputs are validated by the entity operation, without preflight validation
in services or adapters. Missing products return not found before mutation-input
validation. Reservation insertion calls `ensure_new` in the adapter; transition
eligibility is evaluated in the use case through the entity after locking, with
SQL predicates retained for write-time races.
Mappers pass timestamps through; constructors validate and normalize hydrated data,
and entity timestamps are already UTC when mapped to storage. Query parameters,
positive hold/return requests and atomic SQL delta bounds retain their own checks.

Application commands are immutable data carriers without validation hooks. HTTP schemas
validate transport input; entities and services validate when a use case executes.
Services trust UUID-typed identifiers and cursors supplied by callers; HTTP adapters
validate their transport representation, and entity constructors validate stored identities.
Direct callers receive business validation errors from `execute`, rather than from
command construction. Invalid execution rolls back its transaction.
