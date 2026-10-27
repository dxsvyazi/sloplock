import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import text

from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import StockLimitExceeded
from stocklock.domain.services.product_service import ProductService
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
from stocklock.shared.constraints import MAX_STOCK_QUANTITY
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.utils import utc_now
from tests.entity_updates import set_stock, transition
from tests.service_doubles import Products, Store
from tests.test_reservation_workflows import setup_repositories, wait_until_blocked


@pytest.mark.parametrize("overdue", [False, True])
async def test_correction_preserves_capacity_for_active_holds(overdue):
  store = Store()
  products = ProductService(Products(store))
  async with store.begin():
    product = await products.create(Product(name="Widget", sku="W1", stock_quantity=5))
    hold = Reservation(product_id=product.id, quantity=2, key="hold", expires_at=store.now + timedelta(seconds=1))
    store.reservations[hold.id] = hold
    if overdue:
      store.now = hold.expires_at
    with pytest.raises(StockLimitExceeded):
      await set_stock(products, product.id, MAX_STOCK_QUANTITY - 1)
    assert store.products[product.id].stock_quantity == 5
    corrected = await set_stock(products, product.id, MAX_STOCK_QUANTITY - 2)
    assert corrected.stock_quantity == MAX_STOCK_QUANTITY - 2


@pytest.mark.parametrize("release", ["cancel", "expire"])
async def test_postgresql_correction_leaves_room_for_stock_returns(database, release):
  products, reservations, _, workflows = setup_repositories(database)
  async with database.uow.begin():
    product = await products.create(Product(name="Widget", sku="W1", stock_quantity=5))
  hold = await workflows.reserve(product.id, 2, "hold")
  if release == "expire":
    async with database.uow.begin():
      await database.manager.get_session().execute(
        text(
          "UPDATE reservations SET created_at=clock_timestamp()-interval '2 minutes', "
          "expires_at=clock_timestamp()-interval '1 minute' WHERE id=:id"
        ),
        {"id": hold.id},
      )
  with pytest.raises(StockLimitExceeded):
    async with database.uow.begin():
      await set_stock(products, product.id, MAX_STOCK_QUANTITY)
  async with database.uow.begin():
    assert (await products.find_by_id(product.id)).stock_quantity == 3
    await set_stock(products, product.id, MAX_STOCK_QUANTITY - 2)
  assert await getattr(workflows, release)(hold.id) is not None
  async with database.uow.begin():
    assert (await products.find_by_id(product.id)).stock_quantity == MAX_STOCK_QUANTITY
    assert (await reservations.find_by_id(hold.id)).status is not ReservationStatus.active


async def test_correction_counts_only_active_holds_for_its_product(database):
  products = ProductRepository(database.manager)
  reservations = ReservationRepository(database.manager)
  async with database.uow.begin():
    first = await products.create(Product(name="First", sku="F", stock_quantity=5))
    other = await products.create(Product(name="Other", sku="O", stock_quantity=5))
    now = utc_now()
    for product in (first, other):
      hold = await reservations.create(
        Reservation(
          product_id=product.id, quantity=2, key="hold", created_at=now, expires_at=now + timedelta(minutes=1)
        )
      )
      if product.id == first.id:
        await transition(reservations, hold.id, ReservationStatus.cancelled)
    assert (await set_stock(products, first.id, MAX_STOCK_QUANTITY)).stock_quantity == MAX_STOCK_QUANTITY


async def test_correction_reads_holds_committed_during_product_lock_wait(database):
  products, _, _, workflows = setup_repositories(database)
  async with database.uow.begin():
    product = await products.create(Product(name="Widget", sku="W1", stock_quantity=5))
  pid_queue = asyncio.Queue()
  start = asyncio.Event()

  async def correction():
    await start.wait()
    async with database.uow.begin():
      await pid_queue.put(await database.manager.get_session().scalar(text("SELECT pg_backend_pid()")))
      return await set_stock(products, product.id, MAX_STOCK_QUANTITY)

  task = asyncio.create_task(correction())
  try:
    async with database.uow.begin():
      await products.find_by_id(product.id, for_update=True)
      start.set()
      await wait_until_blocked(database, await asyncio.wait_for(pid_queue.get(), 3))
      await products.adjust_stock(product.id, -2)
      await ReservationRepository(database.manager).create(
        Reservation(product_id=product.id, quantity=2, key="concurrent", expires_at=utc_now() + timedelta(minutes=1))
      )
    with pytest.raises(StockLimitExceeded):
      await asyncio.wait_for(task, 5)
    async with database.uow.begin():
      assert (await products.find_by_id(product.id)).stock_quantity == 3
  finally:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("terminal", ["cancel", "expire", "confirm"])
