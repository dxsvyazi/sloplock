from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import IdempotencyConflict, InsufficientStock, ReservationUnavailable, StockLimitExceeded
from stocklock.domain.value_objects.product import SKU, ProductName, StockDelta, StockQuantity
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.shared.constraints import MAX_STOCK_QUANTITY
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def hold(**changes):
  values = (
    dict(product_id=uuid4(), quantity=2, key="key", created_at=NOW, expires_at=NOW + timedelta(minutes=1)) | changes
  )
  values["quantity"] = ReservationQuantity(values["quantity"])
  values["key"] = IdempotencyKey(values["key"])
  return Reservation(**values)


@pytest.mark.parametrize(
  "changes",
  [
    {"name": "bad"},
    {"sku": " "},
    {"stock_quantity": -1},
    {"stock_quantity": True},
    {"id": "bad"},
    {"created_at": NOW.replace(tzinfo=None)},
  ],
)
def test_product_rejects_invalid_construction(changes):
  with pytest.raises(ValidationException):
    Product(**(dict(name=ProductName("Widget"), sku=SKU("W1"), stock_quantity=StockQuantity(3)) | changes))


@pytest.mark.parametrize("field,value", [("stock_quantity", -1), ("name", "bad"), ("id", uuid4())])
def test_product_fields_are_read_only(field, value):
  product = Product.create(name="Widget", sku="W1", stock_quantity=3)
  with pytest.raises(FrozenInstanceError):
    setattr(product, field, value)


def test_detail_changes_validate_all_fields_before_mutating():
  product = Product.create(name="Widget", sku="W1", stock_quantity=3)
  with pytest.raises(ValidationException):
    product.update_details({"name": ProductName("Renamed"), "sku": " "})
  assert (product.name.value, product.sku.value, product.updated_at) == ("Widget", "W1", None)
  product.update_details({"name": ProductName("Renamed")})
  assert (product.name.value, product.sku.value, product.stock_quantity.value) == ("Renamed", "W1", 3)
  assert product.updated_at is not None
  timestamp = product.updated_at
  product.update_details({"name": ProductName("Renamed")})
  assert product.updated_at == timestamp


def test_stock_methods_preserve_bounds_and_failed_mutations():
  product = Product.create(name="Widget", sku="W1", stock_quantity=3)
  with pytest.raises(InsufficientStock):
    product.adjust_stock(StockDelta(-4))
  assert (product.stock_quantity.value, product.updated_at) == (3, None)
  product.adjust_stock(StockDelta(-2))
  assert product.stock_quantity.value == 1
  with pytest.raises(StockLimitExceeded):
    product.correct_stock(StockQuantity(MAX_STOCK_QUANTITY), held_quantity=1)
  assert product.stock_quantity.value == 1
  product.correct_stock(StockQuantity(MAX_STOCK_QUANTITY - 1), held_quantity=1)
  with pytest.raises(StockLimitExceeded):
    product.adjust_stock(StockDelta(2))


@pytest.mark.parametrize(
  "changes",
  [
    {"quantity": 0},
    {"quantity": True},
    {"status": 1},
    {"key": " bad "},
    {"product_id": "bad"},
    {"expires_at": NOW},
    {"created_at": NOW.replace(tzinfo=None)},
  ],
)
def test_reservation_rejects_invalid_construction(changes):
  with pytest.raises(ValidationException):
    hold(**changes)


def test_reservation_rehydrates_history_and_normalizes_utc():
  item = hold(status=ReservationStatus.confirmed, created_at=NOW.astimezone(timezone(timedelta(hours=7))))
  assert item.created_at.utcoffset() == timedelta(0)
  with pytest.raises(ValidationException):
    item.ensure_new()
  with pytest.raises(FrozenInstanceError):
    item.status = ReservationStatus.active


@pytest.mark.parametrize(
  "target", [ReservationStatus.confirmed, ReservationStatus.expired, ReservationStatus.cancelled]
)
def test_reservation_transition_is_guarded_and_irreversible(target):
  item = hold()
  instant = item.expires_at if target is ReservationStatus.expired else NOW
  if target is ReservationStatus.cancelled:
    assert item.cancel() is True
  elif target is ReservationStatus.confirmed:
    assert item.confirm(instant) is True
  else:
    assert item.expire(instant) is True
  assert item.status is target
  assert item.cancel() is False
  assert item.confirm(NOW) is False
  assert item.expire(item.expires_at) is False
  with pytest.raises(FrozenInstanceError):
    item.quantity = 0


def test_expiration_boundary_and_confirmation_factory():
  item = hold()
  with pytest.raises(ReservationUnavailable):
    Confirmation.from_reservation(item)
  assert item.confirm(item.expires_at) is False
  assert item.status is ReservationStatus.active
  assert item.expire(item.expires_at)
  other = hold()
  assert other.confirm(NOW) is True
  result = Confirmation.from_reservation(other)
  assert result.reservation_id == other.id
  with pytest.raises(FrozenInstanceError):
    result.reservation_id = uuid4()


def test_retry_compatibility_belongs_to_reservation():
  item = hold()
  item.ensure_retry(ReservationQuantity(2))
  with pytest.raises(IdempotencyConflict):
    item.ensure_retry(ReservationQuantity(1))


@pytest.mark.parametrize("value", [None, "2026-01-01", 123])
@pytest.mark.parametrize("entity", ["product", "reservation", "confirmation"])
def test_entities_reject_non_datetime_timestamps(entity, value):
  with pytest.raises(ValidationException):
    if entity == "product":
      Product(name=ProductName("Widget"), sku=SKU("W1"), stock_quantity=StockQuantity(0), created_at=value)
    elif entity == "reservation":
      hold(created_at=value)
    else:
      Confirmation(reservation_id=uuid4(), created_at=value)
