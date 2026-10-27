from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal, NotRequired, TypedDict

from stocklock.domain.entities.base import BaseEntity
from stocklock.domain.errors import InsufficientStock, StockCapacityExceeded, StockLimitExceeded
from stocklock.domain.validation import validate_id, validate_quantity, validate_text
from stocklock.shared.constraints import MAX_PRODUCT_NAME_LEN, MAX_STOCK_QUANTITY, MIN_PRODUCT_NAME_LEN
from stocklock.shared.exceptions import MissingProductDetails, ValidationException
from stocklock.shared.utils import utc_now
from stocklock.shared.utils.timestamps import as_utc

type ProductDetailField = Literal["name", "sku"]

_ALLOWED_DETAILS: Final[frozenset[ProductDetailField]] = frozenset(("name", "sku"))


class ProductDetailsPatch(TypedDict):
  name: NotRequired[str]
  sku: NotRequired[str]


@dataclass(frozen=True, slots=True, kw_only=True)
class Product(BaseEntity):
  """Public fields are read-only; validated operations are the only mutation boundary."""

  __hash__: Any = None

  name: str
  sku: str
  stock_quantity: int
  created_at: datetime = field(default_factory=utc_now)
  updated_at: datetime | None = None

  def __post_init__(self) -> None:
    validate_id(self.id)
    self.validate_details({"name": self.name, "sku": self.sku})
    self.validate_stock(self.stock_quantity)

    self._set("created_at", as_utc(self.created_at))

    if self.updated_at is not None:
      self._set("updated_at", as_utc(self.updated_at))

  @staticmethod
  def validate_details(details: ProductDetailsPatch) -> None:
    if not details:
      raise MissingProductDetails

    if details.keys() - _ALLOWED_DETAILS:
      raise ValidationException("Supply product name and/or SKU only")

    if "name" in details:
      validate_text(details["name"], minimum=MIN_PRODUCT_NAME_LEN, maximum=MAX_PRODUCT_NAME_LEN)

    if "sku" in details:
      validate_text(details["sku"])

  @staticmethod
  def validate_stock(quantity: int) -> None:
    validate_quantity(quantity)

  @staticmethod
  def validate_stock_delta(delta: int) -> None:
    validate_quantity(delta, minimum=-MAX_STOCK_QUANTITY)

  @staticmethod
  def validate_stock_operation(quantity: int) -> None:
    validate_quantity(quantity, minimum=1)

  @staticmethod
  def validate_return_capacity(available_quantity: int, held_quantity: int) -> None:
    Product.validate_stock(available_quantity)
    # Aggregated active holds can exceed the per-row integer range.
    if type(held_quantity) is not int or held_quantity < 0:
      raise ValidationException("Held quantity must be a nonnegative integer")

    if available_quantity + held_quantity > MAX_STOCK_QUANTITY:
      raise StockCapacityExceeded

  def update_details(self, details: ProductDetailsPatch) -> None:
    self.validate_details(details)

    updated: bool = False

    for name, value in details.items():
      if getattr(self, name) != value:
        self._set(name, value)
        updated = True

    if updated:
      self._set("updated_at", utc_now())

  def correct_stock(self, quantity: int, *, held_quantity: int = 0) -> None:
    self.validate_return_capacity(quantity, held_quantity)
    self._set_stock(quantity)

  def adjust_stock(self, delta: int) -> None:
    self.validate_stock_delta(delta)

    quantity = self.stock_quantity + delta

    if quantity < 0:
      raise InsufficientStock

    if quantity > MAX_STOCK_QUANTITY:
      raise StockLimitExceeded

    self._set_stock(quantity)

  def _set_stock(self, quantity: int) -> None:
    if quantity != self.stock_quantity:
      self._set("stock_quantity", quantity)
      self._set("updated_at", utc_now())
