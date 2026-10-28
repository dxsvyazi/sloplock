import asyncio
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError

from stocklock.domain.entities.product import Product
from stocklock.domain.value_objects.product import StockDelta
from stocklock.infrastructure.clock import PostgresClock
from stocklock.infrastructure.models.product import ProductORM
from stocklock.infrastructure.models.reservation import ReservationORM
from stocklock.infrastructure.repositories.confirmation_repository import ConfirmationRepository
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException
from tests.entity_updates import set_stock, transition, update_details
from tests.usecase_driver import ReservationDriver


def setup_repositories(database):
  products = ProductRepository(database.manager)
  reservations = ReservationRepository(database.manager)
  confirmations = ConfirmationRepository(database.manager)
  return (
    products,
    reservations,
    confirmations,
    ReservationDriver(database.uow, products, reservations, confirmations, clock=PostgresClock(database.manager)),
  )


async def create_product(database, products, stock=10):
  product = Product.create(name="Widget", sku="W1", stock_quantity=stock)
  async with database.uow.begin():
    await products.create(product)
  return product


async def reserve(workflows, product, *, key=None, quantity=1):
  return await workflows.reserve(product.id, quantity, key or str(uuid4()))


@pytest.mark.parametrize("operation", ["confirm", "cancel", "expire"])
async def test_terminal_workflow_fetches_locked_reservation_only_once(database, operation):
  products, reservations, _, workflows = setup_repositories(database)
  product = await create_product(database, products)
  item = await reserve(workflows, product, quantity=2)
  if operation == "expire":
    async with database.uow.begin():
      await database.manager.get_session(raises=True).execute(
        text(
          "UPDATE reservations SET created_at = clock_timestamp() - interval '2 minutes', "
          "expires_at = clock_timestamp() - interval '1 minute' WHERE id = :id"
        ),
        {"id": item.id},
      )

  locking_reads = []

  def capture_lock(connection, cursor, statement, parameters, context, executemany):
    if "FROM reservations" in statement and "FOR UPDATE" in statement and "reservations.quantity" in statement:
      locking_reads.append(statement)

  event.listen(database.engine.sync_engine, "before_cursor_execute", capture_lock)
  try:
    await getattr(workflows, operation)(item.id)
  finally:
    event.remove(database.engine.sync_engine, "before_cursor_execute", capture_lock)

  assert len(locking_reads) == 1
  async with database.uow.begin():
    expected = {
      "confirm": ReservationStatus.confirmed,
      "cancel": ReservationStatus.cancelled,
      "expire": ReservationStatus.expired,
    }[operation]
    assert (await reservations.find_by_id(item.id)).status is expected
    assert (await products.find_by_id(product.id)).stock_quantity.value == (8 if operation == "confirm" else 10)


async def race(*operations):
  barrier = asyncio.Barrier(len(operations))

  async def worker(operation):
    await barrier.wait()
    return await operation()

  return await asyncio.wait_for(asyncio.gather(*(worker(op) for op in operations), return_exceptions=True), 15)


async def test_competing_reservations_never_oversubscribe(database):
  from stocklock.domain.errors import InsufficientStock

  products, reservations, _, workflows = setup_repositories(database)
  product = await create_product(database, products, stock=7)
  results = await race(*(lambda: reserve(workflows, product) for _ in range(20)))
  assert sum(not isinstance(result, Exception) for result in results) == 7
  assert sum(isinstance(result, InsufficientStock) for result in results) == 13
  async with database.uow.begin():
    assert (await products.find_by_id(product.id)).stock_quantity.value == 0
    assert sum(item.quantity.value for item in await reservations.find_many()) == 7


async def test_concurrent_reservation_retries_hold_stock_once(database):
  from stocklock.domain.errors import IdempotencyConflict

  products, reservations, _, workflows = setup_repositories(database)
  product = await create_product(database, products)
  results = await race(*(lambda: reserve(workflows, product, key="retry", quantity=2) for _ in range(8)))
  assert all(result == results[0] for result in results)
  async with database.uow.begin():
    assert (await products.find_by_id(product.id)).stock_quantity.value == 8
    assert len(await reservations.find_many()) == 1
  with pytest.raises(IdempotencyConflict):
    await reserve(workflows, product, key="retry", quantity=3)
  other = await create_product(database, products)
  assert (await reserve(workflows, other, key="retry")).product_id == other.id


