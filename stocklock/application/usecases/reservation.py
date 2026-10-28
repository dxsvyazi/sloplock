from dataclasses import dataclass

from stocklock.application.commands.reservation import (
  CancelReservationCommand,
  CreateReservationCommand,
  ExpireReservationCommand,
  GetReservationCommand,
  ListProductReservationsCommand,
  ListReservationsCommand,
)
from stocklock.application.policies.reservation import ReservationTimePolicy
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import ReservationUnavailable
from stocklock.domain.ports.repositories.reservation_repository import ReservationSnapshot
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity


@dataclass(slots=True)
class ReserveProductUseCase:
  uow: IUnitOfWork
  products: ProductService
  reservations: ReservationService
  time_policy: ReservationTimePolicy

  async def execute(self, command: CreateReservationCommand) -> Reservation:
    """Start the configured lifetime after locking; retries retain the original hold."""
    quantity = ReservationQuantity(command.quantity)
    key = IdempotencyKey(command.key)

    async with self.uow.begin():
      # Product first, then insert only: never lock an existing reservation here.
      await self.products.require(command.product_id, for_update=True)

      existing = await self.reservations.find_retry(command.product_id, key, quantity)

      if existing is not None:
        return existing

      await self.products.hold_stock(command.product_id, quantity)

      created_at = await self.reservations.current_time()
      reservation = Reservation.create(
        product_id=command.product_id,
        quantity=command.quantity,
        key=command.key,
        created_at=created_at,
        expires_at=self.time_policy.expiration_for(created_at),
      )

      return await self.reservations.create(reservation)


@dataclass(slots=True)
class GetReservationUseCase:
  uow: IUnitOfWork
  reservations: ReservationService

  async def execute(self, command: GetReservationCommand) -> Reservation:
    async with self.uow.begin():
      return await self.reservations.require(command.reservation_id)


@dataclass(slots=True)
class ListReservationsUseCase:
  uow: IUnitOfWork
  reservations: ReservationService

  async def execute(self, command: ListReservationsCommand) -> list[Reservation]:
    async with self.uow.begin():
      return await self.reservations.list(status=command.status, start_id=command.start_id, limit=command.limit)


@dataclass(slots=True)
class ListProductReservationsUseCase:
  uow: IUnitOfWork
  products: ProductService
  reservations: ReservationService

  async def execute(self, command: ListProductReservationsCommand) -> list[Reservation]:
    async with self.uow.begin():
      await self.products.require(command.product_id)

      return await self.reservations.list(
        product_id=command.product_id, status=command.status, start_id=command.start_id, limit=command.limit
      )


@dataclass(slots=True)
class CancelReservationUseCase:
  uow: IUnitOfWork
  products: ProductService
  reservations: ReservationService

  async def execute(self, command: CancelReservationCommand) -> Reservation:
    async with self.uow.begin():
      reservation = await self.reservations.require(command.reservation_id, for_update=True)

      original = ReservationSnapshot.capture(reservation)

      if not reservation.cancel():
        raise ReservationUnavailable.not_active()

      reservation = await self.reservations.save_transition(reservation, original=original)

      if reservation is None:
        raise ReservationUnavailable.not_active()

      await self.products.return_stock(reservation.product_id, reservation.quantity)

      return reservation


@dataclass(slots=True)
class ExpireReservationUseCase:
  uow: IUnitOfWork
  products: ProductService
  reservations: ReservationService

  async def execute(self, command: ExpireReservationCommand) -> Reservation:
    async with self.uow.begin():
      reservation = await self.reservations.require(command.reservation_id, for_update=True)

      original = ReservationSnapshot.capture(reservation)

      if not reservation.expire(await self.reservations.current_time()):
        raise ReservationUnavailable.not_eligible_for_expire()

      reservation = await self.reservations.save_transition(reservation, original=original)

      if reservation is None:
        raise ReservationUnavailable.not_eligible_for_expire()

      await self.products.return_stock(reservation.product_id, reservation.quantity)

      return reservation


@dataclass(slots=True)
class TryExpireReservationUseCase:
  """Best-effort cleanup: another transaction may have processed the candidate."""

  uow: IUnitOfWork
  products: ProductService
  reservations: ReservationService

  async def execute(self, command: ExpireReservationCommand) -> Reservation | None:
    async with self.uow.begin():
      reservation = await self.reservations.get(command.reservation_id, for_update=True)

      if reservation is None:
        return None

      original = ReservationSnapshot.capture(reservation)

      if not reservation.expire(await self.reservations.current_time()):
        return None

      reservation = await self.reservations.save_transition(reservation, original=original)

      if reservation is not None:
        await self.products.return_stock(reservation.product_id, reservation.quantity)

      return reservation
