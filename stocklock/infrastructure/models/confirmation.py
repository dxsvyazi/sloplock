from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from stocklock.infrastructure.models.base import BaseORM
from stocklock.shared.sqlalchemy.mixins import CreatedAtMixin, IdUUIDMixin


class ConfirmationORM(BaseORM, IdUUIDMixin, CreatedAtMixin):
  __tablename__ = "confirmations"

  reservation_id: Mapped[UUID] = mapped_column(sa.ForeignKey("reservations.id", ondelete="CASCADE"), unique=True)
