from dataclasses import dataclass
from uuid import UUID

from stocklock.application.commands.common import PageCommand
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.domain.services.reservation_service import ReservationService


@dataclass(slots=True)
class ListDueReservationsUseCase:
  uow: IUnitOfWork
  reservations: ReservationService

  async def execute(self, command: PageCommand) -> list[UUID]:
    """Release the read transaction before callers start per-reservation workflows."""
    async with self.uow.begin():
      return await self.reservations.list_due_ids(start_id=command.start_id, limit=command.limit)
