from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from stocklock.infrastructure.models.base import BaseORM
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.sqlalchemy.mixins import CreatedAtMixin, IdUUIDMixin
from stocklock.shared.sqlalchemy.types import IntEnumType


class ReservationORM(BaseORM, IdUUIDMixin, CreatedAtMixin):
  __tablename__ = "reservations"
  __table_args__ = (
    sa.CheckConstraint("quantity > 0", name="quantity_positive"),
    sa.CheckConstraint("status IN (1, 2, 3, 4)", name="status_valid"),
    sa.CheckConstraint("expires_at > created_at", name="expiration_after_creation"),
    sa.CheckConstraint("char_length(key) BETWEEN 1 AND 256 AND octet_length(key) <= 1024", name="key_length_valid"),
    sa.UniqueConstraint("product_id", "key"),
    sa.Index("ix_reservations_product_id_status_id", "product_id", "status", "id"),
    sa.Index("ix_reservations_status_expires_at", "status", "expires_at"),
  )

  product_id: Mapped[UUID] = mapped_column(sa.ForeignKey("products.id"))
  quantity: Mapped[int]
  status: Mapped[ReservationStatus] = mapped_column(IntEnumType(ReservationStatus))
  key: Mapped[str]
  expires_at: Mapped[datetime] = mapped_column(sa.DateTime(True))
