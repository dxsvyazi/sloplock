from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import ReservationNotFound
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository, ReservationSnapshot
from stocklock.domain.validation import require_type, validate_id, validate_page
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException


@dataclass(slots=True)
class ReservationService:
  """Reservation operations; stock/confirmation changes belong to the calling flow."""

  reservations: IReservationRepository

  async def get(self, reservation_id: UUID, *, for_update: bool = False) -> Reservation | None:
    return await self.reservations.find_by_id(reservation_id, for_update=for_update)

  async def require(self, reservation_id: UUID, *, for_update: bool = False) -> Reservation:
    reservation = await self.get(reservation_id, for_update=for_update)

    if reservation is None:
      raise ReservationNotFound

    return reservation

  async def list(
    self,
    *,
    product_id: UUID | None = None,
    status: ReservationStatus | None = None,
    start_id: UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
  ) -> list[Reservation]:
    validate_page(limit)

    if status is not None:
      Reservation.validate_status(status)

    return await self.reservations.find_many(product_id=product_id, status=status, start_id=start_id, limit=limit)

  async def list_due_ids(self, *, start_id: UUID | None = None, limit: int = DEFAULT_PAGE_SIZE) -> "list[UUID]":
    validate_page(limit)
    return await self.reservations.find_due_ids(start_id=start_id, limit=limit)

  async def expire_due(self, reservation_ids: tuple[UUID, ...]) -> "list[Reservation]":
    validate_page(len(reservation_ids))

    for reservation_id in reservation_ids:
      validate_id(reservation_id)

    return await self.reservations.expire_due(reservation_ids)

  async def find_retry(
    self, product_id: UUID, key: IdempotencyKey, quantity: ReservationQuantity
  ) -> Reservation | None:
    """For creation retries, the caller must already hold the product lock."""
    require_type(key, IdempotencyKey)
    require_type(quantity, ReservationQuantity)

    existing = await self.reservations.find_by_key(product_id, key)

    if existing is not None:
      existing.ensure_retry(quantity)

    return existing

  async def current_time(self) -> datetime:
    return await self.reservations.current_time()

  async def create(self, reservation: Reservation) -> Reservation:
    """Persist a validated hold; the caller owns stock and transaction coordination."""
    return await self.reservations.create(reservation)

  async def save_transition(self, reservation: Reservation, *, original: ReservationSnapshot) -> Reservation | None:
    """Persist a changed terminal state; the caller owns the lock and domain operation."""
    if reservation.id != original.id:
      raise ValidationException("Reservation and snapshot identifiers must match")

    if reservation.status is original.status:
      return None

    Reservation.validate_target(reservation.status)

    if original.status is not ReservationStatus.active:
      return None

    return await self.reservations.save_transition(reservation, previous_status=original.status)
