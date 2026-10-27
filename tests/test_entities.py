from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import IdempotencyConflict, InsufficientStock, ReservationUnavailable, StockLimitExceeded
from stocklock.shared.constraints import MAX_STOCK_QUANTITY
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def hold(**changes):
  return Reservation(
    **(dict(product_id=uuid4(), quantity=2, key="key", created_at=NOW, expires_at=NOW + timedelta(minutes=1)) | changes)
  )


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
    Product(**(dict(name="Widget", sku="W1", stock_quantity=3) | changes))


@pytest.mark.parametrize("field,value", [("stock_quantity", -1), ("name", "bad"), ("id", uuid4())])
def test_product_fields_are_read_only(field, value):
  product = Product(name="Widget", sku="W1", stock_quantity=3)
  with pytest.raises(FrozenInstanceError):
    setattr(product, field, value)


def test_detail_changes_validate_all_fields_before_mutating():
  product = Product(name="Widget", sku="W1", stock_quantity=3)
  with pytest.raises(ValidationException):
    product.update_details({"name": "Renamed", "sku": " "})
  assert (product.name, product.sku, product.updated_at) == ("Widget", "W1", None)
  product.update_details({"name": "Renamed"})
  assert (product.name, product.sku, product.stock_quantity) == ("Renamed", "W1", 3)
  assert product.updated_at is not None
  timestamp = product.updated_at
  product.update_details({"name": "Renamed"})
  assert product.updated_at == timestamp


def test_stock_methods_preserve_bounds_and_failed_mutations():
  product = Product(name="Widget", sku="W1", stock_quantity=3)
  with pytest.raises(InsufficientStock):
    product.adjust_stock(-4)
  assert (product.stock_quantity, product.updated_at) == (3, None)
  product.adjust_stock(-2)
  assert product.stock_quantity == 1
  with pytest.raises(StockLimitExceeded):
    product.correct_stock(MAX_STOCK_QUANTITY, held_quantity=1)
  assert product.stock_quantity == 1
  product.correct_stock(MAX_STOCK_QUANTITY - 1, held_quantity=1)
  with pytest.raises(StockLimitExceeded):
    product.adjust_stock(2)


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
  assert item.transition(target, instant) is True
  assert item.status is target
  for other in (ReservationStatus.confirmed, ReservationStatus.expired, ReservationStatus.cancelled):
    assert item.transition(other, item.expires_at) is False
  with pytest.raises(FrozenInstanceError):
    item.quantity = 0


def test_expiration_boundary_and_confirmation_factory():
  item = hold()
  with pytest.raises(ReservationUnavailable):
    Confirmation.from_reservation(item)
  with pytest.raises(ReservationUnavailable):
    item.confirm(item.expires_at)
  assert item.status is ReservationStatus.active
  assert item.expire(item.expires_at)
  other = hold()
  other.confirm(NOW)
  result = Confirmation.from_reservation(other)
  assert result.reservation_id == other.id
  with pytest.raises(FrozenInstanceError):
    result.reservation_id = uuid4()


def test_retry_compatibility_belongs_to_reservation():
  item = hold()
  item.ensure_retry(2)
  with pytest.raises(IdempotencyConflict):
    item.ensure_retry(1)


@pytest.mark.parametrize("value", [None, "2026-01-01", 123])
@pytest.mark.parametrize("entity", ["product", "reservation", "confirmation"])
def test_entities_reject_non_datetime_timestamps(entity, value):
  with pytest.raises(ValidationException):
    if entity == "product":
      Product(name="Widget", sku="W1", stock_quantity=0, created_at=value)
    elif entity == "reservation":
      hold(created_at=value)
    else:
      Confirmation(reservation_id=uuid4(), created_at=value)
