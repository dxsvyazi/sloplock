from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal, NotRequired, Self, TypedDict

from stocklock.domain.entities.base import BaseEntity
from stocklock.domain.errors import InsufficientStock, StockCapacityExceeded, StockLimitExceeded
from stocklock.domain.validation import require_type, validate_id
from stocklock.domain.value_objects.product import SKU, ProductName, StockDelta, StockQuantity
from stocklock.shared.constraints import MAX_STOCK_QUANTITY
from stocklock.shared.exceptions import MissingProductDetails, ValidationException
from stocklock.shared.utils import utc_now
from stocklock.shared.utils.timestamps import as_utc

type ProductDetailField = Literal["name", "sku"]

_ALLOWED_DETAILS: Final[frozenset[ProductDetailField]] = frozenset(("name", "sku"))


class ProductDetailsPatch(TypedDict):
  name: NotRequired[ProductName]
  sku: NotRequired[SKU]


@dataclass(frozen=True, slots=True, kw_only=True)
class Product(BaseEntity):
  """Public fields are read-only; domain operations are the only mutation boundary."""

  __hash__: Any = None

  name: ProductName
  sku: SKU
  stock_quantity: StockQuantity
  created_at: datetime = field(default_factory=utc_now)
  updated_at: datetime | None = None

  def __post_init__(self) -> None:
    validate_id(self.id)
    require_type(self.name, ProductName)
    require_type(self.sku, SKU)
    require_type(self.stock_quantity, StockQuantity)

    self._set("created_at", as_utc(self.created_at))

    if self.updated_at is not None:
      self._set("updated_at", as_utc(self.updated_at))

  @classmethod
  def create(cls, *, name: str, sku: str, stock_quantity: int) -> Self:
    return cls(name=ProductName(name), sku=SKU(sku), stock_quantity=StockQuantity(stock_quantity))

  @staticmethod
  def validate_return_capacity(available_quantity: StockQuantity, held_quantity: int) -> None:
    require_type(available_quantity, StockQuantity)

    # Aggregated active holds can exceed the per-row integer range.
    if type(held_quantity) is not int or held_quantity < 0:
      raise ValidationException("Held quantity must be a nonnegative integer")

    if available_quantity.value + held_quantity > MAX_STOCK_QUANTITY:
      raise StockCapacityExceeded

  def update_details(self, details: ProductDetailsPatch) -> None:
    if not details:
      raise MissingProductDetails

    if details.keys() - _ALLOWED_DETAILS:
      raise ValidationException("Supply product name and/or SKU only")

    # Validate the whole patch before applying any of it.
    if "name" in details:
      require_type(details["name"], ProductName)
    if "sku" in details:
      require_type(details["sku"], SKU)

    updated = False

    for name, value in details.items():
      if getattr(self, name) != value:
        self._set(name, value)
        updated = True

    if updated:
      self._set("updated_at", utc_now())

  def correct_stock(self, quantity: StockQuantity, *, held_quantity: int = 0) -> None:
    self.validate_return_capacity(quantity, held_quantity)
    self._set_stock(quantity)

  def adjust_stock(self, delta: StockDelta) -> None:
    require_type(delta, StockDelta)

    quantity = self.stock_quantity.value + delta.value

    if quantity < 0:
      raise InsufficientStock

    if quantity > MAX_STOCK_QUANTITY:
      raise StockLimitExceeded

    self._set_stock(StockQuantity(quantity))

  def _set_stock(self, quantity: StockQuantity) -> None:
    if quantity != self.stock_quantity:
      self._set("stock_quantity", quantity)
      self._set("updated_at", utc_now())
