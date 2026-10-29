from dataclasses import dataclass, replace
from datetime import datetime
from uuid import UUID

from stocklock.domain.entities.product import _ALLOWED_DETAILS, Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import InsufficientStock, ProductHasActiveReservations, ProductNotFound, StockLimitExceeded
from stocklock.domain.ports.repositories.product_repository import (
  IProductRepository,
  ProductDetailField,
  ProductDetailsSnapshot,
  ProductStockSnapshot,
)
from stocklock.domain.validation import require_type, validate_page
from stocklock.domain.value_objects.product import StockDelta
from stocklock.domain.value_objects.reservation import ReservationQuantity
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE, MAX_STOCK_QUANTITY
from stocklock.shared.enums import DeletionMode, ProductVisibility
from stocklock.shared.exceptions import ValidationException


@dataclass(slots=True)
class ProductService:
  """Individual inventory operations; the caller owns the transaction."""

  products: IProductRepository

  async def create(self, product: Product) -> Product:
    return await self.products.create(product)

  async def require(
    self,
    product_id: UUID,
    *,
    for_update: bool = False,
    include_deleted: bool = False,
  ) -> Product:
    product = await self.products.find_by_id(product_id, for_update=for_update)

    if product is None or (product.deleted_at is not None and not include_deleted):
      raise ProductNotFound

    return product

  async def list(
    self,
    *,
    start_id: UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    visibility: ProductVisibility = ProductVisibility.visible,
  ) -> list[Product]:
    validate_page(limit)

    require_type(visibility, ProductVisibility)

    return await self.products.find_many(start_id=start_id, limit=limit, visibility=visibility)

  async def delete(self, product: Product, *, mode: DeletionMode, at: datetime) -> None:
    require_type(mode, DeletionMode)

    if await self.products.active_held_quantity(product.id):
      raise ProductHasActiveReservations

    if mode is DeletionMode.hard:
      await self.products.hard_delete(product.id)
    elif product.deleted_at is None:
      product.soft_delete(at)
      await self.products.save_deletion(product)

  async def save_details(self, product: Product, *, original: ProductDetailsSnapshot) -> Product:
    """Compare domain values; caller fetched and mutated the product under its lock."""
    if product.id != original.id:
      raise ValidationException("Product and snapshot identifiers must match")

    changed_fields: frozenset[ProductDetailField] = frozenset(
      name for name in _ALLOWED_DETAILS if getattr(product, name) != getattr(original, name)
    )

    if not changed_fields:
      return product if product.updated_at == original.updated_at else replace(product, updated_at=original.updated_at)

    return await self.products.save_details(product, changed_fields=changed_fields)

  async def active_held_quantity(self, product_id: UUID) -> int:
    """Caller must already hold the product lock before reading correction headroom."""
    return await self.products.active_held_quantity(product_id)

  async def save_stock(self, product: Product, *, original: ProductStockSnapshot) -> Product:
    if product.id != original.id:
      raise ValidationException("Product and snapshot identifiers must match")

    if product.stock_quantity == original.stock_quantity:
      return product if product.updated_at == original.updated_at else replace(product, updated_at=original.updated_at)

    return await self.products.save_stock(product)

  async def hold_stock(self, product_id: UUID, quantity: ReservationQuantity) -> Product:
    require_type(quantity, ReservationQuantity)

    product = await self.products.adjust_stock(product_id, StockDelta(-quantity.value))

    if product is None:
      raise InsufficientStock

    return product

  async def return_stock(self, product_id: UUID, quantity: ReservationQuantity) -> Product:
    require_type(quantity, ReservationQuantity)

    product = await self.products.adjust_stock(product_id, StockDelta(quantity.value))

    if product is None:
      raise StockLimitExceeded

    return product

  async def return_stock_many(self, reservations: "list[Reservation]") -> None:
    """Return transitioned holds once per product, locking products in UUID order."""
    quantities: dict[UUID, int] = {}
    for reservation in reservations:
      quantities[reservation.product_id] = quantities.get(reservation.product_id, 0) + reservation.quantity.value

    for product_id, quantity in sorted(quantities.items()):
      if quantity > MAX_STOCK_QUANTITY:
        raise StockLimitExceeded
      await self.return_stock(product_id, ReservationQuantity(quantity))
