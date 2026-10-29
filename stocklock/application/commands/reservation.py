from dataclasses import dataclass
from uuid import UUID

from stocklock.application.commands.common import PageCommand
from stocklock.shared.enums import ProductVisibility, ReservationStatus


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateReservationCommand:
  product_id: UUID
  quantity: int
  key: str


@dataclass(frozen=True, slots=True, kw_only=True)
class GetReservationCommand:
  reservation_id: UUID


@dataclass(frozen=True, slots=True, kw_only=True)
class CancelReservationCommand(GetReservationCommand):
  pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpireReservationCommand(GetReservationCommand):
  pass


@dataclass(frozen=True, slots=True, kw_only=True)
class ExpireReservationsCommand:
  reservation_ids: tuple[UUID, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class ListReservationsCommand(PageCommand):
  status: ReservationStatus | None = None
  product_visibility: ProductVisibility = ProductVisibility.all


@dataclass(frozen=True, slots=True, kw_only=True)
class ListProductReservationsCommand(ListReservationsCommand):
  product_id: UUID
