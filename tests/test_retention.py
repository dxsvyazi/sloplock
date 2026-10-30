import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.application.ports.clock import IClock
from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import ReservationNotFound
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.infrastructure.clock import PostgresClock
from stocklock.infrastructure.models.confirmation import ConfirmationORM
from stocklock.infrastructure.models.reservation import ReservationORM
from stocklock.infrastructure.repositories.confirmation_repository import ConfirmationRepository
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
from stocklock.project.container import create_container
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException
from tests.entity_updates import transition
from tests.usecase_driver import ReservationDriver

NOW = datetime(2026, 10, 28, tzinfo=timezone.utc)


@dataclass
class FrozenClock(IClock):
  value: datetime = NOW

  async def now(self):
    return self.value


async def seed(database, statuses=(ReservationStatus.cancelled,), *, age=timedelta(days=31)):
  repo = ReservationRepository(database.manager)
  products = ProductRepository(database.manager)
  async with database.uow.begin():
    now = await PostgresClock(database.manager).now()
    product = await products.create(Product.create(name="Widget", sku="history", stock_quantity=7))
    items = []
    for index, status in enumerate(statuses):
      due = status is ReservationStatus.expired
      item = await repo.create(
        Reservation(
          product_id=product.id,
          quantity=ReservationQuantity(1),
          key=IdempotencyKey(str(index)),
          created_at=now - timedelta(days=100),
          expires_at=now - timedelta(days=1) if due else now + timedelta(days=1),
        )
      )
      if status is not ReservationStatus.active:
        await transition(repo, item.id, status, clock=PostgresClock(database.manager))
        if status is ReservationStatus.confirmed:
          await ConfirmationRepository(database.manager).create(Confirmation(reservation_id=item.id))
        await database.manager.get_session().execute(
          update(ReservationORM).where(ReservationORM.id == item.id).values(finalized_at=NOW - age)
        )
      items.append(item)
  return product, items


def flow(database, *, policy=None, clock=None):
  from stocklock.application.policies.retention import RetentionPolicy
  from stocklock.application.usecases.retention import CleanupRetentionUseCase
  from stocklock.infrastructure.session_manager import SessionManager
  from stocklock.infrastructure.uow import SqlAlchemyUnitOfWork

  manager = SessionManager(async_sessionmaker(database.engine, expire_on_commit=False))
  return CleanupRetentionUseCase(
    SqlAlchemyUnitOfWork(manager),
    ReservationRepository(manager),
    policy or RetentionPolicy(expired=timedelta(days=30), cancelled=timedelta(days=30), confirmed=timedelta(days=30)),
    clock or FrozenClock(),
  )


async def remaining(database):
  async with database.uow.begin():
    session = database.manager.get_session()
    return set(await session.scalars(select(ReservationORM.id))), set(
      await session.scalars(select(ConfirmationORM.reservation_id))
    )


async def test_cleanup_deletes_all_terminal_states_and_confirmation_without_changing_stock(database):
  product, items = await seed(database, tuple(ReservationStatus))
  active = items[0]
  assert await flow(database).execute() == 3
  assert await remaining(database) == ({active.id}, set())
  async with database.uow.begin():
    assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == 7
  assert await flow(database).execute() == 0


async def test_exact_cutoff_and_status_specific_disabled_retention(database):
  from stocklock.application.policies.retention import RetentionPolicy

  _, items = await seed(
    database,
    (ReservationStatus.cancelled, ReservationStatus.expired, ReservationStatus.confirmed),
    age=timedelta(days=30),
  )
  policy = RetentionPolicy(expired=None, cancelled=timedelta(days=30), confirmed=timedelta(days=31))
  assert await flow(database, policy=policy, clock=FrozenClock(NOW - timedelta(microseconds=1))).execute() == 0
  assert await flow(database, policy=policy).execute() == 1
  assert await remaining(database) == ({items[1].id, items[2].id}, {items[2].id})


async def test_bounded_batches_delete_only_requested_count(database):
  _, items = await seed(database, (ReservationStatus.cancelled,) * 3)
  assert await flow(database).execute(limit=2) == 2
  assert len((await remaining(database))[0]) == 1
  assert await flow(database).execute(limit=2) == 1
  assert await remaining(database) == (set(), set())


