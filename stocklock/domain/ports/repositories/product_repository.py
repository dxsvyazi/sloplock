from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from stocklock.domain.entities.product import Product, ProductDetailField
from stocklock.domain.value_objects.product import SKU, ProductName, StockDelta, StockQuantity
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE


@dataclass(frozen=True, slots=True)
class ProductDetailsSnapshot:
  id: UUID
  name: ProductName
  sku: SKU
  updated_at: datetime | None

  @classmethod
  def capture(cls, product: Product) -> "ProductDetailsSnapshot":
    return cls(product.id, product.name, product.sku, product.updated_at)


@dataclass(frozen=True, slots=True)
class ProductStockSnapshot:
  id: UUID
  stock_quantity: StockQuantity
  updated_at: datetime | None

  @classmethod
  def capture(cls, product: Product) -> "ProductStockSnapshot":
    return cls(product.id, product.stock_quantity, product.updated_at)


class IProductRepository(ABC):
  """Transaction-scoped operations; repositories never commit independently."""

  @abstractmethod
  async def find_by_id(self, id: UUID, *, for_update: bool = False) -> Product | None: ...

  @abstractmethod
  async def find_many(self, *, start_id: UUID | None = None, limit: int = DEFAULT_PAGE_SIZE) -> list[Product]: ...

  @abstractmethod
  async def create(self, product: Product) -> Product: ...

  @abstractmethod
  async def save_details(self, product: Product, *, changed_fields: frozenset[ProductDetailField]) -> Product:
    """Persist selected details and entity timestamp; caller holds the product lock."""
    ...

  @abstractmethod
  async def active_held_quantity(self, id: UUID) -> int:
    """Read active holds after acquiring the product lock, without locking reservations."""
    ...

  @abstractmethod
  async def save_stock(self, product: Product) -> Product:
    """Persist validated stock and entity timestamp; caller holds the product lock.

    Caller must validate return capacity against active_held_quantity in this transaction.
    """
    ...

  @abstractmethod
  async def adjust_stock(self, id: UUID, delta: StockDelta) -> Product | None:
    """Atomically apply a delta; return None if missing or outside the stock range."""
    ...
