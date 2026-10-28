from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text

from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.ports.repositories.product_repository import ProductDetailsSnapshot, ProductStockSnapshot
from stocklock.domain.ports.repositories.reservation_repository import ReservationSnapshot
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.domain.value_objects.product import ProductName, StockDelta, StockQuantity
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException
from tests.service_doubles import Products, Reservations, Store


def product_snapshot(product, kind="ProductDetailsSnapshot"):
  snapshot_type = ProductDetailsSnapshot if kind == "ProductDetailsSnapshot" else ProductStockSnapshot
  return snapshot_type.capture(product)


def reservation_snapshot(reservation):
  return ReservationSnapshot.capture(reservation)


@pytest.mark.parametrize(
  "kind,method", [("ProductDetailsSnapshot", "save_details"), ("ProductStockSnapshot", "save_stock")]
)
async def test_reverted_changes_preserve_persisted_timestamp(kind, method):
  store = Store()
  service = ProductService(Products(store))
  async with store.begin():
    product = await service.create(Product.create(name="Widget", sku="W1", stock_quantity=5))
    original = product_snapshot(product, kind)
    if kind == "ProductDetailsSnapshot":
      product.update_details({"name": ProductName("Renamed")})
      product.update_details({"name": ProductName("Widget")})
    else:
      product.correct_stock(StockQuantity(2))
      product.correct_stock(StockQuantity(5))
    store.fail = method
    result = await getattr(service, method)(product, original=original)
    assert result.updated_at is None
    assert result == store.products[product.id]


async def test_snapshot_stays_unchanged_and_detail_save_preserves_stock():
  store = Store()
  service = ProductService(Products(store))
  async with store.begin():
    product = await service.create(Product.create(name="Widget", sku="W1", stock_quantity=5))
    original = product_snapshot(product)
    product.update_details({"name": ProductName("Renamed")})
    assert original.name.value == "Widget"
    with pytest.raises(FrozenInstanceError):
      original.name = "Changed"
    # Even an unrelated mutation must not be included in a detail save.
    product.adjust_stock(StockDelta(-1))
    result = await service.save_details(product, original=original)
    assert (result.name.value, result.sku.value, result.stock_quantity.value) == ("Renamed", "W1", 5)
    assert result.updated_at == product.updated_at


@pytest.mark.parametrize(
  "kind,method", [("ProductDetailsSnapshot", "save_details"), ("ProductStockSnapshot", "save_stock")]
)
async def test_unchanged_product_does_not_attempt_persistence(kind, method):
  store = Store()
  service = ProductService(Products(store))
  async with store.begin():
    product = await service.create(Product.create(name="Widget", sku="W1", stock_quantity=5))
    original = product_snapshot(product, kind)
    store.fail = method
    assert await getattr(service, method)(product, original=original) == product
    assert store.products[product.id].updated_at is None


@pytest.mark.parametrize(
  "kind,method", [("ProductDetailsSnapshot", "save_details"), ("ProductStockSnapshot", "save_stock")]
)
async def test_product_save_rejects_snapshot_from_another_entity(kind, method):
  store = Store()
  service = ProductService(Products(store))
  async with store.begin():
    product = await service.create(Product.create(name="Widget", sku="W1", stock_quantity=5))
    other = Product.create(name="Other", sku="W2", stock_quantity=2)
    with pytest.raises(ValidationException):
      await getattr(service, method)(product, original=product_snapshot(other, kind))
    assert store.products[product.id] == product


async def test_stock_save_uses_entity_timestamp_and_preserves_details():
  store = Store()
  service = ProductService(Products(store))
  async with store.begin():
    product = await service.create(Product.create(name="Widget", sku="W1", stock_quantity=5))
    original = product_snapshot(product, "ProductStockSnapshot")
    product.correct_stock(StockQuantity(2))
    product.update_details({"name": ProductName("Unrelated")})
    result = await service.save_stock(product, original=original)
    assert (result.name.value, result.stock_quantity.value, result.updated_at) == ("Widget", 2, product.updated_at)


@pytest.mark.parametrize("status", list(ReservationStatus))
async def test_unchanged_reservation_does_not_attempt_a_terminal_write(status):
  store = Store()
  service = ReservationService(Reservations(store))
  item = Reservation(
    product_id=uuid4(),
    quantity=ReservationQuantity(1),
    key=IdempotencyKey("hold"),
    status=status,
    created_at=store.now,
    expires_at=store.now + timedelta(minutes=1),
  )
  async with store.begin():
    store.reservations[item.id] = item
    original = reservation_snapshot(item)
    store.fail = "save_transition"
    assert await service.save_transition(item, original=original) is None
    assert store.reservations[item.id].status is status


