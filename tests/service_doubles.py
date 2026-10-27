"""In-memory transaction doubles for domain/application behavior, not race safety."""

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.ports.repositories.confirmation_repository import IConfirmationRepository
from stocklock.domain.ports.repositories.product_repository import IProductRepository, ProductDetailField
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository
from stocklock.domain.validation import require_type
from stocklock.domain.value_objects.product import StockDelta
from stocklock.domain.value_objects.reservation import IdempotencyKey
from stocklock.shared.constraints import MAX_STOCK_QUANTITY
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import DynamicException
from stocklock.shared.utils import utc_now


class PersistenceTestFailure(DynamicException):
  """An intentionally injected failure in the in-memory persistence double."""


@dataclass
class Store:
  products: dict[UUID, Product] = field(default_factory=dict)
  reservations: dict[UUID, Reservation] = field(default_factory=dict)
  confirmations: dict[UUID, Confirmation] = field(default_factory=dict)
  now: datetime = field(default_factory=utc_now)
  active: bool = False
  fail: str | None = None

  def check(self, operation: str = "") -> None:
    if not self.active:
      raise PersistenceTestFailure("No active transaction")
    if self.fail == operation:
      raise PersistenceTestFailure("Injected persistence failure")

  @asynccontextmanager
  async def begin(self) -> AsyncIterator[None]:
    if self.active:
      raise PersistenceTestFailure("Nested transaction")
    snapshot = deepcopy((self.products, self.reservations, self.confirmations))
    self.active = True
    try:
      yield
    except BaseException:
      self.products, self.reservations, self.confirmations = snapshot
      raise
    finally:
      self.active = False


def page[T: Product | Reservation](items: Iterable[T], start_id: UUID | None, limit: int) -> list[T]:
  return deepcopy(sorted((v for v in items if start_id is None or v.id > start_id), key=lambda v: v.id)[:limit])


class Products(IProductRepository):
  def __init__(self, store: Store) -> None:
    self.store = store

  async def find_by_id(self, id: UUID, *, for_update: bool = False) -> Product | None:
    self.store.check()
    return deepcopy(self.store.products.get(id))

  async def find_many(self, *, start_id: UUID | None = None, limit: int = 50) -> list[Product]:
    self.store.check()
    return page(self.store.products.values(), start_id, limit)

  async def create(self, product: Product) -> Product:
    self.store.check("create_product")
    self.store.products[product.id] = deepcopy(product)
    return deepcopy(product)

  async def save_details(self, product: Product, *, changed_fields: frozenset[ProductDetailField]) -> Product:
    self.store.check("save_details")
    current = self.store.products[product.id]
    for name in changed_fields:
      object.__setattr__(current, name, getattr(product, name))
    object.__setattr__(current, "updated_at", product.updated_at)
    return deepcopy(current)

  async def active_held_quantity(self, id: UUID) -> int:
    self.store.check()
    return sum(
      r.quantity.value
      for r in self.store.reservations.values()
      if r.product_id == id and r.status is ReservationStatus.active
    )

  async def save_stock(self, product: Product) -> Product:
    self.store.check("save_stock")
    current = self.store.products[product.id]
    object.__setattr__(current, "stock_quantity", product.stock_quantity)
    object.__setattr__(current, "updated_at", product.updated_at)
    return deepcopy(current)

  async def adjust_stock(self, id: UUID, delta: StockDelta) -> Product | None:
    require_type(delta, StockDelta)
    self.store.check("adjust_stock")
    if (product := self.store.products.get(id)) is None:
      return None
    if not 0 <= product.stock_quantity.value + delta.value <= MAX_STOCK_QUANTITY:
      return None
    product.adjust_stock(delta)
    return deepcopy(product)


class Reservations(IReservationRepository):
  def __init__(self, store: Store) -> None:
    self.store = store

  async def current_time(self) -> datetime:
    self.store.check()
    return self.store.now

  async def find_by_id(self, id: UUID, *, for_update: bool = False) -> Reservation | None:
    self.store.check()
    return deepcopy(self.store.reservations.get(id))

  async def find_by_key(self, product_id: UUID, key: IdempotencyKey) -> Reservation | None:
    self.store.check()
    return next(
      (deepcopy(r) for r in self.store.reservations.values() if r.product_id == product_id and r.key == key),
      None,
    )

  async def find_many(
    self,
    *,
    product_id: UUID | None = None,
    status: ReservationStatus | None = None,
    start_id: UUID | None = None,
    limit: int = 50,
  ) -> list[Reservation]:
    self.store.check()
    return page(
      (
        r
        for r in self.store.reservations.values()
        if (product_id is None or r.product_id == product_id) and (status is None or r.status == status)
      ),
      start_id,
      limit,
    )

  async def find_due_ids(self, *, start_id: UUID | None = None, limit: int = 50) -> list[UUID]:
    self.store.check()
    return [
      r.id
      for r in page(
        (
          r
          for r in self.store.reservations.values()
          if r.status is ReservationStatus.active and r.expires_at <= self.store.now
        ),
        start_id,
        limit,
      )
    ]

  async def create(self, reservation: Reservation) -> Reservation:
    self.store.check("create_reservation")
    reservation.ensure_new()
    self.store.reservations[reservation.id] = deepcopy(reservation)
    return deepcopy(reservation)

  async def save_transition(
    self, reservation: Reservation, *, previous_status: ReservationStatus
  ) -> Reservation | None:
    self.store.check("save_transition")
    current = self.store.reservations.get(reservation.id)
    Reservation.validate_target(reservation.status)
    if previous_status is not ReservationStatus.active or current is None:
      return None
    if not current.can_transition(reservation.status, self.store.now):
      return None
    object.__setattr__(current, "status", reservation.status)
    return deepcopy(current)


class Confirmations(IConfirmationRepository):
  def __init__(self, store: Store) -> None:
    self.store = store

  async def find_by_reservation_id(self, reservation_id: UUID) -> Confirmation | None:
    self.store.check()
    return deepcopy(self.store.confirmations.get(reservation_id))

  async def create_or_find(self, confirmation: Confirmation) -> Confirmation:
    self.store.check("create_confirmation")
    return deepcopy(self.store.confirmations.setdefault(confirmation.reservation_id, deepcopy(confirmation)))
