from dataclasses import dataclass
from uuid import UUID

from stocklock.application.commands.common import PageCommand, validate_id, validate_quantity, validate_text
from stocklock.shared.constraints import MAX_PRODUCT_NAME_LEN, MIN_PRODUCT_NAME_LEN
from stocklock.shared.exceptions import MissingProductDetails


@dataclass(frozen=True, slots=True, kw_only=True)
class CreateProductCommand:
  name: str
  sku: str
  stock_quantity: int

  def __post_init__(self) -> None:
    validate_text(self.name, minimum=MIN_PRODUCT_NAME_LEN, maximum=MAX_PRODUCT_NAME_LEN)
    validate_text(self.sku)
    validate_quantity(self.stock_quantity)


@dataclass(frozen=True, slots=True, kw_only=True)
class GetProductCommand:
  product_id: UUID

  def __post_init__(self) -> None:
    validate_id(self.product_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class UpdateProductCommand(GetProductCommand):
  name: str | None = None
  sku: str | None = None

  def __post_init__(self) -> None:
    GetProductCommand.__post_init__(self)
    if self.name is None and self.sku is None:
      raise MissingProductDetails

    if self.name is not None:
      validate_text(self.name, minimum=MIN_PRODUCT_NAME_LEN, maximum=MAX_PRODUCT_NAME_LEN)

    if self.sku is not None:
      validate_text(self.sku)


@dataclass(frozen=True, slots=True, kw_only=True)
class CorrectProductStockCommand(GetProductCommand):
  stock_quantity: int

  def __post_init__(self) -> None:
    GetProductCommand.__post_init__(self)
    validate_quantity(self.stock_quantity)


@dataclass(frozen=True, slots=True, kw_only=True)
class ListProductsCommand(PageCommand):
  pass
