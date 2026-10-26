from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest

from stocklock.application.commands.confirmation import ConfirmReservationCommand, GetConfirmationCommand
from stocklock.application.commands.product import (
  CorrectProductStockCommand,
  CreateProductCommand,
  GetProductCommand,
  ListProductsCommand,
  UpdateProductCommand,
)
from stocklock.application.commands.reservation import (
  CancelReservationCommand,
  CreateReservationCommand,
  ExpireReservationCommand,
  GetReservationCommand,
  ListProductReservationsCommand,
  ListReservationsCommand,
)
from stocklock.application.policies.reservation import ReservationTimePolicy
from stocklock.domain.errors import IdempotencyConflict, NotFound, ReservationUnavailable, StockLimitExceeded
from stocklock.domain.services.confirmation_service import ConfirmationService
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException
from tests.service_doubles import Confirmations, PersistenceTestFailure, Products, Reservations, Store


@pytest.fixture
def flows():
  store = Store()
  services = dict(
    products=ProductService(Products(store)),
    reservations=ReservationService(Reservations(store)),
    confirmations=ConfirmationService(Confirmations(store)),
  )
  modules = {
    name: import_module(f"stocklock.application.usecases.{name}")
    for name in ("products", "reservations", "confirmations")
  }

  def build(name, *dependencies):
    module = next(m for m in modules.values() if hasattr(m, name))
    kwargs = {d: services[d] for d in dependencies}
    if name == "ReserveProductUseCase":
      kwargs["time_policy"] = ReservationTimePolicy(lifetime=timedelta(minutes=5))
    return getattr(module, name)(uow=store, **kwargs)

  return store, build


async def seed(flows):
  _, build = flows
  return await build("CreateProductUseCase", "products").execute(
    CreateProductCommand(name="Widget", sku="W1", stock_quantity=5)
  )


async def reserve(flows, product_id, *, key="retry", quantity=2):
  _, build = flows

  return await build("ReserveProductUseCase", "products", "reservations").execute(
    CreateReservationCommand(
      product_id=product_id,
      quantity=quantity,
      key=key,
    ),
  )


async def test_product_business_flows_and_read_transaction_scopes(flows):
  store, build = flows
  product = await seed(flows)
  changed = await build("UpdateProductUseCase", "products").execute(
    UpdateProductCommand(product_id=product.id, name="Renamed")
  )
  assert (changed.name, changed.sku, changed.stock_quantity) == ("Renamed", "W1", 5)
  corrected = await build("CorrectProductStockUseCase", "products").execute(
    CorrectProductStockCommand(product_id=product.id, stock_quantity=2)
  )
  found = await build("GetProductUseCase", "products").execute(GetProductCommand(product_id=product.id))
  assert found == corrected
  assert found.stock_quantity == 2
  assert await build("ListProductsUseCase", "products").execute(ListProductsCommand()) == [found]
  assert await build("ListProductsUseCase", "products").execute(ListProductsCommand(start_id=product.id)) == []
  assert not store.active


async def test_reserve_and_confirmation_retries_preserve_identity_and_stock(flows):
  store, build = flows
  product = await seed(flows)
  item = await reserve(flows, product.id)
  assert store.products[product.id].stock_quantity == 3
  confirmation_flow = build("ConfirmReservationUseCase", "reservations", "confirmations")
  result = await confirmation_flow.execute(ConfirmReservationCommand(reservation_id=item.id))
  assert await confirmation_flow.execute(ConfirmReservationCommand(reservation_id=item.id)) == result
  store.now = item.expires_at
  retry = await reserve(flows, product.id)
  assert retry.id == item.id
  assert retry.status is ReservationStatus.confirmed
  assert store.products[product.id].stock_quantity == 3
  assert len(store.reservations) == len(store.confirmations) == 1
  with pytest.raises(IdempotencyConflict):
    await reserve(flows, product.id, quantity=3)


@pytest.mark.parametrize("name", ["CancelReservationUseCase", "ExpireReservationUseCase"])
async def test_release_flow_returns_units_once(flows, name):
  store, build = flows
  product = await seed(flows)
  item = await reserve(flows, product.id)
  if name == "ExpireReservationUseCase":
    store.now = item.expires_at
  flow = build(name, "products", "reservations")
  command_type = CancelReservationCommand if name == "CancelReservationUseCase" else ExpireReservationCommand
  command = command_type(reservation_id=item.id)
  assert await flow.execute(command) is not None
  assert await flow.execute(command) is None
  assert store.products[product.id].stock_quantity == 5
  assert store.confirmations == {}
  with pytest.raises(ReservationUnavailable):
    await build("ConfirmReservationUseCase", "reservations", "confirmations").execute(
      ConfirmReservationCommand(reservation_id=item.id)
    )


