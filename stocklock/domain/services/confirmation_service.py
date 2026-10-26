from dataclasses import dataclass
from uuid import UUID

from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import MissingConfirmation, ReservationUnavailable
from stocklock.domain.ports.repositories.confirmation_repository import IConfirmationRepository
from stocklock.domain.validation import validate_id
from stocklock.shared.enums import ReservationStatus


@dataclass(slots=True)
class ConfirmationService:
  """Immutable confirmation results; the caller owns the transaction."""

  confirmations: IConfirmationRepository

  async def get(self, reservation_id: UUID) -> Confirmation | None:
    validate_id(reservation_id)

    return await self.confirmations.find_by_reservation_id(reservation_id)

  async def require(self, reservation_id: UUID) -> Confirmation:
    result = await self.get(reservation_id)

    if result is None:
      raise MissingConfirmation

    return result

  async def create(self, reservation: Reservation) -> Confirmation:
    """Call after a successful confirmation transition within the same transaction."""
    validate_id(reservation.id)

    if reservation.status is not ReservationStatus.confirmed:
      raise ReservationUnavailable("A confirmation requires a confirmed reservation")

    return await self.confirmations.create_or_find(Confirmation(reservation_id=reservation.id))
