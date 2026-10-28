"""Track finalization and support bounded deletion of terminal history.

Legacy terminal records get a full retention window after this migration.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_retention"
down_revision: str | None = "0002_reservation_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  op.add_column("reservations", sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True))
  op.execute("UPDATE reservations SET finalized_at = statement_timestamp() WHERE status <> 1")
  op.create_check_constraint(
    op.f("ck_reservations_finalization_matches_status"),
    "reservations",
    "(status = 1 AND finalized_at IS NULL) OR (status <> 1 AND finalized_at IS NOT NULL)",
  )
  op.create_index(
    "ix_reservations_retention",
    "reservations",
    ["status", "finalized_at", "id"],
    postgresql_where=sa.text("status <> 1"),
  )


def downgrade() -> None:
  op.drop_index("ix_reservations_retention", table_name="reservations")
  op.drop_constraint(op.f("ck_reservations_finalization_matches_status"), "reservations", type_="check")
  op.drop_column("reservations", "finalized_at")