async def test_correction_racing_terminal_transition_preserves_return_capacity(database, terminal):
  from tests.test_reservation_workflows import race

  products, reservations, _, workflows = setup_repositories(database)
  async with database.uow.begin():
    product = await products.create(Product(name="Widget", sku="W1", stock_quantity=5))
  hold = await workflows.reserve(product.id, 2, "hold")
  if terminal == "expire":
    async with database.uow.begin():
      await database.manager.get_session().execute(
        text(
          "UPDATE reservations SET created_at=clock_timestamp()-interval '2 minutes', "
          "expires_at=clock_timestamp()-interval '1 minute' WHERE id=:id"
        ),
        {"id": hold.id},
      )

  async def correct():
    async with database.uow.begin():
      return await set_stock(products, product.id, MAX_STOCK_QUANTITY - 2)

  results = await race(correct, lambda: getattr(workflows, terminal)(hold.id))
  assert not any(isinstance(result, Exception) for result in results)
  async with database.uow.begin():
    final = await reservations.find_by_id(hold.id)
    assert final.status is not ReservationStatus.active
    assert (await products.find_by_id(product.id)).stock_quantity <= MAX_STOCK_QUANTITY


async def test_correction_racing_reservation_cannot_remove_stock_return_capacity(database):
  from tests.test_reservation_workflows import race

  products, reservations, _, workflows = setup_repositories(database)
  async with database.uow.begin():
    product = await products.create(Product(name="Widget", sku="W1", stock_quantity=5))

  async def correct():
    async with database.uow.begin():
      return await set_stock(products, product.id, MAX_STOCK_QUANTITY - 1)

  results = await race(correct, lambda: workflows.reserve(product.id, 2, "hold"))
  assert not isinstance(results[1], Exception)
  assert not isinstance(results[0], Exception) or isinstance(results[0], StockLimitExceeded)
  async with database.uow.begin():
    available = (await products.find_by_id(product.id)).stock_quantity
    active = await reservations.find_many(product_id=product.id, status=ReservationStatus.active)
    assert available + sum(r.quantity for r in active) <= MAX_STOCK_QUANTITY
  assert await workflows.cancel(results[1].id) is not None


async def test_api_rejects_correction_without_stock_return_capacity(database):
  from sqlalchemy.ext.asyncio import async_sessionmaker
  from stocklock.bootstrap import create_app
  from stocklock.project.container import create_container
  from tests.test_api import request

  app = create_app(
    container=create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  )
  async with app.router.lifespan_context(app):
    status, product = await request(app, "POST", "/products", {"name": "Widget", "sku": "W1", "stock_quantity": 5})
    assert status == 201
    path = f"/products/{product['id']}"
    status, hold = await request(app, "POST", path + "/reservations", {"quantity": 2, "key": "hold"})
    assert status == 201
    status, _ = await request(app, "PATCH", path + "/stock", {"stock_quantity": MAX_STOCK_QUANTITY})
    assert status == 409
    status, product = await request(app, "GET", path)
    assert status == 200
    assert product["stock_quantity"] == 3
    status, _ = await request(app, "PATCH", path + "/stock", {"stock_quantity": MAX_STOCK_QUANTITY - 2})
    assert status == 200
    status, _ = await request(app, "POST", f"/reservations/{hold['id']}/cancel")
    assert status == 200
    _, product = await request(app, "GET", path)
    assert product["stock_quantity"] == MAX_STOCK_QUANTITY
