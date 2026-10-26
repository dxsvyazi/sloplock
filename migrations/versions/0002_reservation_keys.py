"""Bound reservation keys without changing existing retry identities.

Existing incompatible keys cause this migration to fail for operator review.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_reservation_keys"
down_revision: str | None = "0001_inventory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  op.create_check_constraint(
    op.f("ck_reservations_key_length_valid"),
    "reservations",
    "char_length(key) BETWEEN 1 AND 256 AND octet_length(key) <= 1024",
  )


def downgrade() -> None:
  op.drop_constraint(op.f("ck_reservations_key_length_valid"), "reservations", type_="check")
