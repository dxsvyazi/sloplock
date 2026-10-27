from dataclasses import FrozenInstanceError

import pytest

from stocklock.domain.value_objects.product import SKU, ProductName, StockDelta, StockQuantity
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.shared.constraints import MAX_STOCK_QUANTITY
from stocklock.shared.exceptions import ValidationException


@pytest.mark.parametrize(
  "kind,valid",
  [
    (StockQuantity, [0, MAX_STOCK_QUANTITY]),
    (StockDelta, [-MAX_STOCK_QUANTITY, 0, MAX_STOCK_QUANTITY]),
    (ReservationQuantity, [1, MAX_STOCK_QUANTITY]),
  ],
)
def test_numeric_values_preserve_bounds(kind, valid):
  for value in valid:
    assert kind(value).value == value


@pytest.mark.parametrize("kind", [StockQuantity, StockDelta, ReservationQuantity])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, MAX_STOCK_QUANTITY + 1, -MAX_STOCK_QUANTITY - 1])
def test_numeric_values_reject_non_integer_and_out_of_range_inputs(kind, value):
  with pytest.raises(ValidationException):
    kind(value)


def test_zero_is_stock_but_cannot_be_reserved():
  assert StockQuantity(0).value == 0
  with pytest.raises(ValidationException):
    ReservationQuantity(0)
  with pytest.raises(ValidationException):
    StockQuantity(-1)


@pytest.mark.parametrize("value", ["", "abc", " name", "name ", "x" * 257, 123, None])
def test_product_name_constraints(value):
  with pytest.raises(ValidationException):
    ProductName(value)


@pytest.mark.parametrize("value", ["", " ", " SKU", "SKU ", None, 123])
def test_sku_constraints(value):
  with pytest.raises(ValidationException):
    SKU(value)


@pytest.mark.parametrize("value", ["", " key", "key ", "a\x00b", "x" * 257, "😀" * 257, "\ud800", None, 1])
def test_idempotency_key_constraints(value):
  with pytest.raises(ValidationException):
    IdempotencyKey(value)


@pytest.mark.parametrize("value", ["Key", "key", "a b", "😀" * 256])
def test_keys_preserve_exact_identity(value):
  assert IdempotencyKey(value).value == value


@pytest.mark.parametrize(
  "kind,value",
  [
    (ProductName, "Widget"),
    (SKU, "W1"),
    (StockQuantity, 2),
    (StockDelta, -2),
    (ReservationQuantity, 2),
    (IdempotencyKey, "key"),
  ],
)
def test_value_objects_are_immutable_and_compare_by_type_and_value(kind, value):
  item = kind(value)
  assert item == kind(value)
  assert hash(item) == hash(kind(value))
  assert item != value
  with pytest.raises(FrozenInstanceError):
    item.value = value
  assert not hasattr(item, "__dict__")


def test_distinct_domain_quantities_do_not_compare_equal():
  assert StockQuantity(2) != ReservationQuantity(2)