async def test_locked_candidates_are_skipped_and_revisited(database):
  _, items = await seed(database, (ReservationStatus.confirmed,) * 2)
  async with database.uow.begin():
    await ReservationRepository(database.manager).find_by_id(items[0].id, for_update=True)
    assert await asyncio.wait_for(asyncio.create_task(flow(database).execute()), 1) == 1
  assert await remaining(database) == ({items[0].id}, {items[0].id})
  assert await flow(database).execute() == 1


async def test_overlapping_cleanup_transactions_delete_each_record_once(database):
  await seed(database, (ReservationStatus.confirmed,) * 8)
  results = await asyncio.gather(*(flow(database).execute(limit=3) for _ in range(4)))
  assert sum(results) == 8
  assert await remaining(database) == (set(), set())


async def test_failure_after_confirmation_delete_rolls_back_entire_batch(database):
  _, items = await seed(database, (ReservationStatus.confirmed,))

  def fail_reservation_delete(connection, cursor, statement, parameters, context, executemany):
    if statement.startswith("DELETE FROM reservations"):
      raise RuntimeError("Injected reservation deletion failure")

  event.listen(database.engine.sync_engine, "before_cursor_execute", fail_reservation_delete)
  try:
    with pytest.raises(RuntimeError, match="Injected reservation deletion failure"):
      await flow(database).execute()
  finally:
    event.remove(database.engine.sync_engine, "before_cursor_execute", fail_reservation_delete)
  assert await remaining(database) == ({items[0].id}, {items[0].id})
  assert await flow(database).execute() == 1


@pytest.mark.parametrize("cleanup_first", [False, True])
async def test_confirmation_retry_coordinates_with_cleanup(database, cleanup_first):
  _, [item] = await seed(database, (ReservationStatus.confirmed,))
  driver = ReservationDriver(
    database.uow,
    ProductRepository(database.manager),
    ReservationRepository(database.manager),
    ConfirmationRepository(database.manager),
    clock=PostgresClock(database.manager),
  )
  entered, release = asyncio.Event(), asyncio.Event()
  original = ReservationRepository.find_by_id

  async def pause_retry(self, id, *, for_update=False):
    result = await original(self, id, for_update=for_update)
    if for_update and not cleanup_first:
      entered.set()
      await release.wait()
    return result

  if cleanup_first:
    # Keep cleanup uncommitted until PostgreSQL reports the retry waiting on its lock.
    blocker_pid = None

    async def purge_then_pause():
      nonlocal blocker_pid
      async with database.uow.begin():
        blocker_pid = await database.manager.get_session().scalar(text("SELECT pg_backend_pid()"))
        count = await ReservationRepository(database.manager).purge_terminal(
          {ReservationStatus.confirmed: NOW - timedelta(days=30)}, limit=100
        )
        entered.set()
        await release.wait()
        return count

    cleanup = asyncio.create_task(purge_then_pause())
    await asyncio.wait_for(entered.wait(), 1)
    retry = asyncio.create_task(driver.confirm(item.id))
    try:
      async with asyncio.timeout(2):
        async with database.engine.connect() as monitor:
          while not await monitor.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE :blocker = ANY(pg_blocking_pids(pid)))"),
            {"blocker": blocker_pid},
          ):
            await asyncio.sleep(0.01)
    finally:
      release.set()
      results = await asyncio.gather(cleanup, retry, return_exceptions=True)
    assert results[0] == 1
    assert isinstance(results[1], ReservationNotFound)
  else:
    # The retry holds the reservation lock, so cleanup must leave both rows intact.
    from unittest.mock import patch

    with patch.object(ReservationRepository, "find_by_id", pause_retry):
      retry = asyncio.create_task(driver.confirm(item.id))
      try:
        await asyncio.wait_for(entered.wait(), 1)
        assert await flow(database).execute() == 0
      finally:
        release.set()
      assert (await retry).reservation_id == item.id
    assert await flow(database).execute() == 1


