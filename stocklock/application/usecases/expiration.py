from dataclasses import dataclass
from uuid import UUID

from stocklock.application.commands.common import PageCommand
from stocklock.application.commands.reservation import ExpireReservationsCommand
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService


@dataclass(slots=True)
class ListDueReservationsUseCase:
  uow: IUnitOfWork
  reservations: ReservationService

  async def execute(self, command: PageCommand) -> list[UUID]:
    """Release the read transaction before callers process expiration candidates."""
    async with self.uow.begin():
      return await self.reservations.list_due_ids(start_id=command.start_id, limit=command.limit)


@dataclass(slots=True)
class ExpireReservationsUseCase:
  uow: IUnitOfWork
  reservations: ReservationService
  products: ProductService

  async def execute(self, command: ExpireReservationsCommand) -> list[UUID]:
    """Expire a bounded page and restore only its transitioned holds atomically."""
    async with self.uow.begin():
      expired = await self.reservations.expire_due(command.reservation_ids)
      await self.products.return_stock_many(expired)
      return [reservation.id for reservation in expired]
