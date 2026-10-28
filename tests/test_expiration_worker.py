import asyncio
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.infrastructure.clock import PostgresClock
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
from stocklock.project.container import create_container
from stocklock.shared.enums import ReservationStatus


async def seed(database, count=3):
  products = ProductRepository(database.manager)
  reservations = ReservationRepository(database.manager)
  async with database.uow.begin():
    now = await PostgresClock(database.manager).now()
    pairs = []
    for number in range(1, count + 1):
      product = await products.create(Product.create(name="Item", sku=str(number), stock_quantity=0))
      item = await reservations.create(
        Reservation(
          id=UUID(int=number),
          product_id=product.id,
          quantity=ReservationQuantity(1),
          key=IdempotencyKey(str(number)),
          created_at=now - timedelta(minutes=2),
          expires_at=now - timedelta(minutes=1),
        )
      )
      pairs.append((product, item))
    return pairs


async def test_overlapping_sweeps_return_stock_once(database):
  from stocklock.infrastructure.workers.expiration import ExpirationWorker

  pairs = await seed(database)
  container = create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  try:
    workers = [ExpirationWorker(container, timedelta(seconds=1), batch_size=1) for _ in range(2)]
    await asyncio.gather(*(worker.run_once() for worker in workers))
    async with database.uow.begin():
      for product, item in pairs:
        assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == 1
        assert (await ReservationRepository(database.manager).find_by_id(item.id)).status is ReservationStatus.expired
  finally:
    await container.close()


async def test_failed_hold_rolls_back_and_does_not_starve_later_pages(database, monkeypatch):
  from stocklock.infrastructure.workers.expiration import ExpirationWorker

  pairs = await seed(database)
  original = ProductRepository.adjust_stock

  async def fail_first(self, id, delta):
    if id == pairs[0][0].id:
      raise RuntimeError("Injected stock return failure")
    return await original(self, id, delta)

  monkeypatch.setattr(ProductRepository, "adjust_stock", fail_first)
  container = create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  try:
    await ExpirationWorker(container, timedelta(seconds=1), batch_size=1).run_once()
    async with database.uow.begin():
      for index, (product, item) in enumerate(pairs):
        assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == (
          0 if index == 0 else 1
        )
        expected = ReservationStatus.active if index == 0 else ReservationStatus.expired
        assert (await ReservationRepository(database.manager).find_by_id(item.id)).status is expected
  finally:
    await container.close()


async def test_cancellation_propagates_from_bulk_workflow(database, monkeypatch):
  from stocklock.application.usecases.expiration import ExpireReservationsUseCase
  from stocklock.infrastructure.workers.expiration import ExpirationWorker

  await seed(database, count=1)

  async def cancel(self, command):
    raise asyncio.CancelledError

  monkeypatch.setattr(ExpireReservationsUseCase, "execute", cancel)
  container = create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  try:
    with pytest.raises(asyncio.CancelledError):
      await ExpirationWorker(container, timedelta(seconds=1)).run_once()
  finally:
    await container.close()


async def test_worker_uses_one_bulk_workflow_for_a_page(database, monkeypatch):
  from stocklock.application.usecases.reservation import TryExpireReservationUseCase
  from stocklock.infrastructure.workers.expiration import ExpirationWorker

  pairs = await seed(database)

  async def individual_is_unexpected(self, command):
    pytest.fail("Successful bulk expiration must not use individual workflows")

  monkeypatch.setattr(TryExpireReservationUseCase, "execute", individual_is_unexpected)
  container = create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  try:
    await ExpirationWorker(container, timedelta(seconds=1)).run_once()
    async with database.uow.begin():
      for _, item in pairs:
        assert (await ReservationRepository(database.manager).find_by_id(item.id)).status is ReservationStatus.expired
  finally:
    await container.close()


