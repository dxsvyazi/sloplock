import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.project.container import create_container
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException
from tests.test_retention import remaining, seed


def container_for(database, **settings):
  return create_container(
    session_maker=async_sessionmaker(database.engine, expire_on_commit=False),
    time_settings=TimePolicySettings(_env_file=None, **settings),
  )


async def test_bounded_sweeps_resume_until_history_is_deleted(database):
  from stocklock.infrastructure.workers.retention import RetentionWorker

  await seed(database, (ReservationStatus.confirmed,) * 5, age=timedelta(days=1000))
  container = container_for(database)
  try:
    worker = RetentionWorker(container, timedelta(days=1), batch_size=2, max_batches=2)
    await worker.run_once()
    ids, confirmations = await remaining(database)
    assert len(ids) == len(confirmations) == 1
    await worker.run_once()
    assert await remaining(database) == (set(), set())
  finally:
    await container.close()


async def test_overlapping_workers_cleanup_without_duplicates(database):
  from stocklock.infrastructure.workers.retention import RetentionWorker

  await seed(database, (ReservationStatus.confirmed,) * 8, age=timedelta(days=1000))
  container = container_for(database)
  try:
    await asyncio.gather(*(RetentionWorker(container, timedelta(days=1), batch_size=2).run_once() for _ in range(3)))
    assert await remaining(database) == (set(), set())
  finally:
    await container.close()


async def test_stop_prevents_further_batches(database, monkeypatch):
  from stocklock.infrastructure.workers.retention import RetentionWorker

  await seed(database, (ReservationStatus.cancelled,) * 3, age=timedelta(days=1000))
  stop = asyncio.Event()
  original = ReservationRepository.purge_terminal

  async def stop_after_batch(self, cutoffs, *, limit):
    result = await original(self, cutoffs, limit=limit)
    stop.set()
    return result

  monkeypatch.setattr(ReservationRepository, "purge_terminal", stop_after_batch)
  container = container_for(database)
  try:
    worker = RetentionWorker(container, timedelta(days=1), batch_size=1)
    await worker.run_once(stop=stop)
    assert len((await remaining(database))[0]) == 2
    await worker.run_once(stop=stop)
    assert len((await remaining(database))[0]) == 2
  finally:
    await container.close()


async def test_timeout_rolls_back_deleted_history_and_later_sweep_retries(database, monkeypatch):
  from stocklock.infrastructure.workers.retention import RetentionWorker

  _, [item] = await seed(database, (ReservationStatus.confirmed,), age=timedelta(days=1000))
  original = ReservationRepository.purge_terminal

  async def stall_after_delete(self, cutoffs, *, limit):
    await original(self, cutoffs, limit=limit)
    await asyncio.Event().wait()

  container = container_for(database)
  try:
    worker = RetentionWorker(container, timedelta(days=1), operation_timeout=timedelta(milliseconds=100))
    with monkeypatch.context() as patch:
      patch.setattr(ReservationRepository, "purge_terminal", stall_after_delete)
      with pytest.raises(TimeoutError):
        await worker.run_once()
    assert await remaining(database) == ({item.id}, {item.id})
    await worker.run_once()
    assert await remaining(database) == (set(), set())
  finally:
    await container.close()


async def test_cancellation_propagates_and_releases_transaction(database, monkeypatch):
  from stocklock.infrastructure.workers.retention import RetentionWorker

  _, [item] = await seed(database, (ReservationStatus.confirmed,), age=timedelta(days=1000))
  original = ReservationRepository.purge_terminal
  entered = asyncio.Event()

  async def wait_after_delete(self, cutoffs, *, limit):
    await original(self, cutoffs, limit=limit)
    entered.set()
    await asyncio.Event().wait()

  monkeypatch.setattr(ReservationRepository, "purge_terminal", wait_after_delete)
  container = container_for(database)
  try:
    task = asyncio.create_task(RetentionWorker(container, timedelta(days=1)).run_once())
    try:
      await asyncio.wait_for(entered.wait(), 1)
    finally:
      task.cancel()
    with pytest.raises(asyncio.CancelledError):
      await task
    assert await remaining(database) == ({item.id}, {item.id})
  finally:
    await container.close()


async def test_worker_retries_failed_sweep_and_stops_promptly(database, monkeypatch, caplog):
  from stocklock.infrastructure.workers.retention import RetentionWorker

  await seed(database, (ReservationStatus.confirmed,), age=timedelta(days=1000))
  original = ReservationRepository.purge_terminal
  stop = asyncio.Event()
  failed = False

  async def fail_once(self, cutoffs, *, limit):
    nonlocal failed
    if not failed:
      failed = True
      raise RuntimeError("Injected cleanup failure")
    result = await original(self, cutoffs, limit=limit)
    stop.set()
    return result

  monkeypatch.setattr(ReservationRepository, "purge_terminal", fail_once)
  container = container_for(database)
  try:
    worker = RetentionWorker(container, timedelta(milliseconds=1))
    await asyncio.wait_for(worker.run(stop), 2)
    assert "Retention sweep failed" in caplog.text
    assert await remaining(database) == (set(), set())
    await asyncio.wait_for(worker.run(stop), 1)
  finally:
    await container.close()


async def test_fully_disabled_worker_issues_no_sql(database):
  from stocklock.infrastructure.workers.retention import RetentionWorker

  container = container_for(
    database,
    EXPIRED_RESERVATION_RETENTION_SECONDS=0,
    CANCELLED_RESERVATION_RETENTION_SECONDS=0,
    CONFIRMATION_RETENTION_SECONDS=0,
  )
  statements = []

  def capture(connection, cursor, statement, parameters, context, executemany):
    statements.append(statement)

  event.listen(database.engine.sync_engine, "before_cursor_execute", capture)
  try:
    await RetentionWorker(container, timedelta(days=1)).run_once()
    assert statements == []
  finally:
    event.remove(database.engine.sync_engine, "before_cursor_execute", capture)
    await container.close()


async def test_disabled_cli_exits_without_creating_database_connections(monkeypatch):
  from stocklock.infrastructure.workers import retention

  container = create_container(
    session_maker=async_sessionmaker(),
    time_settings=TimePolicySettings(
      EXPIRED_RESERVATION_RETENTION_SECONDS=0,
      CANCELLED_RESERVATION_RETENTION_SECONDS=0,
      CONFIRMATION_RETENTION_SECONDS=0,
      _env_file=None,
    ),
  )
  monkeypatch.setattr(retention, "create_container", lambda: container)
  await asyncio.wait_for(retention.main(), 1)


@pytest.mark.parametrize(
  "kwargs",
  [
    {"interval": timedelta(0)},
    {"interval": timedelta(seconds=-1)},
    {"batch_size": 0},
    {"batch_size": 101},
    {"batch_size": True},
    {"max_batches": 0},
    {"max_batches": True},
    {"operation_timeout": timedelta(0)},
  ],
)
def test_worker_rejects_invalid_limits(kwargs):
  from stocklock.infrastructure.workers.retention import RetentionWorker

  with pytest.raises((ValueError, ValidationException)):
    RetentionWorker(None, **({"interval": timedelta(days=1)} | kwargs))
