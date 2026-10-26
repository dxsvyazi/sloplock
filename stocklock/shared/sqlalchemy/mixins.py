from sqlalchemy.orm import Mapped

from stocklock.shared.sqlalchemy.types import CreatedAt, IdInt, IdUUID, UpdatedAt


class CreatedAtMixin:
  created_at: Mapped[CreatedAt]


class UpdatedAtMixin:
  updated_at: Mapped[UpdatedAt]


class TimeMetricsMixin(UpdatedAtMixin, CreatedAtMixin): ...


class IdIntMixin:
  id: Mapped[IdInt]


class IdUUIDMixin:
  id: Mapped[IdUUID]
