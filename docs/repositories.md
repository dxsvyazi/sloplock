# Repository transactions and concurrency

The three asynchronous repository adapters implement the ports in
`stocklock/domain/ports/repositories/`. They return domain values, never ORM
objects, and require an explicit transaction even for reads. They flush writes
but never commit. `SessionManager` gives each independent asyncio task its own
session and rejects nested transactions or use of a parent's session by a child
task.

`stocklock/project/persistence.py` is the Wireup composition boundary. Call
`create_persistence_container(async_sessionmaker(engine, expire_on_commit=False))`
and resolve `IUnitOfWork`, the repository ports, domain services, or individual use cases there.
The caller owns the engine and must close the container and dispose the engine
at shutdown. Resolve dependencies at the application boundary, then inject them
into handlers/use cases; do not resolve services inside business logic.

## Operations

- Products: `create`, `find_by_id`, `find_many`, `update_details`, `set_stock`,
  `adjust_stock`. `update_details` patches only supplied fields. `set_stock`
  sets an absolute available quantity, matching `CorrectProductStockCommand`.
  `adjust_stock` atomically adds a signed delta, returning `None` for a missing
  product or a result outside `0..2**31-1`. Neither operation replaces stock
  using a previously read entity.
- Reservations: `create`, `find_by_id`, `find_by_key`, `find_many`,
  `current_time`, `transition`. Lists optionally filter by product and status.
  `transition` accepts only confirmed/expired/cancelled targets, and succeeds
  only from active. Confirmation requires `now < expires_at`; expiration
  requires `now >= expires_at`. Cancellation releases any stored active hold,
  including an overdue one. Ineligible or missing transitions return `None`.
- Confirmations: `create_or_find` (`create` remains a compatibility entry point),
  `find_by_reservation_id`. Creation requires a
  confirmed reservation and returns the original result on repeated calls.
  A database unique constraint enforces one result per reservation.

Lists use ascending UUID keyset pagination: `start_id` is exclusive and `limit`
is between 1 and 100 (default 50). A list is a statement-level view; successive
pages are not a frozen snapshot of concurrently changing inventory.

The former SQLAlchemy pagination strategy arguments and unrestricted
`update(entity)`/`delete(entity)` methods were removed from the ports. There are
no current callers to migrate. Terminal reservations and confirmations cannot
be rewritten or deleted through these adapters.

## Atomic reservation workflows

Use individual application classes for operations involving multiple services:

- `ReserveProductUseCase.execute(command)` locks the product, checks its
  idempotency key, holds stock, and creates the reservation. The injected time
  policy derives the deadline from database time after locking. See
  [time policies](time-policies.md) for environment settings.
- `ConfirmReservationUseCase.execute(command)` locks the reservation, transitions
  it while eligible, and creates or returns its unique confirmation.
- `CancelReservationUseCase.execute(command)` and
  `ExpireReservationUseCase.execute(command)` transition the reservation and
  return its units. Only the winning transition returns stock; overflow rolls
  back the state change as well.

Each use case owns one transaction and depends on domain services rather than
repositories. See [services and use cases](services.md) for commands, return values,
errors, and the full set of product/query flows.

The repository primitives deliberately do not start transactions or coordinate
other repositories. Calling `create` or `transition` alone does not perform the
related stock/confirmation work. Future use cases must keep those related
changes inside the same unit of work, as the supplied workflows do.

## Locking contract

The supported baseline is PostgreSQL `READ COMMITTED`. Conditional stock updates
serialize on the product row and recheck their bounds after contention. Absolute
stock corrections and detail patches use that same row's update lock. Concurrent
absolute corrections take effect in database lock order; a correction replaces
the available quantity at that point, irrespective of historical totals.

Terminal operations lock the reservation before evaluating expiration with
PostgreSQL `clock_timestamp()`. This clock includes lock-wait time, unlike the
transaction-start `now()` clock. ORM reads and returned updates refresh cached
rows so a previously loaded entity cannot bypass a later terminal state.

Lock ordering for the supplied workflows is:

1. New reservation: product row, then insert a new reservation. Idempotency
   lookup does not lock an existing reservation.
2. Confirm: reservation row only, then insert the confirmation.
3. Cancel/expire: reservation row, then update the product row.

Do not add a path that locks a product and then locks an existing reservation:
that would invert cancellation's order. Batch operations are not provided;
future batches must acquire locks in a consistent order. Custom multi-aggregate
workflows need their own invariant/locking design. This is not a blanket
serializability guarantee for arbitrary read-then-write operations or raw SQL.
At stronger transaction isolation levels, serialization failures must propagate
and the caller must retry the entire transaction, never an individual write.

## Schema and verification

The initial Alembic revision creates all three tables, nonnegative stock,
positive quantities, valid states, expiration-after-creation checks, scoped
idempotency uniqueness, confirmation uniqueness, foreign keys, and reservation
query indexes. It targets a new database; an existing manually created schema
must be reconciled before applying this initial revision.

Set `STOCKLOCK_DATABASE_URL` to an async SQLAlchemy PostgreSQL URL and run:

```sh
uv run alembic upgrade head
```

Integration tests require a disposable PostgreSQL database with schema creation
permission. They create a unique schema per test and remove it afterward; they
do not clear application tables. Set `STOCKLOCK_TEST_DATABASE_URL`, then run:

```sh
uv run pytest -q
uv run ruff check stocklock tests migrations
```

Without that test URL, database tests are explicitly skipped. The suite covers
independent competing transactions, oversubscription, reservation retries,
confirmation retries, cancellation/expiration races, competing terminal states,
lock waits across expiration, stale ORM rows, stock bounds and corrections,
database failure rollback, and migration upgrade/model parity/downgrade.
These changes provide persistence and application workflows; HTTP handlers and a separately launched expiration worker use these workflows.

## Correction headroom and due selection

`set_stock` locks the product and then sums all stored active holds in a separate
statement. At READ COMMITTED, that statement observes reservations committed
while the product lock was awaited. It rejects corrections whose available
quantity plus active held quantity exceeds the supported stock range. It never
locks reservation rows, preserving terminal operations' reservation-first order.
Raw SQL and incomplete repository-only workflows remain outside this guarantee.

`find_due_ids` selects active holds with deadlines at or before database wall
time, ordered by UUID with an exclusive cursor. It takes no row locks; expiry
rechecks eligibility in the existing per-reservation transaction. Multiple
workers may select the same IDs safely.