async def test_reservation_save_rejects_snapshot_from_another_entity():
  store = Store()
  service = ReservationService(Reservations(store))
  values = dict(
    product_id=uuid4(),
    quantity=ReservationQuantity(1),
    key=IdempotencyKey("hold"),
    expires_at=store.now + timedelta(minutes=1),
  )
  item, other = Reservation(**values), Reservation(**values)
  async with store.begin():
    original = reservation_snapshot(other)
    item.cancel()
    with pytest.raises(ValidationException):
      await service.save_transition(item, original=original)
    assert store.reservations == {}


async def test_postgresql_noop_updates_preserve_row_version(database):
  from stocklock.application.commands.product import CorrectProductStockCommand, UpdateProductCommand
  from stocklock.application.usecases.product import CorrectProductStockUseCase, UpdateProductUseCase

  repository = ProductRepository(database.manager)
  service = ProductService(repository)
  async with database.uow.begin():
    product = await repository.create(Product.create(name="Widget", sku="W1", stock_quantity=5))
    version = await database.manager.get_session().scalar(
      text("SELECT xmin::text FROM products WHERE id=:id"), {"id": product.id}
    )
  await UpdateProductUseCase(database.uow, service).execute(UpdateProductCommand(product_id=product.id, name="Widget"))
  await CorrectProductStockUseCase(database.uow, service).execute(
    CorrectProductStockCommand(product_id=product.id, stock_quantity=5)
  )
  async with database.uow.begin():
    assert (
      await database.manager.get_session().scalar(
        text("SELECT xmin::text FROM products WHERE id=:id"), {"id": product.id}
      )
      == version
    )
    assert (await repository.find_by_id(product.id)).updated_at is None


@pytest.mark.parametrize("operation", ["details", "stock"])
async def test_postgresql_save_persists_exact_entity_timestamp_and_selected_fields(database, monkeypatch, operation):
  repository = ProductRepository(database.manager)
  service = ProductService(repository)
  timestamp = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)
  monkeypatch.setattr("stocklock.domain.entities.product.utc_now", lambda: timestamp)
  async with database.uow.begin():
    product = await repository.create(Product.create(name="Widget", sku="W1", stock_quantity=5))
    product = await service.require(product.id, for_update=True)
    if operation == "details":
      original = ProductDetailsSnapshot.capture(product)
      product.update_details({"name": ProductName("Renamed")})
      product.adjust_stock(StockDelta(-1))
      saved = await service.save_details(product, original=original)
      assert (saved.name.value, saved.sku.value, saved.stock_quantity.value) == ("Renamed", "W1", 5)
    else:
      original = ProductStockSnapshot.capture(product)
      product.correct_stock(StockQuantity(2), held_quantity=await service.active_held_quantity(product.id))
      product.update_details({"name": ProductName("Unrelated")})
      saved = await service.save_stock(product, original=original)
      assert (saved.name.value, saved.sku.value, saved.stock_quantity.value) == ("Widget", "W1", 2)
    assert saved.updated_at == timestamp
    assert saved.created_at == product.created_at
  async with database.uow.begin():
    assert await repository.find_by_id(product.id) == saved


async def test_postgresql_terminal_save_rechecks_deadline_after_domain_mutation(database):
  products = ProductRepository(database.manager)
  repository = ReservationRepository(database.manager)
  service = ReservationService(repository)
  async with database.uow.begin():
    product = await products.create(Product.create(name="Widget", sku="W1", stock_quantity=5))
    now = await service.current_time()
    item = await repository.create(
      Reservation(
        product_id=product.id,
        quantity=ReservationQuantity(1),
        key=IdempotencyKey("hold"),
        created_at=now - timedelta(minutes=2),
        expires_at=now + timedelta(minutes=1),
      )
    )
    item = await service.require(item.id, for_update=True)
    original = reservation_snapshot(item)
    item.confirm(await service.current_time())
    # Deterministically move the persisted deadline past the decision instant.
    await database.manager.get_session().execute(
      text("UPDATE reservations SET expires_at=clock_timestamp()-interval '1 minute' WHERE id=:id"), {"id": item.id}
    )
    assert await service.save_transition(item, original=original) is None
    assert (await repository.find_by_id(item.id)).status is ReservationStatus.active