async def test_transition_timestamps_are_database_times_and_failed_retries_preserve_them(database):
  repo = ReservationRepository(database.manager)
  async with database.uow.begin():
    now = await PostgresClock(database.manager).now()
    product = await ProductRepository(database.manager).create(
      Product.create(name="Widget", sku="times", stock_quantity=0)
    )
    items = []
    for index, status in enumerate(
      (ReservationStatus.cancelled, ReservationStatus.confirmed, ReservationStatus.expired)
    ):
      item = await repo.create(
        Reservation(
          product_id=product.id,
          quantity=ReservationQuantity(1),
          key=IdempotencyKey(str(index)),
          created_at=now - timedelta(days=1),
          expires_at=now - timedelta(hours=1) if status is ReservationStatus.expired else now + timedelta(hours=1),
        )
      )
      assert (
        await database.manager.get_session().scalar(
          select(ReservationORM.finalized_at).where(ReservationORM.id == item.id)
        )
        is None
      )
      assert await transition(repo, item.id, status, clock=PostgresClock(database.manager)) is not None
      finalized = await database.manager.get_session().scalar(
        select(ReservationORM.finalized_at).where(ReservationORM.id == item.id)
      )
      assert now <= finalized <= await PostgresClock(database.manager).now()
      assert await transition(repo, item.id, status, clock=PostgresClock(database.manager)) is None
      assert (
        await database.manager.get_session().scalar(
          select(ReservationORM.finalized_at).where(ReservationORM.id == item.id)
        )
        == finalized
      )
      items.append(item)


async def test_bulk_expiration_sets_finalized_at_in_same_transaction(database):
  _, [item] = await seed(database, (ReservationStatus.active,))
  async with database.uow.begin():
    now = await PostgresClock(database.manager).now()
    await database.manager.get_session().execute(
      update(ReservationORM).where(ReservationORM.id == item.id).values(expires_at=now - timedelta(seconds=1))
    )
    assert len(await ReservationRepository(database.manager).expire_due((item.id,))) == 1
    finalized = await database.manager.get_session().scalar(
      select(ReservationORM.finalized_at).where(ReservationORM.id == item.id)
    )
    assert now <= finalized <= await PostgresClock(database.manager).now()


@pytest.mark.parametrize(
  "statement",
  [
    "UPDATE reservations SET finalized_at = clock_timestamp() WHERE status = 1",
    "UPDATE reservations SET finalized_at = NULL WHERE status <> 1",
  ],
)
async def test_database_rejects_inconsistent_finalization_metadata(database, statement):
  await seed(database, (ReservationStatus.active, ReservationStatus.cancelled))
  with pytest.raises(IntegrityError):
    async with database.uow.begin():
      await database.manager.get_session().execute(text(statement))


async def test_disabled_policy_performs_no_database_work(database):
  from stocklock.application.policies.retention import RetentionPolicy

  statements = []

  def capture(connection, cursor, statement, parameters, context, executemany):
    statements.append(statement)

  event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
  try:
    assert await flow(database, policy=RetentionPolicy(expired=None, cancelled=None, confirmed=None)).execute() == 0
  finally:
    event.remove(database.engine.sync_engine, "before_cursor_execute", capture)
  assert statements == []


@pytest.mark.parametrize("limit", [0, 101, True])
async def test_cleanup_rejects_invalid_batch_sizes_before_transaction(database, limit):
  with pytest.raises(ValidationException):
    await flow(database).execute(limit=limit)


async def test_deleted_history_returns_http_not_found_and_releases_key(database):
  from stocklock.bootstrap import create_app
  from tests.test_api import request

  product, [item] = await seed(database, (ReservationStatus.confirmed,))
  container = create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  app = create_app(container=container)
  async with app.router.lifespan_context(app):
    assert (await request(app, "GET", f"/reservations/{item.id}/confirmation"))[0] == 200
    assert await flow(database).execute() == 1
    for method, suffix in (("GET", ""), ("GET", "/confirmation"), ("POST", "/confirm")):
      code, payload = await request(app, method, f"/reservations/{item.id}{suffix}")
      assert code == 404
      assert payload == {"detail": "Reservation not found"}
    code, payload = await request(app, "POST", f"/products/{product.id}/reservations", {"quantity": 1, "key": "0"})
    assert code == 201
    assert payload["id"] != str(item.id)
