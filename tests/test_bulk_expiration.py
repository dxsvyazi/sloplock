import asyncio
from dataclasses import replace
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import StockLimitExceeded
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.infrastructure.clock import PostgresClock
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
from stocklock.infrastructure.session_manager import SessionManager
from stocklock.infrastructure.uow import SqlAlchemyUnitOfWork
from stocklock.shared.constraints import MAX_STOCK_QUANTITY
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException
from tests.entity_updates import transition
from tests.test_expiration_worker import seed


def flow(database):
  from stocklock.application.usecases.expiration import ExpireReservationsUseCase

  manager = SessionManager(async_sessionmaker(database.engine, expire_on_commit=False))
  return ExpireReservationsUseCase(
    SqlAlchemyUnitOfWork(manager),
    ReservationService(ReservationRepository(manager)),
    ProductService(ProductRepository(manager)),
  )


def command(ids):
  from stocklock.application.commands.reservation import ExpireReservationsCommand

  return ExpireReservationsCommand(reservation_ids=tuple(ids))


async def test_bulk_groups_stock_returns_and_updates_reservations_once(database):
  pairs = await seed(database, count=1)
  product, first = pairs[0]
  repo = ReservationRepository(database.manager)
  second = replace(first, id=UUID(int=2), quantity=ReservationQuantity(3), key=IdempotencyKey("second"))
  async with database.uow.begin():
    await repo.create(second)
  statements = []

  def capture(connection, cursor, statement, parameters, context, executemany):
    statements.append(statement)

  event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
  try:
    assert set(await flow(database).execute(command([first.id, second.id, first.id]))) == {first.id, second.id}
  finally:
    event.remove(database.engine.sync_engine, "before_cursor_execute", capture)
  assert sum("UPDATE reservations" in sql for sql in statements) == 1
  assert sum("UPDATE products" in sql for sql in statements) == 1
  assert await flow(database).execute(command([first.id, second.id])) == []
  async with database.uow.begin():
    assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == 4
    assert (await repo.find_by_id(first.id)).status is ReservationStatus.expired
    assert (await repo.find_by_id(second.id)).status is ReservationStatus.expired


async def test_bulk_rechecks_status_and_deadline_and_ignores_missing_ids(database):
  pairs = await seed(database, count=5)
  repo = ReservationRepository(database.manager)
  async with database.uow.begin():
    for index, status in ((1, ReservationStatus.cancelled), (2, ReservationStatus.expired)):
      await transition(repo, pairs[index][1].id, status, clock=PostgresClock(database.manager))
    # Insert future and confirmed holds via valid entity lifecycle operations.
    from sqlalchemy import update
    from stocklock.infrastructure.models.reservation import ReservationORM

    now = await PostgresClock(database.manager).now()
    await database.manager.get_session(raises=True).execute(
      update(ReservationORM)
      .where(ReservationORM.id.in_([pairs[3][1].id, pairs[4][1].id]))
      .values(expires_at=now + timedelta(hours=1))
    )
    await transition(repo, pairs[4][1].id, ReservationStatus.confirmed, clock=PostgresClock(database.manager))
  assert await flow(database).execute(command([r.id for _, r in pairs] + [uuid4()])) == [pairs[0][1].id]
  async with database.uow.begin():
    for index, (product, _) in enumerate(pairs):
      assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == (index == 0)


async def test_bulk_failure_rolls_back_transitions_and_prior_product_returns(database, monkeypatch):
  pairs = await seed(database)
  last_product = max(p.id for p, _ in pairs)
  original = ProductRepository.adjust_stock

  async def fail_last(self, id, delta):
    if id == last_product:
      raise RuntimeError("Injected bulk stock failure")
    return await original(self, id, delta)

  monkeypatch.setattr(ProductRepository, "adjust_stock", fail_last)
  with pytest.raises(RuntimeError, match="Injected bulk stock failure"):
    await flow(database).execute(command([r.id for _, r in pairs]))
  async with database.uow.begin():
    for product, reservation in pairs:
      assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == 0
      assert (
        await ReservationRepository(database.manager).find_by_id(reservation.id)
      ).status is ReservationStatus.active


async def test_bulk_skips_locked_reservations_and_revisits_them(database):
  pairs = await seed(database, count=2)
  ids = [r.id for _, r in pairs]

  async def expire():
    return await flow(database).execute(command(ids))

  async with database.uow.begin():
    await ReservationRepository(database.manager).find_by_id(ids[0], for_update=True)
    assert await asyncio.wait_for(asyncio.create_task(expire()), 1) == [ids[1]]
  assert await flow(database).execute(command(ids)) == [ids[0]]


async def test_overlapping_bulk_transactions_return_stock_once(database):
  [(product, first)] = await seed(database, count=1)
  reservations = [first] + [
    replace(first, id=UUID(int=number), key=IdempotencyKey(str(number))) for number in range(2, 11)
  ]
  async with database.uow.begin():
    for reservation in reservations[1:]:
      await ReservationRepository(database.manager).create(reservation)
  ids = [r.id for r in reservations]
  results = await asyncio.gather(*(flow(database).execute(command(batch)) for batch in (ids[:5], ids[5:], ids)))
  assert sorted(id for result in results for id in result) == sorted(ids)
  async with database.uow.begin():
    assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == 10


