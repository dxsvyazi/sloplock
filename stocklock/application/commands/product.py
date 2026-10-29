from dataclasses import dataclass
from uuid import UUID

from stocklock.application.commands.common import PageCommand
from stocklock.shared.enums import DeletionMode, ProductVisibility


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateProductCommand:
  name: str
  sku: str
  stock_quantity: int


@dataclass(frozen=True, slots=True, kw_only=True)
class GetProductCommand:
  product_id: UUID
  include_deleted: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateProductCommand(GetProductCommand):
  name: str | None = None
  sku: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectProductStockCommand(GetProductCommand):
  stock_quantity: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ListProductsCommand(PageCommand):
  visibility: ProductVisibility = ProductVisibility.visible


@dataclass(frozen=True, slots=True, kw_only=True)
class DeleteProductCommand:
  product_id: UUID
  mode: DeletionMode = DeletionMode.soft