@pytest.mark.parametrize("operation", ["reserve", "confirm", "cancel", "expire"])
async def test_multistep_failures_roll_back_business_flow(flows, operation):
  store, build = flows
  product = await seed(flows)
  item = await reserve(flows, product.id) if operation != "reserve" else None

  if operation == "expire":
    store.now = item.expires_at

  store.fail = {
    "reserve": "create_reservation",
    "confirm": "create_confirmation",
    "cancel": "adjust_stock",
    "expire": "adjust_stock",
  }[operation]
  with pytest.raises(PersistenceTestFailure, match="Injected persistence failure"):
    if operation == "reserve":
      await reserve(flows, product.id)
    elif operation == "confirm":
      await build("ConfirmReservationUseCase", "reservations", "confirmations").execute(
        ConfirmReservationCommand(reservation_id=item.id)
      )
    else:
      name = "CancelReservationUseCase" if operation == "cancel" else "ExpireReservationUseCase"
      command_type = CancelReservationCommand if operation == "cancel" else ExpireReservationCommand
      await build(name, "products", "reservations").execute(command_type(reservation_id=item.id))
  assert not store.active
  assert store.products[product.id].stock_quantity == (5 if operation == "reserve" else 3)
  assert len(store.reservations) == (0 if operation == "reserve" else 1)
  assert store.confirmations == {}
  if item is not None:
    assert store.reservations[item.id].status is ReservationStatus.active


async def test_expired_confirmation_and_stock_overflow_cannot_partially_transition(flows):
  store, build = flows
  product = await seed(flows)
  item = await reserve(flows, product.id)
  store.now = item.expires_at
  with pytest.raises(ReservationUnavailable):
    await build("ConfirmReservationUseCase", "reservations", "confirmations").execute(
      ConfirmReservationCommand(reservation_id=item.id)
    )
  # Simulate inconsistent legacy data; normal corrections now reserve return capacity.
  store.products[product.id].stock_quantity = 2**31 - 1
  with pytest.raises(StockLimitExceeded):
    await build("ExpireReservationUseCase", "products", "reservations").execute(
      ExpireReservationCommand(reservation_id=item.id)
    )
  assert store.reservations[item.id].status is ReservationStatus.active
  assert store.products[product.id].stock_quantity == 2**31 - 1


async def test_reservation_queries_filter_and_page_and_confirmation_may_be_absent(flows):
  store, build = flows
  product = await seed(flows)
  first = await reserve(flows, product.id, key="first")
  second = await reserve(flows, product.id, key="second")
  assert (
    await build("GetReservationUseCase", "reservations").execute(GetReservationCommand(reservation_id=first.id))
    == first
  )
  assert (
    await build("GetConfirmationUseCase", "reservations", "confirmations").execute(
      GetConfirmationCommand(reservation_id=first.id)
    )
    is None
  )
  await build("CancelReservationUseCase", "products", "reservations").execute(
    CancelReservationCommand(reservation_id=first.id)
  )
  assert await build("ListReservationsUseCase", "reservations").execute(
    ListReservationsCommand(status=ReservationStatus.active)
  ) == [second]
  assert await build("ListProductReservationsUseCase", "products", "reservations").execute(
    ListProductReservationsCommand(product_id=product.id, start_id=first.id, limit=1)
  ) == [second]
  with pytest.raises(NotFound):
    await build("ListProductReservationsUseCase", "products", "reservations").execute(
      ListProductReservationsCommand(product_id=uuid4())
    )
  result = await build("ConfirmReservationUseCase", "reservations", "confirmations").execute(
    ConfirmReservationCommand(reservation_id=second.id)
  )
  assert (
    await build("GetConfirmationUseCase", "reservations", "confirmations").execute(
      GetConfirmationCommand(reservation_id=second.id)
    )
    == result
  )
  assert not store.active


@pytest.mark.parametrize(
  "name, dependencies, command",
  [
    ("GetProductUseCase", ("products",), GetProductCommand(product_id=uuid4())),
    ("GetReservationUseCase", ("reservations",), GetReservationCommand(reservation_id=uuid4())),
    ("ConfirmReservationUseCase", ("reservations", "confirmations"), ConfirmReservationCommand(reservation_id=uuid4())),
    ("GetConfirmationUseCase", ("reservations", "confirmations"), GetConfirmationCommand(reservation_id=uuid4())),
  ],
)
async def test_missing_resources_raise_not_found(flows, name, dependencies, command):
  _, build = flows
  with pytest.raises(NotFound):
    await build(name, *dependencies).execute(command)


async def test_invalid_clock_timestamp_rolls_back_stock_hold(flows):
  store, _ = flows
  product = await seed(flows)
  store.now = store.now.replace(tzinfo=None)
  with pytest.raises(ValidationException):
    await reserve(flows, product.id)
  assert store.products[product.id].stock_quantity == 5
  assert store.reservations == {}
