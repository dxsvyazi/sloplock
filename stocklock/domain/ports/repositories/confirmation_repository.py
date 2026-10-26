from abc import ABC, abstractmethod
from uuid import UUID

from stocklock.domain.entities.confirmation import Confirmation


class IConfirmationRepository(ABC):
  @abstractmethod
  async def find_by_reservation_id(self, reservation_id: UUID) -> Confirmation | None: ...

  @abstractmethod
  async def create_or_find(self, confirmation: Confirmation) -> Confirmation:
    """Return the unique immutable result for an already-confirmed reservation.

    Requires the same transaction as the transition. A retry returns the
    original identity and timestamp. Results cannot be updated or deleted.
    """
    ...
