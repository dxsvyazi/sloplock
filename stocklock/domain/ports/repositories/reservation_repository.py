from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.value_objects.reservation import IdempotencyKey
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE
from stocklock.shared.enums import ProductVisibility, ReservationStatus


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
  async def purge_terminal(self, cutoffs: dict[ReservationStatus, datetime], *, limit: int) -> int:
    """Lock and delete a bounded batch of terminal holds and their confirmations.

    Skip locked reservations. Each status has an inclusive finalization cutoff;
    omitted statuses are retained. Caller owns the transaction. Never alter stock.
    """
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
    product_visibility: ProductVisibility = ProductVisibility.all,
    start_id: UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
  ) -> list[Reservation]: ...

  @abstractmethod
  async def find_due_ids(self, *, start_id: UUID | None = None, limit: int = DEFAULT_PAGE_SIZE) -> list[UUID]:
    """List stored active holds past their deadline, ordered by identifier."""
    ...

  @abstractmethod
  async def expire_due(self, reservation_ids: tuple[UUID, ...]) -> list[Reservation]:
    """Lock requested active, due holds without waiting on locked reservations.

    Transition them to expired and return only changed rows. Caller must restore
    their stock in this same transaction. Skipped holds can be retried later.
    """
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
