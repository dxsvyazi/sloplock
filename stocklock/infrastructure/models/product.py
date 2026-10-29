from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from stocklock.infrastructure.models.base import BaseORM
from stocklock.shared.constraints import MAX_PRODUCT_NAME_LEN
from stocklock.shared.sqlalchemy.mixins import IdUUIDMixin, TimeMetricsMixin


class ProductORM(BaseORM, IdUUIDMixin, TimeMetricsMixin):
  __tablename__ = "products"
  __table_args__ = (
    sa.CheckConstraint("stock_quantity >= 0", name="stock_nonnegative"),
    sa.Index("ix_products_deleted_at_id", "deleted_at", "id", postgresql_where=sa.text("deleted_at IS NOT NULL")),
  )

  name: Mapped[str] = mapped_column(sa.String(MAX_PRODUCT_NAME_LEN))
  sku: Mapped[str]
  stock_quantity: Mapped[int]
  deleted_at: Mapped[datetime | None] = mapped_column(sa.DateTime(True))
