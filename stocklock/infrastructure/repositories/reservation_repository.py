from datetime import datetime
from typing import cast
from uuid import UUID

from sqlalchemy import func, select, update

from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository
from stocklock.domain.validation import require_type
from stocklock.domain.value_objects.reservation import IdempotencyKey
from stocklock.infrastructure.exceptions import ServerTimeUnavailable
from stocklock.infrastructure.mappers.reservation import domain_to_orm, orm_to_domain
from stocklock.infrastructure.models.reservation import ReservationORM
from stocklock.infrastructure.repositories.base import SessionRepository, paginate
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.utils.timestamps import as_utc


class ReservationRepository(SessionRepository, IReservationRepository):
  async def current_time(self) -> datetime:
    if (time := cast(datetime | None, await self.session.scalar(select(func.clock_timestamp())))) is None:
      raise ServerTimeUnavailable

    return as_utc(time)

  async def find_by_id(self, id: UUID, *, for_update: bool = False) -> Reservation | None:
    stmt = select(ReservationORM).where(ReservationORM.id == id)

    if for_update:
      stmt = stmt.with_for_update()

    row = await self.session.scalar(stmt.execution_options(populate_existing=True))

    return row and orm_to_domain(row)

  async def find_by_key(self, product_id: UUID, key: IdempotencyKey) -> Reservation | None:
    require_type(key, IdempotencyKey)
    stmt = select(ReservationORM).where(ReservationORM.product_id == product_id, ReservationORM.key == key.value)
    row = await self.session.scalar(stmt.execution_options(populate_existing=True))

    return row and orm_to_domain(row)

  async def find_many(
    self,
    *,
    product_id: UUID | None = None,
    status: ReservationStatus | None = None,
    start_id: UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
  ) -> list[Reservation]:
    stmt = select(ReservationORM)

    if product_id is not None:
      stmt = stmt.where(ReservationORM.product_id == product_id)

    if status is not None:
      stmt = stmt.where(ReservationORM.status == status.value)

    stmt = paginate(stmt, ReservationORM, start_id, limit)
    rows = await self.session.scalars(stmt.execution_options(populate_existing=True))

    return [orm_to_domain(row) for row in rows]

  async def find_due_ids(self, *, start_id: UUID | None = None, limit: int = DEFAULT_PAGE_SIZE) -> list[UUID]:
    stmt = select(ReservationORM.id).where(
      ReservationORM.status == ReservationStatus.active,
      ReservationORM.expires_at <= func.clock_timestamp(),
    )

    if start_id is not None:
      stmt = stmt.where(ReservationORM.id > start_id)

    return list(await self.session.scalars(stmt.order_by(ReservationORM.id).limit(limit)))

  async def create(self, reservation: Reservation) -> Reservation:
    reservation.ensure_new()

    self.session.add(domain_to_orm(reservation))
    await self.session.flush()

    return reservation

  async def save_transition(
    self, reservation: Reservation, *, previous_status: ReservationStatus
  ) -> Reservation | None:
    """Caller locked before evaluating eligibility; guard the write again here."""
    target = reservation.status
    Reservation.validate_target(target)

    if previous_status is not ReservationStatus.active:
      return None

    conditions = [ReservationORM.id == reservation.id, ReservationORM.status == ReservationStatus.active]

    if target is ReservationStatus.confirmed:
      conditions.append(ReservationORM.expires_at > func.clock_timestamp())

    elif target is ReservationStatus.expired:
      conditions.append(ReservationORM.expires_at <= func.clock_timestamp())

    updated = await self.session.scalar(
      update(ReservationORM)
      .where(*conditions)
      .values(status=reservation.status.value)
      .returning(ReservationORM)
      .execution_options(synchronize_session=False, populate_existing=True)
    )

    return updated and orm_to_domain(updated)
