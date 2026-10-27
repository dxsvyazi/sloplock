from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.infrastructure.exceptions import NoActiveSession
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException
from stocklock.shared.utils import utc_now
from tests.entity_updates import set_stock, transition, update_details


def repositories(database):
  reservations = import_module("stocklock.infrastructure.repositories.reservation_repository").ReservationRepository
  confirmations = import_module("stocklock.infrastructure.repositories.confirmation_repository").ConfirmationRepository
  return ProductRepository(database.manager), reservations(database.manager), confirmations(database.manager)


def reservation(product, **changes):
  return Reservation(
    **(dict(product_id=product.id, quantity=2, key=str(uuid4()), expires_at=utc_now() + timedelta(minutes=5)) | changes)
  )


async def test_product_crud_uses_partial_details_and_explicit_stock_operations(database):
  products = ProductRepository(database.manager)
  product = Product(name="Widget", sku="W1", stock_quantity=5)
  async with database.uow.begin():
    assert await products.create(product) == product
    assert await products.find_by_id(uuid4()) is None
    assert await products.adjust_stock(product.id, -3) is not None
    assert await products.adjust_stock(product.id, -3) is None
    changed = await update_details(products, product.id, details={"name": "Renamed"})
    assert (changed.name, changed.sku, changed.stock_quantity) == ("Renamed", "W1", 2)
    assert (await set_stock(products, product.id, 0)).stock_quantity == 0
    assert (await products.adjust_stock(product.id, 2**31 - 1)).stock_quantity == 2**31 - 1
    assert await products.adjust_stock(product.id, 1) is None
    assert (await products.adjust_stock(product.id, -(2**31 - 1))).stock_quantity == 0
    assert await set_stock(products, uuid4(), 1) is None
    assert await update_details(products, uuid4(), details={"sku": "missing"}) is None
  async with database.uow.begin():
    assert (await products.find_by_id(product.id)).stock_quantity == 0
    assert len(await products.find_many(limit=1)) == 1
    assert await products.find_many(start_id=product.id) == []


async def test_repository_access_requires_explicit_transaction(database):
  products, reservations, confirmations = repositories(database)
  for operation in (
    lambda: products.find_by_id(uuid4()),
    lambda: reservations.find_by_id(uuid4()),
    lambda: confirmations.find_by_reservation_id(uuid4()),
  ):
    with pytest.raises(NoActiveSession, match="No active session"):
      await operation()


async def test_reservation_filters_and_irreversible_transitions(database):
  products, reservations, confirmations = repositories(database)
  first = Product(name="Widget", sku="W1", stock_quantity=8)
  second = Product(name="Other", sku="W2", stock_quantity=8)
  active = reservation(first)
  expired = reservation(first, created_at=utc_now() - timedelta(minutes=2), expires_at=utc_now() - timedelta(minutes=1))
  other = reservation(second)
  async with database.uow.begin():
    for product in (first, second):
      await products.create(product)
    for item in (active, expired, other):
      assert await reservations.create(item) == item
    assert await reservations.find_by_id(uuid4()) is None
    assert await reservations.find_by_key(first.id, active.key) == active
    assert await reservations.find_by_key(second.id, active.key) is None
    assert await transition(reservations, expired.id, ReservationStatus.confirmed) is None
    assert await transition(reservations, active.id, ReservationStatus.expired) is None
    assert (await transition(reservations, expired.id, ReservationStatus.expired)).status == ReservationStatus.expired
    assert (
      await transition(reservations, active.id, ReservationStatus.confirmed)
    ).status == ReservationStatus.confirmed
    assert await transition(reservations, active.id, ReservationStatus.cancelled) is None
    assert await transition(reservations, uuid4(), ReservationStatus.cancelled) is None
    result = await confirmations.create(Confirmation(reservation_id=active.id))
    assert await confirmations.create(Confirmation(reservation_id=active.id)) == result
    assert await confirmations.find_by_reservation_id(active.id) == result
    assert await confirmations.find_by_reservation_id(other.id) is None
    with pytest.raises(ValidationException):
      await transition(reservations, other.id, ReservationStatus.active)
    with pytest.raises(ValidationException):
      await confirmations.create(Confirmation(reservation_id=other.id))
    assert [r.id for r in await reservations.find_many(product_id=first.id, status=ReservationStatus.expired)] == [
      expired.id
    ]
    assert len(await reservations.find_many(limit=1)) == 1
    assert all(r.id > active.id for r in await reservations.find_many(start_id=active.id))


@pytest.mark.parametrize("quantity", [-1, True, 1.5, 2**31])
async def test_product_repository_rejects_invalid_stock(database, quantity):
  products = ProductRepository(database.manager)
  async with database.uow.begin():
    product = await products.create(Product(name="Widget", sku="W1", stock_quantity=0))
    with pytest.raises(ValidationException):
      await products.create(Product(name="Widget", sku="W1", stock_quantity=quantity))
    with pytest.raises(ValidationException):
      await set_stock(products, product.id, quantity)


@pytest.mark.parametrize(
  "statement",
  [
    "UPDATE products SET stock_quantity = -1",
    "UPDATE reservations SET quantity = 0",
    "UPDATE reservations SET status = 99",
    "UPDATE reservations SET expires_at = created_at",
    "INSERT INTO confirmations (id, reservation_id, created_at) "
    "SELECT gen_random_uuid(), reservation_id, created_at FROM confirmations",
    "INSERT INTO reservations (id, product_id, quantity, status, key, expires_at, created_at) "
    "SELECT gen_random_uuid(), product_id, quantity, status, key, expires_at, "
    "created_at FROM reservations",
  ],
)
async def test_database_constraints_reject_invalid_writes(database, statement):
  products, reservations, confirmations = repositories(database)
  product = Product(name="Widget", sku="W1", stock_quantity=8)
  item = reservation(product)
  async with database.uow.begin():
    await products.create(product)
    await reservations.create(item)
    await transition(reservations, item.id, ReservationStatus.confirmed)
    await confirmations.create(Confirmation(reservation_id=item.id))
  with pytest.raises(IntegrityError):
    async with database.uow.begin():
      await database.manager.get_session(raises=True).execute(text(statement))
