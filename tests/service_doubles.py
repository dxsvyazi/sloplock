"""In-memory transaction doubles for domain/application behavior, not race safety."""

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from uuid import UUID

from stocklock.application.ports.clock import IClock
from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.ports.repositories.confirmation_repository import IConfirmationRepository
from stocklock.domain.ports.repositories.product_repository import IProductRepository, ProductDetailField
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository
from stocklock.domain.validation import require_type
from stocklock.domain.value_objects.product import StockDelta, StockQuantity
from stocklock.domain.value_objects.reservation import IdempotencyKey
from stocklock.shared.constraints import MAX_STOCK_QUANTITY
from stocklock.shared.enums import ProductVisibility, ReservationStatus
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

  async def find_many(
    self,
    *,
    start_id: UUID | None = None,
    limit: int = 50,
    visibility: ProductVisibility = ProductVisibility.visible,
  ) -> list[Product]:
    self.store.check()
    return page(
      (
        p
        for p in self.store.products.values()
        if visibility is ProductVisibility.all or (p.deleted_at is None) == (visibility is ProductVisibility.visible)
      ),
      start_id,
      limit,
    )

  async def save_deletion(self, product: Product) -> None:
    self.store.check("save_deletion")
    self.store.products[product.id] = deepcopy(product)

  async def hard_delete(self, id: UUID) -> None:
    self.store.check("hard_delete")
    del self.store.products[id]
    ids = {r.id for r in self.store.reservations.values() if r.product_id == id}
    self.store.reservations = {k: v for k, v in self.store.reservations.items() if k not in ids}
    self.store.confirmations = {k: v for k, v in self.store.confirmations.items() if k not in ids}

  async def purge_deleted(self, cutoff, *, limit):
    raise NotImplementedError("Product cleanup is tested against PostgreSQL")

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
    if product.deleted_at is not None and delta.value <= 0:
      return None
    quantity = product.stock_quantity.value + delta.value
    if not 0 <= quantity <= MAX_STOCK_QUANTITY:
      return None
    product = replace(product, stock_quantity=StockQuantity(quantity), updated_at=utc_now())
    self.store.products[id] = product
    return deepcopy(product)


class Clock(IClock):
  def __init__(self, store: Store) -> None:
    self.store = store

  async def now(self) -> datetime:
    self.store.check()
    return self.store.now


class Reservations(IReservationRepository):
  def __init__(self, store: Store) -> None:
    self.store = store

  async def purge_terminal(self, cutoffs, *, limit):
    raise NotImplementedError("Retention metadata and cleanup are tested against PostgreSQL")

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
    product_visibility: ProductVisibility = ProductVisibility.all,
    start_id: UUID | None = None,
    limit: int = 50,
  ) -> list[Reservation]:
    self.store.check()
    return page(
      (
        r
        for r in self.store.reservations.values()
        if (product_id is None or r.product_id == product_id)
        and (status is None or r.status == status)
        and (
          product_visibility is ProductVisibility.all
          or (self.store.products[r.product_id].deleted_at is None) == (product_visibility is ProductVisibility.visible)
        )
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

  async def expire_due(self, reservation_ids: tuple[UUID, ...]) -> list[Reservation]:
    self.store.check("expire_due")
    expired = []
    for reservation_id in sorted(set(reservation_ids)):
      current = self.store.reservations.get(reservation_id)
      if current is not None and current.expire(self.store.now):
        expired.append(deepcopy(current))
    return expired

  async def save_transition(
    self, reservation: Reservation, *, previous_status: ReservationStatus
  ) -> Reservation | None:
    self.store.check("save_transition")
    current = self.store.reservations.get(reservation.id)
    Reservation.validate_target(reservation.status)
    if previous_status is not ReservationStatus.active or current is None:
      return None
    if reservation.status is ReservationStatus.cancelled:
      changed = current.cancel()
    elif reservation.status is ReservationStatus.confirmed:
      changed = current.confirm(self.store.now)
    else:
      changed = current.expire(self.store.now)
    if not changed:
      return None
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
