from dataclasses import dataclass

from stocklock.domain.validation import validate_quantity, validate_text
from stocklock.shared.constraints import MAX_PRODUCT_NAME_LEN, MAX_STOCK_QUANTITY, MIN_PRODUCT_NAME_LEN


@dataclass(frozen=True, slots=True)
class ProductName:
  value: str

  def __post_init__(self) -> None:
    validate_text(self.value, minimum=MIN_PRODUCT_NAME_LEN, maximum=MAX_PRODUCT_NAME_LEN)


@dataclass(frozen=True, slots=True)
class SKU:
  value: str

  def __post_init__(self) -> None:
    validate_text(self.value)


@dataclass(frozen=True, slots=True)
class StockQuantity:
  value: int

  def __post_init__(self) -> None:
    validate_quantity(self.value)


@dataclass(frozen=True, slots=True)
class StockDelta:
  value: int

  def __post_init__(self) -> None:
    validate_quantity(self.value, minimum=-MAX_STOCK_QUANTITY)
