from abc import ABC, abstractmethod
from typing import NotRequired, TypedDict
from uuid import UUID

from stocklock.domain.entities.product import Product
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE


class ProductDetailsPatch(TypedDict):
  name: NotRequired[str]
  sku: NotRequired[str]


class IProductRepository(ABC):
  """Transaction-scoped operations; repositories never commit independently."""

  @abstractmethod
  async def find_by_id(self, id: UUID, *, for_update: bool = False) -> Product | None: ...

  @abstractmethod
  async def find_many(self, *, start_id: UUID | None = None, limit: int = DEFAULT_PAGE_SIZE) -> list[Product]: ...

  @abstractmethod
  async def create(self, product: Product) -> Product: ...

  @abstractmethod
  async def update_details(self, id: UUID, *, details: ProductDetailsPatch) -> Product | None: ...

  @abstractmethod
  async def set_stock(self, id: UUID, quantity: int) -> Product | None:
    """Set available stock, serialized with holds/returns; reject insufficient return capacity."""
    ...

  @abstractmethod
  async def adjust_stock(self, id: UUID, delta: int) -> Product | None:
    """Atomically apply a delta; return None if missing or outside the stock range."""
    ...
