# Soft deletion with active reservations

Approved in conversation on 2026-10-30.

Allow administrators to soft-delete products with stored active reservations,
including overdue holds, to stop new reservations immediately. Existing holds
can confirm before expiry, cancel, or expire normally; stock returns remain
atomic and occur once. Hard deletion continues to reject all stored active holds.

## Approach

Reuse deleted_at and the existing product lock. Restrict the active-hold guard
to hard deletion. Allow positive lifecycle stock returns to hidden products;
keep stock decrements, administrative corrections, and detail edits blocked.
This is smaller than introducing a separate availability state, which would
add an unnecessary API and schema change for the requested behavior.

Soft deletion preserves history and its original timestamp on retries. Creation
retries still return not found for hidden products, as before. Product cleanup
still requires no reservations. No migration or endpoint change is needed.

Verify domain/application behavior, real HTTP responses, PostgreSQL stock returns
and rollback, worker expiration, and independent-transaction deletion races.
Update AGENTS.md and current user/developer docs to match this contract.