async def test_concurrent_confirmations_return_one_immutable_result(database):
  products, reservations, confirmations, workflows = setup_repositories(database)
  product = await create_product(database, products)
  item = await reserve(workflows, product, quantity=3)
  results = await race(*(lambda: workflows.confirm(item.id) for _ in range(12)))
  assert all(result == results[0] for result in results)
  assert await workflows.confirm(item.id) == results[0]
  async with database.uow.begin():
    assert (await products.find_by_id(product.id)).stock_quantity.value == 7
    assert (await reservations.find_by_id(item.id)).status is ReservationStatus.confirmed
    assert await confirmations.find_by_reservation_id(item.id) == results[0]
    assert await database.manager.get_session(raises=True).scalar(text("SELECT count(*) FROM confirmations")) == 1


@pytest.mark.parametrize("expired", [False, True])
async def test_cancellation_and_expiration_return_stock_only_once(database, expired):
  products, reservations, _, workflows = setup_repositories(database)
  product = await create_product(database, products)
  item = await reserve(workflows, product, quantity=3)
  if expired:
    async with database.uow.begin():
      await database.manager.get_session(raises=True).execute(
        text(
          "UPDATE reservations SET created_at = clock_timestamp() - interval '2 minutes', "
          "expires_at = clock_timestamp() - interval '1 minute' WHERE id = :id"
        ),
        {"id": item.id},
      )
  results = await race(
    *(lambda: workflows.cancel(item.id) for _ in range(5)),
    *(lambda: workflows.expire(item.id) for _ in range(5)),
  )
  from stocklock.domain.errors import ReservationUnavailable

  assert sum(not isinstance(result, Exception) for result in results) == 1
  assert sum(isinstance(result, ReservationUnavailable) for result in results) == 9
  async with database.uow.begin():
    assert (await products.find_by_id(product.id)).stock_quantity.value == 10
    assert (await reservations.find_by_id(item.id)).status in (ReservationStatus.cancelled, ReservationStatus.expired)


@pytest.mark.parametrize("expired", [False, True])
async def test_confirmation_coordinates_with_cancel_and_expiration(database, expired):
  from stocklock.domain.errors import ReservationUnavailable

  products, reservations, confirmations, workflows = setup_repositories(database)
  product = await create_product(database, products)
  item = await reserve(workflows, product, quantity=3)
  if expired:
    async with database.uow.begin():
      await database.manager.get_session(raises=True).execute(
        text(
          "UPDATE reservations SET created_at = clock_timestamp() - interval '2 minutes', "
          "expires_at = clock_timestamp() - interval '1 minute' WHERE id = :id"
        ),
        {"id": item.id},
      )
  results = await race(
    lambda: workflows.confirm(item.id), lambda: workflows.cancel(item.id), lambda: workflows.expire(item.id)
  )
  assert all(not isinstance(result, Exception) or isinstance(result, ReservationUnavailable) for result in results)
  async with database.uow.begin():
    final = await reservations.find_by_id(item.id)
    confirmation = await confirmations.find_by_reservation_id(item.id)
    stock = (await products.find_by_id(product.id)).stock_quantity.value
    if final.status is ReservationStatus.confirmed:
      assert not expired
      assert confirmation is not None
      assert stock == 7
    else:
      assert final.status in (ReservationStatus.expired, ReservationStatus.cancelled)
      assert confirmation is None
      assert stock == 10


async def test_atomic_deltas_and_partial_details_do_not_lose_updates(database):
  products, _, _, _ = setup_repositories(database)
  product = await create_product(database, products, stock=0)

  async def add_stock():
    async with database.uow.begin():
      return await products.adjust_stock(product.id, StockDelta(1))

  async def rename():
    async with database.uow.begin():
      return await update_details(products, product.id, details={"name": "Renamed"})

  results = await race(*(add_stock for _ in range(15)), rename)
  assert not any(isinstance(result, Exception) for result in results)
  async with database.uow.begin():
    final = await products.find_by_id(product.id)
    assert (final.name.value, final.stock_quantity.value) == ("Renamed", 15)


