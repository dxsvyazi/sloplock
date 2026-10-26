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
from stocklock.domain.inventory import validate_stock_return_capacity
from stocklock.domain.ports.repositories.confirmation_repository import IConfirmationRepository
from stocklock.domain.ports.repositories.product_repository import IProductRepository, ProductDetailsPatch
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository
from stocklock.domain.services.reservation_service import can_transition
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

  async def update_details(self, id: UUID, *, details: ProductDetailsPatch) -> Product | None:
    self.store.check()
    if (product := self.store.products.get(id)) is None:
      return None
    for name, value in details.items():
      setattr(product, name, value)
    return deepcopy(product)

  async def set_stock(self, id: UUID, quantity: int) -> Product | None:
    self.store.check()
    if (product := self.store.products.get(id)) is None:
      return None
    held = sum(
      r.quantity
      for r in self.store.reservations.values()
      if r.product_id == id and r.status is ReservationStatus.active
    )
    validate_stock_return_capacity(quantity, held)
    product.stock_quantity = quantity
    return deepcopy(product)

  async def adjust_stock(self, id: UUID, delta: int) -> Product | None:
    self.store.check("adjust_stock")
    if (product := self.store.products.get(id)) is None:
      return None
    if not 0 <= product.stock_quantity + delta <= MAX_STOCK_QUANTITY:
      return None
    product.stock_quantity += delta
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

  async def find_by_key(self, product_id: UUID, key: str) -> Reservation | None:
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
    self.store.reservations[reservation.id] = deepcopy(reservation)
    return deepcopy(reservation)

  async def transition(self, id: UUID, target: ReservationStatus) -> Reservation | None:
    self.store.check()
    if (reservation := self.store.reservations.get(id)) is None:
      return None
    if not can_transition(reservation, target, self.store.now):
      return None
    reservation.status = target
    return deepcopy(reservation)


class Confirmations(IConfirmationRepository):
  def __init__(self, store: Store) -> None:
    self.store = store

  async def find_by_reservation_id(self, reservation_id: UUID) -> Confirmation | None:
    self.store.check()
    return deepcopy(self.store.confirmations.get(reservation_id))

  async def create_or_find(self, confirmation: Confirmation) -> Confirmation:
    self.store.check("create_confirmation")
    return deepcopy(self.store.confirmations.setdefault(confirmation.reservation_id, deepcopy(confirmation)))
