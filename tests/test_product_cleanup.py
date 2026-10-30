import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.application.policies.product_cleanup import ProductCleanupPolicy
from stocklock.application.usecases.product_cleanup import CleanupProductsUseCase
from stocklock.domain.entities.product import Product
from stocklock.infrastructure.models.product import ProductORM
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.infrastructure.workers.product_cleanup import ProductCleanupWorker
from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.project.container import create_container
from stocklock.shared.enums import ProductVisibility, ReservationStatus
from tests.test_retention import NOW, FrozenClock, seed
from tests.test_retention import flow as retention_flow


async def mark_deleted(database, product_id, *, age=timedelta(days=31)):
  async with database.uow.begin():
    await database.manager.get_session().execute(
      update(ProductORM).where(ProductORM.id == product_id).values(deleted_at=NOW - age)
    )


def container_for(database, **settings):
  return create_container(
    session_maker=async_sessionmaker(database.engine, expire_on_commit=False),
    time_settings=TimePolicySettings(_env_file=None, **settings),
  )


def cleanup(database, *, retention=timedelta(days=30)):
  return CleanupProductsUseCase(
    database.uow, ProductRepository(database.manager), ProductCleanupPolicy(retention=retention), FrozenClock()
  )


async def test_cleanup_waits_for_history_and_preserves_visible_products(database):
  product, _ = await seed(database, (ReservationStatus.confirmed,), age=timedelta(days=31))
  await mark_deleted(database, product.id)
  async with database.uow.begin():
    visible = await ProductRepository(database.manager).create(
      Product.create(name="Visible", sku="v", stock_quantity=4)
    )
  assert await cleanup(database).execute() == 0
  assert await retention_flow(database).execute() == 1
  assert await cleanup(database).execute() == 1
  async with database.uow.begin():
    assert await ProductRepository(database.manager).find_by_id(product.id) is None
    assert (await ProductRepository(database.manager).find_by_id(visible.id)).stock_quantity.value == 4


async def test_cutoff_is_inclusive_and_zero_disables(database):
  product, _ = await seed(database, ())
  await mark_deleted(database, product.id, age=timedelta(days=30))
  assert await cleanup(database, retention=None).execute() == 0
  assert await cleanup(database, retention=timedelta(days=31)).execute() == 0
  assert await cleanup(database).execute() == 1


async def test_product_worker_bounds_batches_and_overlapping_workers(database):
  for _ in range(5):
    product, _ = await seed(database, ())
    await mark_deleted(database, product.id, age=timedelta(days=1000))
  container = container_for(database)
  try:
    worker = ProductCleanupWorker(container, timedelta(days=1), batch_size=2, max_batches=2)
    await worker.run_once()
    async with database.uow.begin():
      assert len(await ProductRepository(database.manager).find_many(visibility=ProductVisibility.all)) == 1
    await asyncio.gather(worker.run_once(), ProductCleanupWorker(container, timedelta(days=1)).run_once())
    async with database.uow.begin():
      assert await ProductRepository(database.manager).find_many(visibility=ProductVisibility.all) == []
  finally:
    await container.close()


async def test_disabled_product_worker_cli_does_not_connect(monkeypatch):
  from stocklock.infrastructure.workers import product_cleanup

  container = create_container(
    session_maker=async_sessionmaker(),
    time_settings=TimePolicySettings(DELETED_PRODUCT_RETENTION_SECONDS=0, _env_file=None),
  )
  monkeypatch.setattr(product_cleanup, "create_container", lambda: container)
  await asyncio.wait_for(product_cleanup.main(), 1)


@pytest.mark.parametrize(
  "name",
  [
    "DELETED_PRODUCT_RETENTION_SECONDS",
    "PRODUCT_CLEANUP_INTERVAL_SECONDS",
    "PRODUCT_CLEANUP_BATCH_SIZE",
    "PRODUCT_CLEANUP_MAX_BATCHES",
    "PRODUCT_CLEANUP_OPERATION_TIMEOUT_SECONDS",
  ],
)
@pytest.mark.parametrize("value", [True, -1, 1.2, "1.2"])
def test_cleanup_settings_reject_invalid_limits(name, value):
  with pytest.raises(ValueError):
    TimePolicySettings(_env_file=None, **{name: value})


async def test_product_cleanup_skips_locked_products_and_retries(database):
  product, _ = await seed(database, ())
  await mark_deleted(database, product.id)
  container = container_for(database)
  try:
    async with database.uow.begin():
      await ProductRepository(database.manager).find_by_id(product.id, for_update=True)
      await asyncio.wait_for(ProductCleanupWorker(container, timedelta(days=1)).run_once(), 1)
    await ProductCleanupWorker(container, timedelta(days=1)).run_once()
    async with database.uow.begin():
      assert await ProductRepository(database.manager).find_by_id(product.id) is None
  finally:
    await container.close()


async def test_product_cleanup_timeout_rolls_back_and_retries(database, monkeypatch):
  product, _ = await seed(database, ())
  await mark_deleted(database, product.id)
  original = ProductRepository.purge_deleted

  async def stall(self, cutoff, *, limit):
    await original(self, cutoff, limit=limit)
    await asyncio.Event().wait()

  container = container_for(database)
  try:
    worker = ProductCleanupWorker(container, timedelta(days=1), operation_timeout=timedelta(milliseconds=100))
    with monkeypatch.context() as patch:
      patch.setattr(ProductRepository, "purge_deleted", stall)
      with pytest.raises(TimeoutError):
        await worker.run_once()
    async with database.uow.begin():
      assert await ProductRepository(database.manager).find_by_id(product.id) is not None
    await worker.run_once()
    async with database.uow.begin():
      assert await ProductRepository(database.manager).find_by_id(product.id) is None
  finally:
    await container.close()


async def test_product_cleanup_cancellation_rolls_back(database, monkeypatch):
  product, _ = await seed(database, ())
  await mark_deleted(database, product.id)
  original = ProductRepository.purge_deleted
  entered = asyncio.Event()

  async def stall(self, cutoff, *, limit):
    await original(self, cutoff, limit=limit)
    entered.set()
    await asyncio.Event().wait()

  monkeypatch.setattr(ProductRepository, "purge_deleted", stall)
  container = container_for(database)
  task = asyncio.create_task(ProductCleanupWorker(container, timedelta(days=1)).run_once())
  try:
    await asyncio.wait_for(entered.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
      await task
    async with database.uow.begin():
      assert await ProductRepository(database.manager).find_by_id(product.id) is not None
  finally:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await container.close()
