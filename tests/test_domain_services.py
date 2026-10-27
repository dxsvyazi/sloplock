from datetime import timedelta, timezone
from importlib import import_module
from uuid import uuid4

import pytest

from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import (
  IdempotencyConflict,
  InsufficientStock,
  MissingConfirmation,
  NotFound,
  ReservationUnavailable,
  StockLimitExceeded,
)
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException
from tests.entity_updates import set_stock, transition, update_details
from tests.service_doubles import Confirmations, Products, Reservations, Store


@pytest.fixture
async def services():
  store = Store()
  products = import_module("stocklock.domain.services.product_service").ProductService(Products(store))
  reservations = import_module("stocklock.domain.services.reservation_service").ReservationService(Reservations(store))
  confirmations = import_module("stocklock.domain.services.confirmation_service").ConfirmationService(
    Confirmations(store)
  )
  async with store.begin():
    yield store, products, reservations, confirmations


@pytest.mark.parametrize("quantity", [-1, True, 1.5, 2**31])
async def test_invalid_product_cannot_reach_service(services, quantity):
  store, products, _, _ = services
  with pytest.raises(ValidationException):
    await products.create(Product.create(name="Widget", sku="W1", stock_quantity=quantity))
  assert store.products == {}


@pytest.mark.parametrize("details", [{}, {"name": "bad"}, {"sku": " "}, {"name": None}, {"stock_quantity": 9}])
async def test_product_patch_rejects_invalid_fields_without_mutation(services, details):
  store, products, _, _ = services
  product = await products.create(Product.create(name="Widget", sku="W1", stock_quantity=3))
  with pytest.raises(ValidationException):
    await update_details(products, product.id, details=details)
  assert store.products[product.id].name.value == "Widget"
  assert store.products[product.id].stock_quantity.value == 3


async def test_stock_operations_preserve_bounds_and_patch_preserves_stock(services):
  _, products, _, _ = services
  product = await products.create(Product.create(name="Widget", sku="W1", stock_quantity=3))
  assert (await products.hold_stock(product.id, ReservationQuantity(2))).stock_quantity.value == 1
  with pytest.raises(InsufficientStock):
    await products.hold_stock(product.id, ReservationQuantity(2))
  assert (await update_details(products, product.id, details={"name": "Renamed"})).stock_quantity.value == 1
  assert (await set_stock(products, product.id, 2**31 - 1)).stock_quantity.value == 2**31 - 1
  with pytest.raises(StockLimitExceeded):
    await products.return_stock(product.id, ReservationQuantity(1))
  assert (await set_stock(products, product.id, 0)).stock_quantity.value == 0


async def test_product_lookup_reports_missing_product(services):
  _, products, _, _ = services
  with pytest.raises(NotFound):
    await products.require(uuid4(), for_update=True)


@pytest.mark.parametrize("quantity", [-1, 0, True, 2**31])
@pytest.mark.parametrize("operation", ["hold_stock", "return_stock"])
async def test_stock_operations_require_positive_quantities(services, quantity, operation):
  _, products, _, _ = services
  with pytest.raises(ValidationException):
    await getattr(products, operation)(uuid4(), quantity)


@pytest.mark.parametrize(
  "changes",
  [
    {"quantity": 0},
    {"quantity": True},
    {"key": " "},
    {"key": " key "},
    {"product_id": "bad"},
    {"seconds": 0},
    {"seconds": -1},
    {"naive": True},
  ],
)
async def test_invalid_reservation_cannot_reach_service(services, changes):
  store, _, reservations, _ = services
  changes = changes.copy()
  values = dict(product_id=uuid4(), quantity=1, key="key")
  seconds = changes.pop("seconds", 30)
  naive = changes.pop("naive", False)
  values.update(changes)
  expires_at = store.now + timedelta(seconds=seconds)
  if naive:
    expires_at = expires_at.replace(tzinfo=None)
  with pytest.raises(ValidationException):
    await reservations.create(Reservation.create(created_at=store.now, **values, expires_at=expires_at))
  assert store.reservations == {}


async def test_reservation_retry_requires_same_quantity_and_product(services):
  store, _, reservations, _ = services
  product_id = uuid4()
  expires_at = (store.now + timedelta(seconds=30)).astimezone(timezone(timedelta(hours=7)))
  item = await reservations.create(
    Reservation(
      created_at=store.now,
      product_id=product_id,
      quantity=ReservationQuantity(2),
      key=IdempotencyKey("key"),
      expires_at=expires_at,
    )
  )
  assert item.expires_at.utcoffset() == timedelta(0)
  assert item.created_at == store.now
  assert await reservations.find_retry(product_id, IdempotencyKey("key"), ReservationQuantity(2)) == item
  assert await reservations.find_retry(uuid4(), IdempotencyKey("key"), ReservationQuantity(2)) is None
  with pytest.raises(IdempotencyConflict):
    await reservations.find_retry(product_id, IdempotencyKey("key"), ReservationQuantity(1))


async def test_terminal_operations_are_irreversible_and_expiration_is_inclusive(services):
  store, _, reservations, _ = services
  item = await reservations.create(
    Reservation(
      created_at=store.now,
      product_id=uuid4(),
      quantity=ReservationQuantity(2),
      key=IdempotencyKey("key"),
      expires_at=store.now + timedelta(seconds=1),
    )
  )
  assert await transition(reservations, item.id, ReservationStatus.expired) is None
  store.now = item.expires_at
  assert await transition(reservations, item.id, ReservationStatus.confirmed) is None
  assert (await transition(reservations, item.id, ReservationStatus.expired)).status is ReservationStatus.expired
  assert await transition(reservations, item.id, ReservationStatus.cancelled) is None
  with pytest.raises(NotFound):
    await reservations.require(uuid4())


async def test_confirmation_creation_requires_confirmed_reservation_and_preserves_result(services):
  store, _, reservations, confirmations = services
  item = await reservations.create(
    Reservation(
      created_at=store.now,
      product_id=uuid4(),
      quantity=ReservationQuantity(2),
      key=IdempotencyKey("key"),
      expires_at=store.now + timedelta(seconds=30),
    )
  )
  with pytest.raises(ReservationUnavailable):
    await confirmations.create(Confirmation.from_reservation(item))
  assert store.confirmations == {}
  confirmed = await transition(reservations, item.id, ReservationStatus.confirmed)
  result = await confirmations.create(Confirmation.from_reservation(confirmed))
  assert await confirmations.create(Confirmation.from_reservation(confirmed)) == result
  assert await confirmations.require(item.id) == result
  assert await confirmations.get(uuid4()) is None
  with pytest.raises(MissingConfirmation):
    await confirmations.require(uuid4())


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": True}, {"limit": 101}])
async def test_service_pagination_is_validated_without_transport(services, kwargs):
  _, products, reservations, _ = services
  for service in (products, reservations):
    with pytest.raises(ValidationException):
      await service.list(**kwargs)


async def test_reservation_filters_reject_invalid_status(services):
  _, _, reservations, _ = services
  with pytest.raises(ValidationException):
    await reservations.list(status="active")
