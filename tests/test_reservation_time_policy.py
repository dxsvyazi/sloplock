import asyncio
from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.api.v1.mappers.reservation import create_request_to_command
from stocklock.api.v1.schemas.reservation import CreateReservationRequest
from stocklock.application.commands.reservation import CreateReservationCommand
from stocklock.application.policies.reservation import ReservationTimePolicy
from stocklock.application.usecases.reservations import ReserveProductUseCase
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.project.persistence import create_persistence_container
from stocklock.shared.exceptions import ValidationException
from tests.conftest import Database
from tests.service_doubles import Products, Reservations, Store


async def seed(store: Store) -> Product:
  async with store.begin():
    return await ProductService(Products(store)).create(name="Widget", sku="W1", stock_quantity=5)


def command(product_id: UUID) -> CreateReservationCommand:
  return create_request_to_command(product_id, CreateReservationRequest(quantity=2, key="key"))


def flow(store: Store, *, seconds: int) -> ReserveProductUseCase:
  return ReserveProductUseCase(
    uow=store,
    products=ProductService(Products(store)),
    reservations=ReservationService(Reservations(store)),
    time_policy=ReservationTimePolicy(lifetime=timedelta(seconds=seconds)),
  )


async def test_request_uses_configured_lifetime_and_one_authoritative_creation_instant() -> None:
  class AdvancingClock(Reservations):
    async def current_time(self) -> datetime:
      now = await super().current_time()
      self.store.now += timedelta(seconds=1)
      return now

  store = Store(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
  product = await seed(store)
  usecase = flow(store, seconds=90)
  usecase.reservations = ReservationService(AdvancingClock(store))
  item = await usecase.execute(command(product.id))
  assert item.created_at == datetime(2026, 1, 1, tzinfo=timezone.utc)
  assert item.expires_at == datetime(2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc)
  assert store.products[product.id].stock_quantity == 3


async def test_lifetime_begins_after_product_lock_wait() -> None:
  store = Store(now=datetime(2026, 1, 1, tzinfo=timezone.utc))

  class DelayedProductService(ProductService):
    async def require(self, product_id: UUID, *, for_update: bool = False) -> Product:
      product = await super().require(product_id, for_update=for_update)
      if for_update:
        store.now += timedelta(minutes=2)
      return product

  product = await seed(store)
  usecase = flow(store, seconds=90)
  usecase.products = DelayedProductService(Products(store))
  item = await usecase.execute(command(product.id))
  assert item.created_at == datetime(2026, 1, 1, 0, 2, tzinfo=timezone.utc)
  assert item.expires_at == datetime(2026, 1, 1, 0, 3, 30, tzinfo=timezone.utc)


async def test_retry_after_expiration_and_policy_change_preserves_original_hold() -> None:
  store = Store()
  product = await seed(store)
  first = await flow(store, seconds=90).execute(command(product.id))
  store.now = first.expires_at
  retry = await flow(store, seconds=3600).execute(command(product.id))
  assert retry == first
  assert store.products[product.id].stock_quantity == 3
  assert len(store.reservations) == 1


async def test_deadline_overflow_rolls_back_stock_hold() -> None:
  store = Store(now=datetime.max.replace(tzinfo=timezone.utc))
  product = await seed(store)
  with pytest.raises(ValidationException):
    await flow(store, seconds=90).execute(command(product.id))
  assert store.products[product.id].stock_quantity == 5
  assert store.reservations == {}


async def test_container_loads_environment_when_created(monkeypatch: pytest.MonkeyPatch) -> None:
  monkeypatch.setenv("RESERVATION_LIFETIME_SECONDS", "120")
  container = create_persistence_container(async_sessionmaker())
  try:
    async with container.enter_scope() as scope:
      usecase = await scope.get(ReserveProductUseCase)
    assert usecase.time_policy.lifetime == timedelta(minutes=2)
  finally:
    await container.close()


async def test_explicit_settings_are_injected_into_reservation_flow() -> None:
  settings = TimePolicySettings(RESERVATION_LIFETIME_SECONDS=180)
  container = create_persistence_container(async_sessionmaker(), time_settings=settings)
  try:
    async with container.enter_scope() as scope:
      usecase = await scope.get(ReserveProductUseCase)
    assert usecase.time_policy.lifetime == timedelta(minutes=3)
    assert await container.get(TimePolicySettings) is settings
  finally:
    await container.close()


async def test_postgresql_hold_gets_full_lifetime_after_waiting_for_product_lock(database: Database) -> None:
  pid_queue: asyncio.Queue[int] = asyncio.Queue()

  class ObservedProducts(ProductService):
    async def require(self, product_id: UUID, *, for_update: bool = False) -> Product:
      session = database.manager.get_session(raises=True)
      await pid_queue.put(cast(int, await session.scalar(text("SELECT pg_backend_pid()"))))
      return await super().require(product_id, for_update=for_update)

  products = ProductService(ProductRepository(database.manager))
  async with database.uow.begin():
    product = await products.create(name="Widget", sku="W1", stock_quantity=5)

  usecase = ReserveProductUseCase(
    uow=database.uow,
    products=ObservedProducts(ProductRepository(database.manager)),
    reservations=ReservationService(ReservationRepository(database.manager)),
    time_policy=ReservationTimePolicy(lifetime=timedelta(seconds=120)),
  )

  # An independent task owns its own transaction/session, never its parent's context.
  start = asyncio.Event()

  async def reserve_after_start() -> Reservation:
    await start.wait()
    return await usecase.execute(command(product.id))

  task = asyncio.create_task(reserve_after_start())
  try:
    async with database.uow.begin():
      await products.require(product.id, for_update=True)
      start.set()
      pid = await asyncio.wait_for(pid_queue.get(), timeout=3)
      async with asyncio.timeout(3):
        while True:
          async with database.engine.connect() as connection:
            blocked = await connection.scalar(
              text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"),
              {"pid": pid},
            )
          if blocked:
            break
          await asyncio.sleep(0.01)
      released_after = cast(
        datetime,
        await database.manager.get_session(raises=True).scalar(text("SELECT clock_timestamp()")),
      )

    item = await asyncio.wait_for(task, timeout=5)
    assert item.created_at >= released_after
    assert item.expires_at - item.created_at == timedelta(seconds=120)
  finally:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
