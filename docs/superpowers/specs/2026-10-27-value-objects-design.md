# Value objects and entity factories

## Intent

Move field-specific validation off entities into immutable domain value objects,
and make new-entity creation explicit through factories. Keep relationship,
inventory, and lifecycle invariants in entities and domain services.

## Approach

The preceding discussion selected dataclass value objects and entity factories.
Declarative validation with a library would reduce validation syntax but would
not by itself give fields domain types. A custom validation decorator would add
framework maintenance without helping the existing domain workflows. Neither is
part of this change.

Use frozen, slotted dataclasses with a typed `value` attribute, value equality,
and validation at construction. Proposed types are `ProductName`, `SKU`,
`StockQuantity`, `StockDelta`, `ReservationQuantity`, and `IdempotencyKey`.
StockDelta covers existing signed stock adjustments; available stock and held
reservation quantities retain their distinct zero and range rules. Do not add
UUID, timestamp, status, or pagination wrappers merely for uniformity.

## Entities and factories

- Entity fields store value objects for the selected concepts. Constructors
  enforce these types at runtime; annotations alone must not permit invalid
  primitive values to enter entities. Value objects own their content checks.
- `Product.create` converts primitive application inputs into value objects and
  generates identity and creation time without allowing historical metadata to
  be supplied. The constructor remains the validated hydration path.
- `Reservation.create` converts request inputs, generates identity, and fixes
  status to active. It accepts explicit creation and expiration timestamps from
  the existing application lifetime policy and database clock. It does not
  import application policy or recompute deadlines during hydration.
- Preserve `Confirmation.from_reservation` as the existing creation factory.
- Keep UTC normalization, expiration ordering, transition eligibility,
  idempotency conflicts, and available-stock/held-stock capacity checks explicit.
- Remove obsolete static field validators and update their callers. Preserve
  validation of complete patches before mutation, and update timestamps only
  for actual changes. Do not add a mutable/immutable base hierarchy.

## Boundaries and compatibility

Application commands, HTTP schemas, and database columns continue to carry
primitives. Convert to value objects when entering domain operations and unwrap
them in HTTP and ORM mappers. Update services, repository port contracts,
snapshots, persistence adapters, and test doubles consistently where they carry
domain values. Preserve asynchronous repository operations and existing locking,
transaction, retry, and expiration behavior. No persistence schema changes or
new dependencies are intended.

Direct Python construction of entities changes to require value objects; update
repository hydration and tests accordingly. HTTP responses and errors retain
their existing behavior. Do not silently trim text, coerce booleans to integers,
or normalize opaque idempotency keys.

## Acceptance and verification

- Test value-object bounds, invalid runtime types, immutability, equality, and
  preservation of existing name, SKU, and idempotency-key constraints.
- Test factory defaults, rejection of invalid inputs, and hydration of historical
  and terminal entities without applying new-reservation rules.
- Exercise entity operations with value objects, including patch atomicity,
  no-op timestamps, capacity, retries, and expiration boundary comparisons.
- Update and run mapping, service, use-case, API, and existing domain tests.
- Run Ruff and diff whitespace checks. Run PostgreSQL integration/race tests
  using independent transactions when configured; report unavailable checks
  explicitly and obtain any required validation exception before committing.

## Delivery

After approval, create a dedicated feature branch, implement and validate the
refactor, review the diff, and make a local commit under the feature workflow.
Publishing, pushing, and merging are outside this change.
