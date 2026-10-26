# Domain services and application use cases

Domain services expose individual business operations and enforce their rules.
They depend on asynchronous repository ports, return domain entities, and contain
no HTTP, SQLAlchemy, or Wireup imports. They require a caller-owned transaction;
they never open or commit one themselves.

Use cases compose service operations into a complete business flow. Each is a
separate class with `execute(command)`, and each opens one `IUnitOfWork.begin()`
scope, including read flows because repositories require a transaction.

## Domain services

| Service | Operations |
| --- | --- |
| `ProductService` | `create`, `require`, `list`, `update_details`, `correct_stock`, `hold_stock`, `return_stock` |
| `ReservationService` | `require`, `list`, `find_retry`, `current_time`, `create`, `confirm`, `cancel`, `expire` |
| `ConfirmationService` | `get`, `require`, `create` |

Products validate names, SKUs, and integer stock bounds. Stock correction sets an
absolute available quantity. Holding and returning units require a positive
quantity and use conditional database updates, preventing lost updates and
negative stock. Product patches accept only name and/or SKU and preserve stock.

Reservations validate positive quantities, keys, and aware expiration timestamps.
Application creation supplies one authoritative database instant for creation and
expiration, and stores UTC timestamps. Direct service callers may omit `created_at`
to read database time inside `create`. The pure
`can_transition` rule remains available independently. Terminal service operations
lock the reservation before evaluating eligibility; the adapter rechecks time and
state at the write boundary. Confirmation requires `now < expires_at`, expiration
requires `now >= expires_at`, and cancellation accepts any stored active hold,
including an overdue hold. Terminal states never return to active.

Confirmation creation requires a confirmed reservation. The adapter verifies its
persisted status and enforces one immutable confirmation per reservation.
`get` returns the result or None; `require` raises `MissingConfirmation` when a confirmed
reservation lacks its expected result.

Service operations alone are not complete cross-resource workflows. In
particular, `hold_stock` and reservation `create` must share a transaction;
`cancel`/`expire` must share a transaction with `return_stock`; `confirm` must share
one with confirmation `create`. Use the application classes for these flows.

## Application use cases

| Module | Class | Command |
| --- | --- | --- |
| `application/usecases/products.py` | `CreateProductUseCase` | `CreateProductCommand` |
| | `GetProductUseCase` | `GetProductCommand` |
| | `ListProductsUseCase` | `ListProductsCommand` |
| | `UpdateProductUseCase` | `UpdateProductCommand` |
| | `CorrectProductStockUseCase` | `CorrectProductStockCommand` |
| `application/usecases/reservations.py` | `ReserveProductUseCase` | `CreateReservationCommand` |
| | `GetReservationUseCase` | `GetReservationCommand` |
| | `ListReservationsUseCase` | `ListReservationsCommand` |
| | `ListProductReservationsUseCase` | `ListProductReservationsCommand` |
| | `CancelReservationUseCase` | `CancelReservationCommand` |
| | `ExpireReservationUseCase` | `ExpireReservationCommand` |
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

Cancellation/expiration return the transitioned reservation or None when missing
or ineligible. Only a successful transition returns units. A stock overflow
raises `StockLimitExceeded`, rolling back the transition. Other required entity
lookups raise `NotFound`; an ineligible confirmation raises
`ReservationUnavailable`. Invalid input raises `ValidationException` (a `ValueError`). HTTP translation
remains an adapter responsibility.

Read flows preserve optional status filters and ascending UUID pagination.
Product reservation lists require that the product exists. Confirmation retrieval
requires that the reservation exists and returns None when no result exists.

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
class's `execute(command)`. No service/use-case abstraction is added until there
is an actual need for multiple implementations.

See [repository transactions](repositories.md) for lock order, database isolation,
constraints, and PostgreSQL test setup. Domain tests use in-memory repository
doubles; only the PostgreSQL tests demonstrate concurrent transaction behavior.

## Review fixes

The concrete `SqlAlchemyUnitOfWork` lives in infrastructure and implements the
application port. Domain entities are plain dataclasses; transport and persistence
mapping remains explicit at each boundary. Product patches use `ProductDetailsPatch`.

Corrections reject `available + stored active held quantity > MAX_STOCK_QUANTITY`.
The adapter reads holds in a fresh statement after locking the product, without
locking reservations. Overdue active holds still need return capacity.

Keys preserve exact identity, with 1–256 Unicode characters and at most 1,024
UTF-8 bytes. NUL and surrounding whitespace are rejected at input boundaries.

`ListDueReservationsUseCase` selects bounded due IDs in a read transaction. The
infrastructure expiration worker releases that scope before invoking one expiry
use case per candidate. Each failure rolls back only that hold, is logged, and
does not prevent later pages progressing. Confirmation and cancellation continue
to coordinate through the same reservation locks.

Worker database operations have a 30-second timeout. A locked or failed hold
rolls back and is revisited on a later sweep; later candidates continue. Compose
allows 35 seconds for graceful worker shutdown.
