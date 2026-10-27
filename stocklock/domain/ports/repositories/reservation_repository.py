from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.value_objects.reservation import IdempotencyKey
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE
from stocklock.shared.enums import ReservationStatus


@dataclass(frozen=True, slots=True)
class ReservationSnapshot:
  id: UUID
  status: ReservationStatus

  @classmethod
  def capture(cls, reservation: Reservation) -> "ReservationSnapshot":
    return cls(reservation.id, reservation.status)


class IReservationRepository(ABC):
  """Transaction-scoped primitives; use cases coordinate related stock changes."""

  @abstractmethod
  async def current_time(self) -> datetime:
    """Return authoritative UTC wall time, including time elapsed waiting for locks."""
    ...

  @abstractmethod
  async def find_by_id(self, id: UUID, *, for_update: bool = False) -> Reservation | None: ...

  @abstractmethod
  async def find_by_key(self, product_id: UUID, key: IdempotencyKey) -> Reservation | None: ...

  @abstractmethod
  async def find_many(
    self,
    *,
    product_id: UUID | None = None,
    status: ReservationStatus | None = None,
    start_id: UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
  ) -> list[Reservation]: ...

  @abstractmethod
  async def find_due_ids(self, *, start_id: UUID | None = None, limit: int = DEFAULT_PAGE_SIZE) -> list[UUID]:
    """List stored active holds past their deadline, ordered by identifier."""
    ...

  @abstractmethod
  async def create(self, reservation: Reservation) -> Reservation:
    """Insert an active hold; caller must decrement stock in this same transaction."""
    ...

  @abstractmethod
  async def save_transition(
    self, reservation: Reservation, *, previous_status: ReservationStatus
  ) -> Reservation | None:
    """Persist a terminal status on a hold locked by the caller, or return None.

    The entity is already mutated. Recheck stored active state and authoritative
    database deadlines: confirm requires now < expires_at, expire requires
    now >= expires_at, and cancellation accepts any stored active hold.
    Caller must create a confirmation or return stock in this same transaction.
    """
    ...