@pytest.mark.parametrize("operation", ["confirm", "cancel"])
async def test_bulk_coordinates_with_other_terminal_workflows(database, operation):
  from stocklock.domain.errors import ReservationUnavailable
  from stocklock.infrastructure.repositories.confirmation_repository import ConfirmationRepository
  from tests.usecase_driver import ReservationDriver

  pairs = await seed(database, count=1)
  product, reservation = pairs[0]
  driver = ReservationDriver(
    database.uow,
    ProductRepository(database.manager),
    ReservationRepository(database.manager),
    ConfirmationRepository(database.manager),
    clock=PostgresClock(database.manager),
  )
  results = await asyncio.gather(
    flow(database).execute(command([reservation.id])),
    getattr(driver, operation)(reservation.id),
    return_exceptions=True,
  )
  assert all(not isinstance(result, BaseException) or isinstance(result, ReservationUnavailable) for result in results)
  async with database.uow.begin():
    final = await ReservationRepository(database.manager).find_by_id(reservation.id)
    assert final.status in (ReservationStatus.expired, ReservationStatus.cancelled)
    assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == 1
    assert await ConfirmationRepository(database.manager).find_by_reservation_id(reservation.id) is None


async def test_bulk_cancellation_rolls_back_transitions_and_stock(database, monkeypatch):
  pairs = await seed(database)
  original = ProductRepository.adjust_stock

  async def cancel_after_write(self, id, delta):
    await original(self, id, delta)
    raise asyncio.CancelledError

  monkeypatch.setattr(ProductRepository, "adjust_stock", cancel_after_write)
  with pytest.raises(asyncio.CancelledError):
    await flow(database).execute(command([r.id for _, r in pairs]))
  async with database.uow.begin():
    for product, reservation in pairs:
      assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == 0
      assert (
        await ReservationRepository(database.manager).find_by_id(reservation.id)
      ).status is ReservationStatus.active


async def test_bulk_stock_overflow_rolls_back(database):
  from sqlalchemy import update
  from stocklock.infrastructure.models.product import ProductORM

  pairs = await seed(database, count=1)
  product, reservation = pairs[0]
  async with database.uow.begin():
    await database.manager.get_session(raises=True).execute(
      update(ProductORM).where(ProductORM.id == product.id).values(stock_quantity=MAX_STOCK_QUANTITY)
    )
  with pytest.raises(StockLimitExceeded):
    await flow(database).execute(command([reservation.id]))
  async with database.uow.begin():
    assert (await ReservationRepository(database.manager).find_by_id(reservation.id)).status is ReservationStatus.active


@pytest.mark.parametrize("ids", [(), tuple(uuid4() for _ in range(101)), ("invalid",)])
async def test_bulk_rejects_invalid_identifiers_and_batch_sizes(ids):
  from tests.service_doubles import Store, Products, Reservations
  from stocklock.application.usecases.expiration import ExpireReservationsUseCase

  store = Store()
  usecase = ExpireReservationsUseCase(store, ReservationService(Reservations(store)), ProductService(Products(store)))
  with pytest.raises(ValidationException):
    await usecase.execute(command(ids))
  assert not store.active


async def test_grouped_stock_returns_use_product_order_without_frameworks():
  from stocklock.domain.entities.product import Product
  from tests.service_doubles import Store, Products

  store = Store()
  products = Products(store)
  service = ProductService(products)
  ids = [UUID(int=2), UUID(int=1)]
  for id in ids:
    store.products[id] = replace(Product.create(name="Item", sku=str(id), stock_quantity=0), id=id)
  holds = [
    Reservation(
      product_id=id,
      quantity=ReservationQuantity(2),
      key=IdempotencyKey(str(index)),
      created_at=store.now,
      expires_at=store.now + timedelta(minutes=1),
    )
    for index, id in enumerate([ids[0], ids[1], ids[0]])
  ]
  returned = []
  original = products.adjust_stock

  async def record(id, delta):
    returned.append((id, delta.value))
    return await original(id, delta)

  products.adjust_stock = record
  async with store.begin():
    await service.return_stock_many(holds)
  assert returned == [(ids[1], 2), (ids[0], 4)]


async def test_grouped_stock_return_rejects_aggregate_above_stock_limit():
  from tests.service_doubles import Store, Products

  store = Store()
  reservation = Reservation(
    product_id=uuid4(),
    quantity=ReservationQuantity(MAX_STOCK_QUANTITY),
    key=IdempotencyKey("large"),
    created_at=store.now,
    expires_at=store.now + timedelta(minutes=1),
  )
  async with store.begin():
    with pytest.raises(StockLimitExceeded):
      await ProductService(Products(store)).return_stock_many([reservation, reservation])
