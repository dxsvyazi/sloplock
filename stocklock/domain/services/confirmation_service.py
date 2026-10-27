from dataclasses import dataclass
from uuid import UUID

from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.errors import MissingConfirmation
from stocklock.domain.ports.repositories.confirmation_repository import IConfirmationRepository


@dataclass(slots=True)
class ConfirmationService:
  """Immutable confirmation results; the caller owns the transaction."""

  confirmations: IConfirmationRepository

  async def get(self, reservation_id: UUID) -> Confirmation | None:
    return await self.confirmations.find_by_reservation_id(reservation_id)

  async def require(self, reservation_id: UUID) -> Confirmation:
    result = await self.get(reservation_id)

    if result is None:
      raise MissingConfirmation

    return result

  async def create(self, confirmation: Confirmation) -> Confirmation:
    """Persist the result constructed by the use case after its terminal transition."""
    return await self.confirmations.create_or_find(confirmation)