async def test_absolute_corrections_serialize_with_reservation(database):
  products, _, _, workflows = setup_repositories(database)
  product = await create_product(database, products, stock=5)

  async def correction():
    async with database.uow.begin():
      return await set_stock(products, product.id, 8)

  results = await race(correction, lambda: reserve(workflows, product, quantity=3))
  assert not any(isinstance(result, Exception) for result in results)
  async with database.uow.begin():
    assert (await products.find_by_id(product.id)).stock_quantity.value in (5, 8)


@pytest.mark.parametrize("operation", ["reserve", "confirm", "cancel", "expire"])
async def test_multistep_failure_rolls_back_all_changes(database, operation):
  products, reservations, confirmations, workflows = setup_repositories(database)
  product = await create_product(database, products)
  item = None
  if operation != "reserve":
    item = await reserve(workflows, product, quantity=3)
  async with database.uow.begin():
    session = database.manager.get_session(raises=True)
    if operation == "expire":
      await session.execute(
        text(
          "UPDATE reservations SET created_at = clock_timestamp() - interval '2 minutes', "
          "expires_at = clock_timestamp() - interval '1 minute' WHERE id = :id"
        ),
        {"id": item.id},
      )
    table = {"reserve": "reservations", "confirm": "confirmations", "cancel": "products", "expire": "products"}[
      operation
    ]
    action = "INSERT" if operation in ("reserve", "confirm") else "UPDATE"
    await session.execute(
      text(
        "CREATE FUNCTION reject_write() RETURNS trigger LANGUAGE plpgsql AS "
        "$$ BEGIN RAISE EXCEPTION 'injected write failure'; END $$"
      )
    )
    await session.execute(
      text(f"CREATE TRIGGER reject_write BEFORE {action} ON {table} FOR EACH ROW EXECUTE FUNCTION reject_write()")
    )
  with pytest.raises(DBAPIError, match="injected write failure"):
    if operation == "reserve":
      await reserve(workflows, product, quantity=3)
    else:
      await getattr(workflows, operation)(item.id)
  async with database.uow.begin():
    assert (await products.find_by_id(product.id)).stock_quantity.value == (10 if operation == "reserve" else 7)
    assert len(await reservations.find_many()) == (0 if operation == "reserve" else 1)
    if item:
      assert (await reservations.find_by_id(item.id)).status is ReservationStatus.active
      assert await confirmations.find_by_reservation_id(item.id) is None


async def wait_until_blocked(database, pid):
  async with asyncio.timeout(3):
    while True:
      async with database.engine.connect() as connection:
        if await connection.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": pid}):
          return
      await asyncio.sleep(0.01)


@pytest.mark.parametrize("through_usecase", [False, True], ids=["repository", "usecase"])
async def test_confirmation_waiting_on_lock_cannot_confirm_after_expiration(database, through_usecase):
  products, reservations, confirmations, workflows = setup_repositories(database)
  product = await create_product(database, products)
  item = await reserve(workflows, product, quantity=3)
  start = asyncio.Event()
  pid_queue = asyncio.Queue()

  class ObservedUnitOfWork:
    @asynccontextmanager
    async def begin(self):
      async with database.uow.begin():
        session = database.manager.get_session(raises=True)
        await pid_queue.put(await session.scalar(text("SELECT pg_backend_pid()")))
        yield

  async def confirmer():
    await start.wait()
    if through_usecase:
      from stocklock.application.commands.confirmation import ConfirmReservationCommand
      from stocklock.application.usecases.confirmations import ConfirmReservationUseCase
      from stocklock.domain.services.confirmation_service import ConfirmationService
      from stocklock.domain.services.reservation_service import ReservationService

      usecase = ConfirmReservationUseCase(
        ObservedUnitOfWork(),
        ReservationService(reservations),
        ConfirmationService(confirmations),
        PostgresClock(database.manager),
      )
      return await usecase.execute(ConfirmReservationCommand(reservation_id=item.id))
    async with ObservedUnitOfWork().begin():
      return await transition(reservations, item.id, ReservationStatus.confirmed, clock=PostgresClock(database.manager))

  task = asyncio.create_task(confirmer())
  try:
    async with database.uow.begin():
      session = database.manager.get_session(raises=True)
      await reservations.find_by_id(item.id, for_update=True)
      await session.execute(
        text("UPDATE reservations SET expires_at = clock_timestamp() + interval '100 milliseconds' WHERE id = :id"),
        {"id": item.id},
      )
      start.set()
      await wait_until_blocked(database, await pid_queue.get())
      # Keep the lock past the deadline, without relying on scheduler timing.
      await session.execute(
        text(
          "SELECT pg_sleep(GREATEST(0, EXTRACT(EPOCH FROM "
          "(expires_at - clock_timestamp()))) + 0.02) FROM reservations WHERE id = :id"
        ),
        {"id": item.id},
      )
    if through_usecase:
      from stocklock.domain.errors import ReservationUnavailable

      with pytest.raises(ReservationUnavailable):
        await asyncio.wait_for(task, 5)
    else:
      assert await asyncio.wait_for(task, 5) is None
    assert (await workflows.expire(item.id)).status is ReservationStatus.expired
    async with database.uow.begin():
      assert (await products.find_by_id(product.id)).stock_quantity.value == 10
      assert await confirmations.find_by_reservation_id(item.id) is None
  finally:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("kind", ["product", "reservation"])
