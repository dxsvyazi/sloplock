# Snapshot-based entity updates

The approved flow is: the use case fetches an entity with its required lock,
captures an immutable snapshot, invokes a domain mutation, and passes both to
the service. The service detects changed domain fields; the repository maps the
entity and selected fields into an explicit SQL update. Use cases own transactions.

Use explicit product-detail, product-stock, and reservation-status snapshots,
defined with their repository contracts. Do not introduce generic dirty tracking
or new entity base classes. Snapshot comparison outside the entity was chosen
over entity-owned change tracking to avoid persistence bookkeeping in entities.

Product detail saves write only changed name/SKU values and the entity timestamp.
Stock corrections acquire the product lock, then read active held quantity in a
separate statement, then mutate and save stock and the entity timestamp. Unchanged
values cause no SQL update. Atomic stock deltas retain SQL arithmetic, bounds
predicates, and an explicit database timestamp.

Reservation use cases lock first, then read authoritative database time, invoke
confirm/cancel/expire, and save the status difference. SQL retains active-status
and current database deadline predicates. A rejected conditional save must not
create a confirmation or restore stock. Cleanup skips missing/ineligible holds.
Confirmations remain immutable and retain their unique/idempotent insert path.

Snapshots are not optimistic concurrency tokens: callers must hold the documented
row lock throughout fetch/mutation/save. All existing lock ordering and transaction
rollback behavior must remain intact. No API contract or schema change is needed.
