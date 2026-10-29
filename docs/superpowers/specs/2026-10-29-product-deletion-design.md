# Administrative product deletion

## Intent and agreed behavior

Administrators can soft-delete products or explicitly erase them and their history.
Both modes reject products with any stored active reservation, including overdue
holds. Soft deletion preserves terminal reservations, confirmations, and successful
confirmation retries. Hard deletion intentionally overrides historical retention;
subsequent product, reservation, confirmation, and confirmation-retry requests
return not found. Neither mode changes stock or cancels reservations implicitly.

Keep HTTP adapters thin, transaction boundaries in application use cases, and SQL
and concurrency controls in repositories. Authentication belongs at the HTTP
boundary; application use cases remain reusable from a future CLI. No administrative CLI is part of this change; product garbage collection gets
its own worker process.

## Approaches

- Physical deletion only would either forbid deletion while history exists or
  erase history on every deletion. It does not provide the agreed routine path.
- Soft deletion only preserves history but cannot perform explicit administrative
  history erasure.
- Chosen: soft deletion by default, explicit hard deletion, and independent
  automatic product retention that waits for reservation cleanup.

## Proposed HTTP and authentication contract

The following concrete API choices are proposed by the implementer for approval.
All paths use the existing `/api/v1` prefix.

- `DELETE /products/{product_id}?mode=soft|hard`, default `soft`, requires an admin
  bearer token. Return an empty 204 on success, 404 for an unknown product, 409
  when any stored active reservation exists, and 422 for invalid input. Hard
  deletion works for visible or soft-deleted products. Repeating soft deletion
  returns 204 without changing the original deletion timestamp; repeating hard
  deletion returns 404.
- Configure `ADMIN_API_TOKEN` as a secret setting with no usable default. Use
  constant-time credential comparison. Missing or incorrect bearer credentials
  return 401 with a bearer challenge; unconfigured admin access returns 503 and
  cannot authorize any operation. Never include credentials in responses or logs.
  This introduces one shared administrative credential, not a user/role system.
- Product lists accept `visibility=visible|deleted|all`, default `visible`.
  `deleted` and `all` require admin authentication.
- Product detail requests accept `include_deleted=true` for authenticated admins;
  otherwise deleted products return 404. Product responses add nullable UTC
  `deleted_at` so administrative clients can distinguish deleted records.
- Global reservation lists accept `product_visibility=visible|deleted|all`,
  default `all`, preserving existing historical results. Explicit `deleted`
  filtering requires admin authentication. Existing status filtering and UUID
  cursor pagination compose with visibility filtering before limiting rows.
- Product-specific reservation lists retain access to history for soft-deleted
  products; their existing product ID already selects the product, so no extra
  visibility filter is necessary. Direct reservation and confirmation reads and
  repeated successful confirmations remain accessible under existing rules.
- Reserving, editing details, and correcting stock on a soft-deleted product
  return 404, including attempts to retry reservation creation by idempotency key.
  Restoration is outside scope. Other existing endpoints retain their current
  authentication behavior.

## Domain, persistence, and concurrency

Add nullable timezone-aware `deleted_at` to the product domain entity and ORM,
with validation and an idempotent domain deletion operation. Persist a database
UTC instant supplied through the existing application clock. Preserve product
identity, details, available stock, and existing SKU behavior. Do not introduce
new SKU uniqueness or reuse rules.

An application deletion use case opens one transaction, locks the product, checks
for stored active reservations in a separate statement after acquiring the lock,
and either persists the soft deletion or erases the product. Reuse the same product
lock as reservation creation and stock correction. New reservations either commit
before deletion's check and cause rejection, or wait and observe deletion.

Do not acquire active reservation row locks after taking the product lock:
cancellation and expiration already lock reservation then product. An MVCC active
existence query must conservatively reject an uncommitted terminal transition;
an administrator may retry after that transition commits. Never treat an overdue
active reservation as terminal just because its deadline has elapsed.

Add a migration for `deleted_at`, a suitable deleted-product retention index, and
database `ON DELETE CASCADE` foreign keys from reservations to products and from
confirmations to reservations. The guarded hard-delete use case is the supported
application erasure path; cascade is an infrastructure mechanism, not permission
to bypass the active-reservation rule. Preserve all existing constraints and
support migration downgrade without attempting to restore erased data.

Deletion and edits must recheck persisted visibility under the lock. Existing
terminal confirmation retry operations may race hard deletion: a retry that
serializes before erasure may succeed; after erasure commits it returns 404.
Automatic cleanup and explicit erasure must safely tolerate each other's deletes.

## Product garbage collection

Add `DELETED_PRODUCT_RETENTION_SECONDS`, proposed default 2,592,000 (30 days),
measured from `deleted_at`; zero disables automatic product removal. This setting
does not override expired, cancelled, or confirmed reservation retention.

Run product cleanup in its own worker, separate from reservation retention, as
requested in the approval amendment. Each product cleanup transaction selects
only soft-deleted products at or before the UTC cutoff with no reservations of
any status, locks eligible product rows using `SKIP LOCKED`, and deletes at most
the configured batch size. Recheck eligibility in the delete. Never remove visible
products or change stock. A retained reservation, including indefinitely retained
history, prevents automatic product removal.

Use dedicated `PRODUCT_CLEANUP_INTERVAL_SECONDS`, `PRODUCT_CLEANUP_BATCH_SIZE`,
`PRODUCT_CLEANUP_MAX_BATCHES`, and `PRODUCT_CLEANUP_OPERATION_TIMEOUT_SECONDS`
settings with defaults 86400, 100, 100, and 30 respectively. Product cleanup runs
independently of reservation retention; each disabled worker exits without a
connection. Add a Compose service with graceful shutdown and migration dependency.

Introduce an abstract `BaseWorker` containing container, interval, batch size,
maximum batches, operation timeout, and an `exception_message` class attribute.
It validates common limits, declares abstract `_run_once`, and defines `run` with
stop-aware interval waits, exception logging using the configured message, retry,
and cancellation propagation. Preserve public `run_once` as a compatibility wrapper
around `_run_once`. Expiration, reservation retention, and product cleanup derive
from this base. The exception message is logged on failure, rather than raised as
an exception itself, preserving the existing worker retry behavior.

## Validation and documentation

Test framework-independent domain deletion and timestamp behavior; application
transaction boundaries and rollback; HTTP authentication, filters, validation,
errors, and empty 204 responses; ORM mapping and migration upgrade/downgrade;
and independent PostgreSQL transaction races for deletion versus reservation
creation, terminal transitions, edits, hard deletion, and cleanup. Cover hard
cascade atomicity, confirmation retry behavior, and retained history blocking
automatic product removal. Keep existing reservation and inventory race coverage.

Update README, service/repository/time-policy documentation, `.env.example`, and
the repository guide to describe the explicit administrative exceptions to the
previous product-retention rules. Do not put real tokens in files or commits.
Run Ruff, pytest including PostgreSQL checks when infrastructure is available,
and whitespace checks. Report actual gaps; unavailable required validation needs
an explicit exception before a final local commit under the feature workflow.

## Delivery

After design approval, create a dedicated `feature-product-deletion` branch from
the current clean `main` at `c802e57`, write the implementation plan, implement,
review, validate, and create a local commit. No push or deployment is included.
Internal naming, repository method decomposition, and test fixture organization
are left to the builder within these contracts.