async def test_locked_reads_refresh_previously_loaded_orm_rows(database, kind):
  products, reservations, _, workflows = setup_repositories(database)
  product = await create_product(database, products)
  item = await reserve(workflows, product, quantity=3)
  start = asyncio.Event()

  async def writer():
    await start.wait()
    if kind == "product":
      async with database.uow.begin():
        await products.adjust_stock(product.id, StockDelta(2))
    else:
      await workflows.cancel(item.id)

  task = asyncio.create_task(writer())
  try:
    async with database.uow.begin():
      session = database.manager.get_session(raises=True)
      # Hold a strong ORM reference to exercise SQLAlchemy's identity map.
      loaded = await session.get(
        ProductORM if kind == "product" else ReservationORM, product.id if kind == "product" else item.id
      )
      start.set()
      await asyncio.wait_for(task, 5)
      if kind == "product":
        assert loaded.stock_quantity == 7
        assert (await products.find_by_id(product.id, for_update=True)).stock_quantity.value == 9
        assert (await products.adjust_stock(product.id, StockDelta(-1))).stock_quantity.value == 8
      else:
        assert loaded.status is ReservationStatus.active
        assert (await reservations.find_by_id(item.id, for_update=True)).status is ReservationStatus.cancelled
        assert (
          await transition(reservations, item.id, ReservationStatus.confirmed, clock=PostgresClock(database.manager))
          is None
        )
  finally:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def test_stock_return_overflow_rolls_back_terminal_transition(database):
  from stocklock.domain.errors import StockLimitExceeded

  products, reservations, _, workflows = setup_repositories(database)
  product = await create_product(database, products)
  item = await reserve(workflows, product, quantity=3)
  async with database.uow.begin():
    # Simulate legacy/raw data that predates correction capacity enforcement.
    await database.manager.get_session().execute(
      text("UPDATE products SET stock_quantity=:quantity WHERE id=:id"),
      {"quantity": 2**31 - 1, "id": product.id},
    )
  with pytest.raises(StockLimitExceeded):
    await workflows.cancel(item.id)
  async with database.uow.begin():
    assert (await reservations.find_by_id(item.id)).status is ReservationStatus.active
    assert (await products.find_by_id(product.id)).stock_quantity.value == 2**31 - 1


@pytest.mark.parametrize("method", ["confirm", "cancel", "expire"])
async def test_terminal_workflows_on_missing_reservation(database, method):
  from stocklock.domain.errors import NotFound

  _, _, _, workflows = setup_repositories(database)
  with pytest.raises(NotFound):
    await getattr(workflows, method)(uuid4())


async def test_invalid_reservation_does_not_change_stock(database):
  from stocklock.domain.errors import NotFound

  products, reservations, _, workflows = setup_repositories(database)
  product = await create_product(database, products)
  for quantity in (-1, 0, True, 2**31):
    with pytest.raises(ValidationException):
      await reserve(workflows, product, quantity=quantity)
  with pytest.raises(NotFound):
    await workflows.reserve(uuid4(), 1, "test")
  async with database.uow.begin():
    assert (await products.find_by_id(product.id)).stock_quantity.value == 10
    assert await reservations.find_many() == []
