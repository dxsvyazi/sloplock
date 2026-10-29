from datetime import timedelta

import pytest

from stocklock.application.commands.product import (
  DeleteProductCommand,
  GetProductCommand,
  ListProductsCommand,
  UpdateProductCommand,
)
from stocklock.application.commands.reservation import CreateReservationCommand, ListReservationsCommand
from stocklock.application.usecases.product import DeleteProductUseCase, GetProductUseCase, ListProductsUseCase
from stocklock.application.usecases.product import UpdateProductUseCase
from stocklock.application.usecases.reservation import ListReservationsUseCase, ReserveProductUseCase
from stocklock.application.policies.reservation import ReservationTimePolicy
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import ProductHasActiveReservations, ProductNotFound
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.shared.enums import DeletionMode, ProductVisibility
from tests.service_doubles import Clock, Products, Reservations, Store, PersistenceTestFailure


def setup():
  store = Store()
  product = Product.create(name="Widget", sku="widget", stock_quantity=10)
  store.products[product.id] = product
  products = ProductService(Products(store))
  return store, product, products, DeleteProductUseCase(store, products, Clock(store))


def test_domain_soft_deletion_is_idempotent_and_normalizes_utc():
  _, product, _, _ = setup()
  at = product.created_at + timedelta(seconds=1)
  product.soft_delete(at)
  assert product.deleted_at == product.updated_at == at
  product.soft_delete(at + timedelta(days=1))
  assert product.deleted_at == product.updated_at == at
  assert product.stock_quantity.value == 10


async def test_soft_deletion_hides_product_and_preserves_timestamp():
  store, product, products, delete = setup()
  await delete.execute(DeleteProductCommand(product_id=product.id))
  assert store.products[product.id].deleted_at == store.now
  store.now += timedelta(days=1)
  await delete.execute(DeleteProductCommand(product_id=product.id))
  assert store.products[product.id].deleted_at == store.now - timedelta(days=1)
  with pytest.raises(ProductNotFound):
    await GetProductUseCase(store, products).execute(GetProductCommand(product_id=product.id))
  assert (
    await GetProductUseCase(store, products).execute(GetProductCommand(product_id=product.id, include_deleted=True))
  ).deleted_at is not None
  assert await ListProductsUseCase(store, products).execute(ListProductsCommand()) == []
  assert (
    len(await ListProductsUseCase(store, products).execute(ListProductsCommand(visibility=ProductVisibility.deleted)))
    == 1
  )
  with pytest.raises(ProductNotFound):
    await UpdateProductUseCase(store, products).execute(UpdateProductCommand(product_id=product.id, name="New name"))
  reserve = ReserveProductUseCase(
    store,
    products,
    ReservationService(Reservations(store)),
    ReservationTimePolicy(lifetime=timedelta(minutes=5)),
    Clock(store),
  )
  with pytest.raises(ProductNotFound):
    await reserve.execute(CreateReservationCommand(product_id=product.id, quantity=1, key="retry"))


@pytest.mark.parametrize("mode", list(DeletionMode))
@pytest.mark.parametrize("overdue", [False, True])
async def test_stored_active_hold_blocks_both_modes(mode, overdue):
  store, product, _, delete = setup()
  created = store.now - timedelta(days=2) if overdue else store.now
  reservation = Reservation.create(
    product_id=product.id,
    quantity=1,
    key="hold",
    created_at=created,
    expires_at=created + timedelta(days=1),
  )
  store.reservations[reservation.id] = reservation
  with pytest.raises(ProductHasActiveReservations):
    await delete.execute(DeleteProductCommand(product_id=product.id, mode=mode))
  assert store.products[product.id].deleted_at is None
  assert store.products[product.id].stock_quantity.value == 10


async def test_hard_deletion_removes_history_and_soft_preserves_it():
  store, product, _, delete = setup()
  reservation = Reservation.create(
    product_id=product.id,
    quantity=1,
    key="hold",
    created_at=store.now,
    expires_at=store.now + timedelta(days=1),
  )
  reservation.cancel()
  store.reservations[reservation.id] = reservation
  await delete.execute(DeleteProductCommand(product_id=product.id))
  assert reservation.id in store.reservations
  listing = ListReservationsUseCase(store, ReservationService(Reservations(store)))
  assert len(await listing.execute(ListReservationsCommand())) == 1
  assert await listing.execute(ListReservationsCommand(product_visibility=ProductVisibility.visible)) == []
  assert len(await listing.execute(ListReservationsCommand(product_visibility=ProductVisibility.deleted))) == 1
  await delete.execute(DeleteProductCommand(product_id=product.id, mode=DeletionMode.hard))
  assert not store.products and not store.reservations
  with pytest.raises(ProductNotFound):
    await delete.execute(DeleteProductCommand(product_id=product.id, mode=DeletionMode.hard))


@pytest.mark.parametrize("mode,operation", [(DeletionMode.soft, "save_deletion"), (DeletionMode.hard, "hard_delete")])
async def test_deletion_failure_rolls_back(mode, operation):
  store, product, _, delete = setup()
  store.fail = operation
  with pytest.raises(PersistenceTestFailure):
    await delete.execute(DeleteProductCommand(product_id=product.id, mode=mode))
  assert store.products[product.id].deleted_at is None


@pytest.mark.parametrize("operation", ["details", "correction", "delta"])
def test_deleted_domain_product_cannot_be_edited(operation):
  from stocklock.domain.value_objects.product import ProductName, StockQuantity, StockDelta

  store, product, _, _ = setup()
  product.soft_delete(store.now)
  with pytest.raises(ProductNotFound):
    if operation == "details":
      product.update_details({"name": ProductName("New name")})
    elif operation == "correction":
      product.correct_stock(StockQuantity(5))
    else:
      product.adjust_stock(StockDelta(1))
