from dataclasses import dataclass

from stocklock.application.commands.confirmation import ConfirmReservationCommand, GetConfirmationCommand
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.services.confirmation_service import ConfirmationService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.shared.enums import ReservationStatus


@dataclass(slots=True)
class ConfirmReservationUseCase:
  uow: IUnitOfWork
  reservations: ReservationService
  confirmations: ConfirmationService

  async def execute(self, command: ConfirmReservationCommand) -> Confirmation:
    async with self.uow.begin():
      reservation = await self.reservations.require(command.reservation_id, for_update=True)

      if reservation.status is ReservationStatus.confirmed:
        return await self.confirmations.require(reservation.id)

      confirmed = await self.reservations.confirm(reservation.id)

      return await self.confirmations.create(confirmed)


@dataclass(slots=True)
class GetConfirmationUseCase:
  uow: IUnitOfWork
  reservations: ReservationService
  confirmations: ConfirmationService

  async def execute(self, command: GetConfirmationCommand) -> Confirmation | None:
    async with self.uow.begin():
      await self.reservations.require(command.reservation_id)

      return await self.confirmations.get(command.reservation_id)