async def test_bulk_failure_falls_back_without_starving_other_holds(database, monkeypatch):
  from stocklock.infrastructure.workers.expiration import ExpirationWorker

  pairs = await seed(database)
  original = ProductRepository.adjust_stock

  async def fail_first(self, id, delta):
    if id == pairs[0][0].id:
      raise RuntimeError("Injected stock return failure")
    return await original(self, id, delta)

  monkeypatch.setattr(ProductRepository, "adjust_stock", fail_first)
  container = create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  try:
    await ExpirationWorker(container, timedelta(seconds=1)).run_once()
    async with database.uow.begin():
      for index, (product, item) in enumerate(pairs):
        assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == (index != 0)
        assert (await ReservationRepository(database.manager).find_by_id(item.id)).status is (
          ReservationStatus.active if index == 0 else ReservationStatus.expired
        )
  finally:
    await container.close()


async def test_bulk_timeout_falls_back_to_individual_expiration(database, monkeypatch):
  from stocklock.application.usecases.expiration import ExpireReservationsUseCase
  from stocklock.infrastructure.workers.expiration import ExpirationWorker

  pairs = await seed(database)

  async def stall(self, command):
    await asyncio.Event().wait()

  monkeypatch.setattr(ExpireReservationsUseCase, "execute", stall)
  container = create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  try:
    await ExpirationWorker(container, timedelta(seconds=1), operation_timeout=timedelta(milliseconds=100)).run_once()
    async with database.uow.begin():
      for product, item in pairs:
        assert (await ProductRepository(database.manager).find_by_id(product.id)).stock_quantity.value == 1
        assert (await ReservationRepository(database.manager).find_by_id(item.id)).status is ReservationStatus.expired
  finally:
    await container.close()


async def test_bounded_sweeps_continue_past_failed_pages(database, monkeypatch):
  from stocklock.infrastructure.workers.expiration import ExpirationWorker

  pairs = await seed(database, count=2)
  original = ProductRepository.adjust_stock

  async def fail_first(self, id, delta):
    if id == pairs[0][0].id:
      raise RuntimeError("Injected stock return failure")
    return await original(self, id, delta)

  monkeypatch.setattr(ProductRepository, "adjust_stock", fail_first)
  container = create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  try:
    worker = ExpirationWorker(container, timedelta(seconds=1), batch_size=1, max_batches=1)
    await worker.run_once()
    await worker.run_once()
    async with database.uow.begin():
      assert (
        await ReservationRepository(database.manager).find_by_id(pairs[1][1].id)
      ).status is ReservationStatus.expired
  finally:
    await container.close()


async def test_main_closes_container_on_cancellation(monkeypatch):
  from stocklock.infrastructure.workers import expiration
  from stocklock.project.configs.time_policy import TimePolicySettings

  closed = False

  class Container:
    async def get(self, cls):
      assert cls is TimePolicySettings
      return TimePolicySettings()

    async def close(self):
      nonlocal closed
      closed = True

  async def cancel(self, stop):
    raise asyncio.CancelledError

  monkeypatch.setattr(expiration, "create_container", Container)
  monkeypatch.setattr(expiration.ExpirationWorker, "run", cancel)
  with pytest.raises(asyncio.CancelledError):
    await expiration.main()
  assert closed


async def test_locked_hold_times_out_and_later_candidates_still_expire(database):
  from stocklock.infrastructure.workers.expiration import ExpirationWorker

  pairs = await seed(database, count=2)
  container = create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  try:
    worker = ExpirationWorker(container, timedelta(seconds=1))
    worker.operation_timeout = timedelta(milliseconds=200)
    async with database.uow.begin():
      await ReservationRepository(database.manager).find_by_id(pairs[0][1].id, for_update=True)
      await asyncio.wait_for(worker.run_once(), timeout=2)
      assert (
        await ReservationRepository(database.manager).find_by_id(pairs[0][1].id)
      ).status is ReservationStatus.active
      assert (
        await ReservationRepository(database.manager).find_by_id(pairs[1][1].id)
      ).status is ReservationStatus.expired
    await worker.run_once()
    async with database.uow.begin():
      assert (
        await ReservationRepository(database.manager).find_by_id(pairs[0][1].id)
      ).status is ReservationStatus.expired
      assert (await ProductRepository(database.manager).find_by_id(pairs[0][0].id)).stock_quantity.value == 1
  finally:
    await container.close()
