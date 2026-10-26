"""Create inventory, reservation and confirmation tables with concurrency constraints."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_inventory"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
  op.create_table(
    "products",
    sa.Column("id", sa.Uuid(), nullable=False),
    sa.Column("name", sa.String(256), nullable=False),
    sa.Column("sku", sa.String(), nullable=False),
    sa.Column("stock_quantity", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint("id", name="pk_products"),
    sa.CheckConstraint("stock_quantity >= 0", name=op.f("ck_products_stock_nonnegative")),
  )
  op.create_table(
    "reservations",
    sa.Column("id", sa.Uuid(), nullable=False),
    sa.Column("product_id", sa.Uuid(), nullable=False),
    sa.Column("quantity", sa.Integer(), nullable=False),
    sa.Column("status", sa.SmallInteger(), nullable=False),
    sa.Column("key", sa.String(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint("id", name="pk_reservations"),
    sa.ForeignKeyConstraint(["product_id"], ["products.id"], name="fk_reservations_product_id_products"),
    sa.UniqueConstraint("product_id", "key", name="uq_reservations_product_id"),
    sa.CheckConstraint("quantity > 0", name=op.f("ck_reservations_quantity_positive")),
    sa.CheckConstraint("status IN (1, 2, 3, 4)", name=op.f("ck_reservations_status_valid")),
    sa.CheckConstraint("expires_at > created_at", name=op.f("ck_reservations_expiration_after_creation")),
  )
  op.create_index("ix_reservations_product_id_status_id", "reservations", ["product_id", "status", "id"])
  op.create_index("ix_reservations_status_expires_at", "reservations", ["status", "expires_at"])
  op.create_table(
    "confirmations",
    sa.Column("id", sa.Uuid(), nullable=False),
    sa.Column("reservation_id", sa.Uuid(), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint("id", name="pk_confirmations"),
    sa.ForeignKeyConstraint(
      ["reservation_id"], ["reservations.id"], name="fk_confirmations_reservation_id_reservations"
    ),
    sa.UniqueConstraint("reservation_id", name="uq_confirmations_reservation_id"),
  )


def downgrade() -> None:
  op.drop_table("confirmations")
  op.drop_index("ix_reservations_status_expires_at", table_name="reservations")
  op.drop_index("ix_reservations_product_id_status_id", table_name="reservations")
  op.drop_table("reservations")
  op.drop_table("products")
