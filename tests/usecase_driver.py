"""Exercise individual use cases through the existing PostgreSQL race scenarios."""

from datetime import timedelta
from uuid import UUID

from stocklock.application.commands.confirmation import ConfirmReservationCommand
from stocklock.application.commands.reservation import (
  CancelReservationCommand,
  CreateReservationCommand,
  ExpireReservationCommand,
)
from stocklock.application.policies.reservation import ReservationTimePolicy
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.application.usecases.confirmations import ConfirmReservationUseCase
from stocklock.application.usecases.reservations import (
  CancelReservationUseCase,
  ExpireReservationUseCase,
  ReserveProductUseCase,
)
from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.ports.repositories.confirmation_repository import IConfirmationRepository
from stocklock.domain.ports.repositories.product_repository import IProductRepository
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository
from stocklock.domain.services.confirmation_service import ConfirmationService
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService


class ReservationDriver:
  def __init__(
    self,
    uow: IUnitOfWork,
    products: IProductRepository,
    reservations: IReservationRepository,
    confirmations: IConfirmationRepository,
    *,
    time_policy: ReservationTimePolicy | None = None,
  ) -> None:
    product_service = ProductService(products)
    reservation_service = ReservationService(reservations)
    confirmation_service = ConfirmationService(confirmations)
    policy = time_policy if time_policy is not None else ReservationTimePolicy(lifetime=timedelta(minutes=5))
    self.reserve_flow = ReserveProductUseCase(uow, product_service, reservation_service, policy)
    self.confirm_flow = ConfirmReservationUseCase(uow, reservation_service, confirmation_service)
    self.cancel_flow = CancelReservationUseCase(uow, product_service, reservation_service)
    self.expire_flow = ExpireReservationUseCase(uow, product_service, reservation_service)

  async def reserve(self, product_id: UUID, quantity: int, key: str) -> Reservation:
    return await self.reserve_flow.execute(
      CreateReservationCommand(product_id=product_id, quantity=quantity, key=key),
    )

  async def confirm(self, reservation_id: UUID) -> Confirmation:
    return await self.confirm_flow.execute(ConfirmReservationCommand(reservation_id=reservation_id))

  async def cancel(self, reservation_id: UUID) -> Reservation | None:
    return await self.cancel_flow.execute(CancelReservationCommand(reservation_id=reservation_id))

  async def expire(self, reservation_id: UUID) -> Reservation | None:
    return await self.expire_flow.execute(ExpireReservationCommand(reservation_id=reservation_id))
