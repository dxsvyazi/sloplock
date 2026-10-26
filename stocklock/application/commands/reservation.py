from dataclasses import dataclass
from uuid import UUID

from stocklock.application.commands.common import PageCommand, validate_id, validate_quantity
from stocklock.domain.validation import validate_idempotency_key
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import InvalidReservationStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateReservationCommand:
  product_id: UUID
  quantity: int
  key: str

  def __post_init__(self) -> None:
    validate_id(self.product_id)
    validate_quantity(self.quantity, minimum=1)
    validate_idempotency_key(self.key)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetReservationCommand:
  reservation_id: UUID

  def __post_init__(self) -> None:
    validate_id(self.reservation_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelReservationCommand(GetReservationCommand):
  pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpireReservationCommand(GetReservationCommand):
  pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ListReservationsCommand(PageCommand):
  status: ReservationStatus | None = None

  def __post_init__(self) -> None:
    PageCommand.__post_init__(self)

    if self.status is not None and not isinstance(self.status, ReservationStatus):
      raise InvalidReservationStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class ListProductReservationsCommand(ListReservationsCommand):
  product_id: UUID

  def __post_init__(self) -> None:
    ListReservationsCommand.__post_init__(self)

    validate_id(self.product_id)
