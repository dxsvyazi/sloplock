from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.ports.repositories.confirmation_repository import IConfirmationRepository
from stocklock.infrastructure.exceptions import ConfirmationConflict
from stocklock.infrastructure.mappers.confirmation import domain_to_orm, orm_to_domain
from stocklock.infrastructure.models.confirmation import ConfirmationORM
from stocklock.infrastructure.models.reservation import ReservationORM
from stocklock.infrastructure.repositories.base import SessionRepository
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException


class ConfirmationRepository(SessionRepository, IConfirmationRepository):
  async def find_by_reservation_id(self, reservation_id: UUID) -> Confirmation | None:
    row = await self.session.scalar(
      select(ConfirmationORM)
      .where(ConfirmationORM.reservation_id == reservation_id)
      .execution_options(populate_existing=True)
    )

    return row and orm_to_domain(row)

  async def create_or_find(self, confirmation: Confirmation) -> Confirmation:
    status = await self.session.scalar(
      select(ReservationORM.status).where(ReservationORM.id == confirmation.reservation_id).with_for_update()
    )

    if status != ReservationStatus.confirmed:
      raise ValidationException("A confirmation requires a confirmed reservation in this transaction")

    row = await self.session.scalar(
      insert(ConfirmationORM)
      .values(**domain_to_orm(confirmation).dump())
      .on_conflict_do_nothing(index_elements=[ConfirmationORM.reservation_id])
      .returning(ConfirmationORM)
      .execution_options(populate_existing=True)
    )

    if row is not None:
      return orm_to_domain(row)

    existing = await self.find_by_reservation_id(confirmation.reservation_id)

    if existing is None:
      raise ConfirmationConflict

    return existing

  async def create(self, confirmation: Confirmation) -> Confirmation:
    """Compatibility entry point; returns the unique immutable confirmation."""
    return await self.create_or_find(confirmation)
