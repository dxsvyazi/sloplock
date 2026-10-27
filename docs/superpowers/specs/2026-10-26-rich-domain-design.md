# Rich domain entities

Approved approach: read-only public fields and explicit, validated mutation methods.
The user also requires entity construction in use cases, with services accepting entities.

Product owns detail validation, atomic in-memory detail changes, stock bounds and return
capacity, and update timestamps. Reservation owns valid construction, retry compatibility,
and irreversible terminal transitions using an explicit UTC instant. Confirmation is
immutable and provides a factory requiring a confirmed reservation. Rehydration accepts
valid historical terminal states and overdue active holds; it never compares creation to
wall time. Services retain lookups, query input validation and persistence coordination.

Repositories retain SQL arithmetic and bounds predicates, reservation locks and deadline
predicates, active-hold aggregation after product locking, and confirmation uniqueness.
These are concurrency protections, not substitutes for entity invariants. Use cases own
transactions and construct products, reservations and confirmation results. Preserve the
HTTP contract, UUID conventions, absolute stock correction and existing schema.

Alternative considered: immutable copies returned for every change. Explicit mutation
methods better match the requested entity ownership and existing workflows. Dataclass
fields are frozen to callers; only validated entity methods modify them internally.

Verify direct construction, failed multi-field updates, forbidden direct assignments,
UTC normalization, retry conflicts, deadline equality, terminal irreversibility, mapping,
rollback, and PostgreSQL races. No new dependencies or migrations are required.
