"""Track product soft deletion and allow explicit cascading history erasure."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_product_deletion"
down_revision: str | None = "0003_retention"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def foreign_keys(*, cascade: bool) -> None:
  for table, column, parent in (
    ("reservations", "product_id", "products"),
    ("confirmations", "reservation_id", "reservations"),
  ):
    name = f"fk_{table}_{column}_{parent}"
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(name, table, parent, [column], ["id"], ondelete="CASCADE" if cascade else None)


def upgrade() -> None:
  op.add_column("products", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
  op.create_index(
    "ix_products_deleted_at_id",
    "products",
    ["deleted_at", "id"],
    postgresql_where=sa.text("deleted_at IS NOT NULL"),
  )
  foreign_keys(cascade=True)


def downgrade() -> None:
  foreign_keys(cascade=False)
  op.drop_index("ix_products_deleted_at_id", table_name="products")
  op.drop_column("products", "deleted_at")
