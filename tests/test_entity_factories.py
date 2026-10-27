from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.value_objects.product import SKU, ProductName, StockQuantity
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_product_factory_creates_typed_values_and_fresh_metadata():
  first = Product.create(name="Widget", sku="W1", stock_quantity=0)
  second = Product.create(name="Widget", sku="W1", stock_quantity=0)
  assert first.name == ProductName("Widget")
  assert first.sku == SKU("W1")
  assert first.stock_quantity == StockQuantity(0)
  assert first.id != second.id
  assert first.id.version == 7
  assert first.created_at.utcoffset() == timedelta(0)
  assert first.updated_at is None


def test_reservation_factory_uses_supplied_clock_and_deadline():
  item = Reservation.create(
    product_id=uuid4(), quantity=2, key="Key", created_at=NOW, expires_at=NOW + timedelta(minutes=1)
  )
  assert item.quantity == ReservationQuantity(2)
  assert item.key == IdempotencyKey("Key")
  assert item.status is ReservationStatus.active
  assert item.id.version == 7
  assert item.created_at == NOW
  assert item.expires_at == NOW + timedelta(minutes=1)


@pytest.mark.parametrize(
  "field,value", [("name", "Widget"), ("sku", "W1"), ("stock_quantity", 1), ("stock_quantity", ReservationQuantity(1))]
)
def test_product_constructor_requires_domain_types(field, value):
  values = dict(name=ProductName("Widget"), sku=SKU("W1"), stock_quantity=StockQuantity(1))
  with pytest.raises(ValidationException):
    Product(**(values | {field: value}))


@pytest.mark.parametrize("field,value", [("quantity", 1), ("key", "key"), ("quantity", StockQuantity(1))])
def test_reservation_constructor_requires_domain_types(field, value):
  values = dict(
    product_id=uuid4(),
    quantity=ReservationQuantity(1),
    key=IdempotencyKey("key"),
    created_at=NOW,
    expires_at=NOW + timedelta(minutes=1),
  )
  with pytest.raises(ValidationException):
    Reservation(**(values | {field: value}))


@pytest.mark.parametrize("changes", [{"name": "bad"}, {"sku": " "}, {"stock_quantity": True}, {"stock_quantity": -1}])
def test_product_factory_rejects_invalid_values(changes):
  with pytest.raises(ValidationException):
    Product.create(**(dict(name="Widget", sku="W1", stock_quantity=1) | changes))


@pytest.mark.parametrize("changes", [{"quantity": 0}, {"quantity": True}, {"key": " key"}, {"expires_at": NOW}])
def test_reservation_factory_rejects_invalid_values(changes):
  with pytest.raises(ValidationException):
    Reservation.create(
      **(
        dict(product_id=uuid4(), quantity=1, key="key", created_at=NOW, expires_at=NOW + timedelta(minutes=1)) | changes
      )
    )


@pytest.mark.parametrize("metadata", [{"id": uuid4()}, {"created_at": NOW}, {"updated_at": NOW}])
def test_product_factory_does_not_accept_historical_metadata(metadata):
  with pytest.raises(TypeError):
    Product.create(name="Widget", sku="W1", stock_quantity=1, **metadata)


@pytest.mark.parametrize("metadata", [{"id": uuid4()}, {"status": ReservationStatus.confirmed}])
def test_reservation_factory_does_not_accept_identity_or_terminal_state(metadata):
  with pytest.raises(TypeError):
    Reservation.create(
      product_id=uuid4(), quantity=1, key="key", created_at=NOW, expires_at=NOW + timedelta(minutes=1), **metadata
    )


@pytest.mark.parametrize("status", list(ReservationStatus))
def test_hydration_preserves_historical_metadata_and_terminal_states(status):
  product_id, reservation_id = uuid4(), uuid4()
  item = Reservation(
    id=reservation_id,
    product_id=product_id,
    quantity=ReservationQuantity(1),
    key=IdempotencyKey("Key"),
    status=status,
    created_at=NOW,
    expires_at=NOW + timedelta(minutes=1),
  )
  assert item.id == reservation_id
  assert item.product_id == product_id
  assert item.created_at == NOW
  assert item.expires_at == NOW + timedelta(minutes=1)
  assert item.status is status


@pytest.mark.parametrize("field,value", [("name", "Renamed"), ("sku", "W2"), ("sku", ProductName("Renamed"))])
def test_detail_patch_rejects_wrong_types_without_partial_changes(field, value):
  product = Product.create(name="Widget", sku="W1", stock_quantity=1)
  before = (product.name, product.sku, product.updated_at)
  with pytest.raises(ValidationException):
    product.update_details({"name": ProductName("Renamed"), field: value})
  assert (product.name, product.sku, product.updated_at) == before


@pytest.mark.parametrize(
  "operation,value",
  [
    ("correct_stock", 1),
    ("correct_stock", ReservationQuantity(1)),
    ("adjust_stock", 1),
    ("adjust_stock", StockQuantity(1)),
  ],
)
def test_stock_mutations_reject_untyped_and_wrong_domain_values(operation, value):
  product = Product.create(name="Widget", sku="W1", stock_quantity=1)
  with pytest.raises(ValidationException):
    getattr(product, operation)(value)
  assert product.stock_quantity == StockQuantity(1)
  assert product.updated_at is None


def test_equal_value_objects_do_not_touch_update_timestamp():
  from stocklock.domain.value_objects.product import StockDelta

  product = Product.create(name="Widget", sku="W1", stock_quantity=1)
  product.update_details({"name": ProductName("Widget"), "sku": SKU("W1")})
  product.correct_stock(StockQuantity(1))
  product.adjust_stock(StockDelta(0))
  assert product.updated_at is None
