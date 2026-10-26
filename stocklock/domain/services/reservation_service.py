from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import IdempotencyConflict, ReservationNotFound, ReservationUnavailable
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository
from stocklock.domain.validation import validate_id, validate_idempotency_key, validate_page, validate_quantity
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import InvalidReservationStatus, InvalidTransitionTarget, ValidationException
from stocklock.shared.utils.timestamps import as_utc


def can_transition(reservation: Reservation, target: ReservationStatus, now: datetime) -> bool:
  """Terminal transitions are irreversible; the expiration boundary is inclusive."""
  if target not in (ReservationStatus.confirmed, ReservationStatus.expired, ReservationStatus.cancelled):
    raise InvalidTransitionTarget

  now, expires_at = as_utc(now), as_utc(reservation.expires_at)

  if reservation.status is not ReservationStatus.active:
    return False

  if target is ReservationStatus.confirmed:
    return now < expires_at

  if target is ReservationStatus.expired:
    return now >= expires_at

  return True


@dataclass(slots=True)
class ReservationService:
  """Reservation operations; stock/confirmation changes belong to the calling flow."""

  reservations: IReservationRepository

  async def require(self, reservation_id: UUID, *, for_update: bool = False) -> Reservation:
    validate_id(reservation_id)

    reservation = await self.reservations.find_by_id(reservation_id, for_update=for_update)

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
    validate_page(start_id, limit)

    if product_id is not None:
      validate_id(product_id)

    if status is not None and not isinstance(status, ReservationStatus):
      raise InvalidReservationStatus

    return await self.reservations.find_many(product_id=product_id, status=status, start_id=start_id, limit=limit)

  async def list_due_ids(self, *, start_id: UUID | None = None, limit: int = DEFAULT_PAGE_SIZE) -> "list[UUID]":
    validate_page(start_id, limit)
    return await self.reservations.find_due_ids(start_id=start_id, limit=limit)

  async def find_retry(self, product_id: UUID, key: str, quantity: int) -> Reservation | None:
    """For creation retries, the caller must already hold the product lock."""
    validate_id(product_id)
    validate_idempotency_key(key)
    validate_quantity(quantity, minimum=1)

    existing = await self.reservations.find_by_key(product_id, key)

    if existing is not None and existing.quantity != quantity:
      raise IdempotencyConflict

    return existing

  async def current_time(self) -> datetime:
    return as_utc(await self.reservations.current_time())

  async def create(
    self,
    *,
    product_id: UUID,
    quantity: int,
    key: str,
    expires_at: datetime,
    created_at: datetime | None = None,
  ) -> Reservation:
    """Create a hold using the caller's database instant, or read it for direct calls.

    The caller must hold stock in this same transaction. An explicit created_at
    must come from current_time after acquiring the product lock.
    """
    validate_id(product_id)
    validate_quantity(quantity, minimum=1)
    validate_idempotency_key(key)

    expires_at = as_utc(expires_at)
    now = await self.current_time() if created_at is None else as_utc(created_at)

    if expires_at <= now:
      raise ValidationException("Expiration must be in the future")

    return await self.reservations.create(
      Reservation(product_id=product_id, quantity=quantity, key=key, created_at=now, expires_at=expires_at)
    )

  async def confirm(self, reservation_id: UUID) -> Reservation:
    reservation = await self._transition(reservation_id, ReservationStatus.confirmed)

    if reservation is None:
      raise ReservationUnavailable("Reservation is no longer active and unexpired")

    return reservation

  async def cancel(self, reservation_id: UUID) -> Reservation | None:
    return await self._transition(reservation_id, ReservationStatus.cancelled)

  async def expire(self, reservation_id: UUID) -> Reservation | None:
    return await self._transition(reservation_id, ReservationStatus.expired)

  async def _transition(self, reservation_id: UUID, target: ReservationStatus) -> Reservation | None:
    validate_id(reservation_id)

    reservation = await self.reservations.find_by_id(reservation_id, for_update=True)

    if reservation is None or not can_transition(reservation, target, await self.current_time()):
      return None

    # Recheck time/state at the write boundary in the persistence adapter.
    return await self.reservations.transition(reservation_id, target)
