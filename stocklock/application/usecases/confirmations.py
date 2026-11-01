import logging
from dataclasses import dataclass

from stocklock.application.commands.confirmation import ConfirmReservationCommand, GetConfirmationCommand
from stocklock.application.ports.clock import IClock
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.errors import ConfirmationNotFound, ReservationUnavailable
from stocklock.domain.ports.repositories.reservation_repository import ReservationSnapshot
from stocklock.domain.services.confirmation_service import ConfirmationService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.shared.enums import ReservationStatus

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ConfirmReservationUseCase:
  uow: IUnitOfWork
  reservations: ReservationService
  confirmations: ConfirmationService
  clock: IClock

  async def execute(self, command: ConfirmReservationCommand) -> Confirmation:
    async with self.uow.begin():
      reservation = await self.reservations.require(command.reservation_id, for_update=True)

      reused = reservation.status is ReservationStatus.confirmed
      if reused:
        confirmation = await self.confirmations.require(reservation.id)
      else:
        original = ReservationSnapshot.capture(reservation)

        if not reservation.confirm(await self.clock.now()):
          raise ReservationUnavailable("Reservation is no longer active and unexpired")

        reservation = await self.reservations.save_transition(reservation, original=original)

        if reservation is None:
          raise ReservationUnavailable("Reservation is no longer active and unexpired")

        confirmation = await self.confirmations.create(Confirmation.from_reservation(reservation))

    logger.info(
      "confirmation.reused" if reused else "reservation.confirmed",
      extra={
        "product_id": reservation.product_id,
        "reservation_id": reservation.id,
        "confirmation_id": confirmation.id,
        "quantity": reservation.quantity.value,
        "outcome": "reused" if reused else "confirmed",
      },
    )
    return confirmation


@dataclass(slots=True)
class GetConfirmationUseCase:
  uow: IUnitOfWork
  reservations: ReservationService
  confirmations: ConfirmationService

  async def execute(self, command: GetConfirmationCommand) -> Confirmation:
    async with self.uow.begin():
      await self.reservations.require(command.reservation_id)

      confirmation = await self.confirmations.get(command.reservation_id)

      if confirmation is None:
        raise ConfirmationNotFound

      return confirmation
