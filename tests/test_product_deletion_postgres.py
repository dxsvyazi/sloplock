import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.application.commands.product import DeleteProductCommand, GetProductCommand, ListProductsCommand
from stocklock.application.commands.reservation import CreateReservationCommand
from stocklock.application.commands.confirmation import ConfirmReservationCommand, GetConfirmationCommand
from stocklock.application.usecases.product import DeleteProductUseCase, GetProductUseCase, ListProductsUseCase
from stocklock.application.usecases.reservation import ReserveProductUseCase
from stocklock.application.usecases.confirmations import ConfirmReservationUseCase, GetConfirmationUseCase
from stocklock.domain.errors import ProductHasActiveReservations, ProductNotFound, ReservationNotFound
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.project.container import create_container
from stocklock.project.configs.admin import AdminSettings
from stocklock.shared.enums import DeletionMode, ProductVisibility, ReservationStatus
from tests.test_retention import seed, remaining
from tests.test_api import request


def container_for(database):
  return create_container(
    session_maker=async_sessionmaker(database.engine, expire_on_commit=False),
    admin_settings=AdminSettings(ADMIN_API_TOKEN="test-secret", _env_file=None),
  )


async def execute(container, usecase, command):
  async with container.enter_scope() as scope:
    return await (await scope.get(usecase)).execute(command)


async def test_soft_preserves_confirmation_retries_and_hard_erases_them(database):
  product, [reservation] = await seed(database, (ReservationStatus.confirmed,))
  container = container_for(database)
  try:
    confirmation = await execute(
      container, GetConfirmationUseCase, GetConfirmationCommand(reservation_id=reservation.id)
    )
    await execute(container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id))
    retried = await execute(
      container, ConfirmReservationUseCase, ConfirmReservationCommand(reservation_id=reservation.id)
    )
    assert retried == confirmation
    assert await remaining(database) == ({reservation.id}, {reservation.id})
    assert await execute(container, ListProductsUseCase, ListProductsCommand()) == []
    assert (
      len(await execute(container, ListProductsUseCase, ListProductsCommand(visibility=ProductVisibility.all))) == 1
    )
    with pytest.raises(ProductNotFound):
      await execute(
        container, ReserveProductUseCase, CreateReservationCommand(product_id=product.id, quantity=1, key="new")
      )
    await execute(container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id, mode=DeletionMode.hard))
    assert await remaining(database) == (set(), set())
    with pytest.raises(ReservationNotFound):
      await execute(container, ConfirmReservationUseCase, ConfirmReservationCommand(reservation_id=reservation.id))
    with pytest.raises(ReservationNotFound):
      await execute(container, GetConfirmationUseCase, GetConfirmationCommand(reservation_id=reservation.id))
  finally:
    await container.close()


@pytest.mark.parametrize("mode", list(DeletionMode))
@pytest.mark.parametrize("first", ["reserve", "delete"])
async def test_product_lock_serializes_deletion_with_new_reservation(database, monkeypatch, mode, first):
  product, _ = await seed(database, ())
  container = container_for(database)
  locked, attempted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
  original = ProductRepository.find_by_id
  calls = 0

  async def controlled(self, id, *, for_update=False):
    nonlocal calls
    if not for_update or id != product.id:
      return await original(self, id, for_update=for_update)
    calls += 1
    call = calls
    if call == 2:
      attempted.set()
    result = await original(self, id, for_update=for_update)
    if call == 1:
      locked.set()
      await release.wait()
    return result

  monkeypatch.setattr(ProductRepository, "find_by_id", controlled)
  operations = {
    "delete": (DeleteProductUseCase, DeleteProductCommand(product_id=product.id, mode=mode)),
    "reserve": (ReserveProductUseCase, CreateReservationCommand(product_id=product.id, quantity=2, key="race")),
  }
  tasks = []
  try:
    tasks.append(asyncio.create_task(execute(container, *operations[first])))
    await asyncio.wait_for(locked.wait(), 2)
    other = "reserve" if first == "delete" else "delete"
    tasks.append(asyncio.create_task(execute(container, *operations[other])))
    await asyncio.wait_for(attempted.wait(), 2)
    release.set()
    winner, loser = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
    assert not isinstance(winner, Exception)
    if first == "reserve" and mode is DeletionMode.soft:
      assert loser is None
    else:
      assert isinstance(loser, ProductNotFound if first == "delete" else ProductHasActiveReservations)
    async with database.uow.begin():
      row = await ProductRepository(database.manager).find_by_id(product.id)
      if first == "reserve":
        assert (row.deleted_at is not None) == (mode is DeletionMode.soft)
        assert row.stock_quantity.value == 5
      elif mode is DeletionMode.soft:
        assert row.deleted_at is not None and row.stock_quantity.value == 7
      else:
        assert row is None
    holds, _ = await remaining(database)
    assert len(holds) == int(first == "reserve")
  finally:
    release.set()
    for task in tasks:
      if not task.done():
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await container.close()


async def test_hard_rejects_active_without_stock_side_effects(database):
  product, [reservation] = await seed(database, (ReservationStatus.active,))
  container = container_for(database)
  try:
    with pytest.raises(ProductHasActiveReservations):
      await execute(
        container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id, mode=DeletionMode.hard)
      )
    current = await execute(container, GetProductUseCase, GetProductCommand(product_id=product.id))
    assert current.stock_quantity == product.stock_quantity and current.deleted_at is None
    assert await remaining(database) == ({reservation.id}, set())
  finally:
    await container.close()


async def test_hard_cascade_rolls_back_if_transaction_fails(database, monkeypatch):
  product, [reservation] = await seed(database, (ReservationStatus.confirmed,))
  container = container_for(database)
  original = ProductRepository.hard_delete

  async def fail_after_delete(self, id):
    await original(self, id)
    raise RuntimeError("injected failure after cascade")

  monkeypatch.setattr(ProductRepository, "hard_delete", fail_after_delete)
  try:
    with pytest.raises(RuntimeError, match="injected"):
      await execute(
        container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id, mode=DeletionMode.hard)
      )
    assert await remaining(database) == ({reservation.id}, {reservation.id})
    assert await execute(container, GetProductUseCase, GetProductCommand(product_id=product.id)) == product
  finally:
    await container.close()


async def test_real_http_deletion_lifecycle(database):
  from stocklock.bootstrap import create_app

  product, [reservation] = await seed(database, (ReservationStatus.confirmed,))
  app = create_app(container=container_for(database))
  headers = {"Authorization": "Bearer test-secret"}
  async with app.router.lifespan_context(app):
    path = f"/products/{product.id}"
    assert (await request(app, "DELETE", path))[0] == 401
    assert await request(app, "DELETE", path, headers=headers) == (204, None)
    assert (await request(app, "GET", path))[0] == 404
    status, payload = await request(app, "GET", path, query={"include_deleted": "true"}, headers=headers)
    assert status == 200 and payload["deleted_at"] is not None
    assert (await request(app, "GET", "/products")) == (200, [])
    assert len((await request(app, "GET", "/products", query={"visibility": "deleted"}, headers=headers))[1]) == 1
    assert len((await request(app, "GET", "/reservations"))[1]) == 1
    assert (await request(app, "GET", "/reservations", query={"product_visibility": "visible"})) == (200, [])
    assert len((await request(app, "GET", path + "/reservations"))[1]) == 1
    assert (await request(app, "POST", f"/reservations/{reservation.id}/confirm"))[0] == 200
    assert (await request(app, "PATCH", path, body={"name": "New name"}))[0] == 404
    assert (await request(app, "PATCH", path + "/stock", body={"stock_quantity": 5}))[0] == 404
    assert (await request(app, "DELETE", path, query={"mode": "hard"}, headers=headers))[0] == 204
    assert (await request(app, "POST", f"/reservations/{reservation.id}/confirm"))[0] == 404
    assert (await request(app, "GET", f"/reservations/{reservation.id}/confirmation"))[0] == 404


@pytest.mark.parametrize("mode", list(DeletionMode))
@pytest.mark.parametrize("transition", ["confirm", "cancel", "expire"])
async def test_deletion_coordinates_with_uncommitted_terminal_transition_without_deadlock(
  database, monkeypatch, mode, transition
):
  from stocklock.application.commands.reservation import CancelReservationCommand, ExpireReservationCommand
  from stocklock.application.usecases.reservation import CancelReservationUseCase, ExpireReservationUseCase
  from stocklock.infrastructure.models.reservation import ReservationORM
  from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
  from sqlalchemy import update, func
  from datetime import timedelta

  product, [reservation] = await seed(database, (ReservationStatus.active,))
  if transition == "expire":
    async with database.uow.begin():
      await database.manager.get_session().execute(
        update(ReservationORM)
        .where(ReservationORM.id == reservation.id)
        .values(expires_at=func.clock_timestamp() - timedelta(days=1))
      )
  container = container_for(database)
  product_locked, transitioned, checked = asyncio.Event(), asyncio.Event(), asyncio.Event()
  original_read = ProductRepository.active_held_quantity
  original_find = ProductRepository.find_by_id
  original_transition = ReservationRepository.save_transition

  async def wait_for_transition(self, id):
    product_locked.set()
    await transitioned.wait()
    try:
      return await original_read(self, id)
    finally:
      checked.set()

  async def pause_transition(self, entity, *, previous_status):
    result = await original_transition(self, entity, previous_status=previous_status)
    transitioned.set()
    await checked.wait()
    return result

  async def wait_after_product_lock(self, id, *, for_update=False):
    result = await original_find(self, id, for_update=for_update)
    if id == product.id and for_update:
      product_locked.set()
      await transitioned.wait()
      checked.set()
    return result

  if mode is DeletionMode.hard:
    monkeypatch.setattr(ProductRepository, "active_held_quantity", wait_for_transition)
  else:
    monkeypatch.setattr(ProductRepository, "find_by_id", wait_after_product_lock)
  monkeypatch.setattr(ReservationRepository, "save_transition", pause_transition)
  terminal_usecase, command = {
    "confirm": (ConfirmReservationUseCase, ConfirmReservationCommand(reservation_id=reservation.id)),
    "cancel": (CancelReservationUseCase, CancelReservationCommand(reservation_id=reservation.id)),
    "expire": (ExpireReservationUseCase, ExpireReservationCommand(reservation_id=reservation.id)),
  }[transition]
  tasks = []
  try:
    tasks.append(
      asyncio.create_task(
        execute(container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id, mode=mode))
      )
    )
    await asyncio.wait_for(product_locked.wait(), 1)
    tasks.append(asyncio.create_task(execute(container, terminal_usecase, command)))
    deletion, terminal = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
    if mode is DeletionMode.hard:
      assert isinstance(deletion, ProductHasActiveReservations)
    else:
      assert deletion is None
    assert not isinstance(terminal, Exception)
    current = await execute(
      container, GetProductUseCase, GetProductCommand(product_id=product.id, include_deleted=True)
    )
    assert (current.deleted_at is not None) == (mode is DeletionMode.soft)
    assert current.stock_quantity.value == (7 if transition == "confirm" else 8)
    await execute(container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id, mode=mode))
  finally:
    checked.set()
    transitioned.set()
    for task in tasks:
      if not task.done():
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await container.close()


async def test_visibility_filters_apply_before_cursor_pagination(database):
  from stocklock.application.commands.reservation import ListReservationsCommand
  from stocklock.application.usecases.reservation import ListReservationsUseCase

  container = container_for(database)
  ids = []
  try:
    for i in range(4):
      product, _ = await seed(database, (ReservationStatus.cancelled,))
      ids.append(product.id)
      if i % 2 == 0:
        await execute(container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id))
    visible = await execute(container, ListProductsUseCase, ListProductsCommand(limit=1))
    assert [p.id for p in visible] == [ids[1]]
    visible = await execute(container, ListProductsUseCase, ListProductsCommand(limit=1, start_id=ids[1]))
    assert [p.id for p in visible] == [ids[3]]
    reservations = await execute(
      container,
      ListReservationsUseCase,
      ListReservationsCommand(
        limit=1, status=ReservationStatus.cancelled, product_visibility=ProductVisibility.deleted
      ),
    )
    assert len(reservations) == 1 and reservations[0].product_id == ids[0]
    reservations = await execute(
      container,
      ListReservationsUseCase,
      ListReservationsCommand(
        limit=1,
        status=ReservationStatus.cancelled,
        start_id=reservations[0].id,
        product_visibility=ProductVisibility.deleted,
      ),
    )
    assert len(reservations) == 1 and reservations[0].product_id == ids[2]
  finally:
    await container.close()


@pytest.mark.parametrize("mode", list(DeletionMode))
@pytest.mark.parametrize("operation", ["details", "stock"])
async def test_edits_racing_deletion_never_modify_deleted_product(database, mode, operation):
  from stocklock.application.commands.product import UpdateProductCommand, CorrectProductStockCommand
  from stocklock.application.usecases.product import UpdateProductUseCase, CorrectProductStockUseCase

  product, _ = await seed(database, ())
  container = container_for(database)
  edit = (
    (UpdateProductUseCase, UpdateProductCommand(product_id=product.id, name="Updated name"))
    if operation == "details"
    else (CorrectProductStockUseCase, CorrectProductStockCommand(product_id=product.id, stock_quantity=4))
  )
  try:
    deleted, edited = await asyncio.wait_for(
      asyncio.gather(
        execute(container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id, mode=mode)),
        execute(container, *edit),
        return_exceptions=True,
      ),
      5,
    )
    assert deleted is None
    assert not isinstance(edited, Exception) or isinstance(edited, ProductNotFound)
    if mode is DeletionMode.soft:
      current = await execute(
        container, GetProductUseCase, GetProductCommand(product_id=product.id, include_deleted=True)
      )
      assert current.deleted_at is not None
      assert current.name.value == (
        "Updated name" if operation == "details" and not isinstance(edited, Exception) else "Widget"
      )
      assert current.stock_quantity.value == (4 if operation == "stock" and not isinstance(edited, Exception) else 7)
    else:
      with pytest.raises(ProductNotFound):
        await execute(container, GetProductUseCase, GetProductCommand(product_id=product.id, include_deleted=True))
  finally:
    await container.close()


async def test_hard_deletion_racing_product_cleanup_is_safe(database):
  from datetime import timedelta
  from sqlalchemy import update, func
  from stocklock.infrastructure.models.product import ProductORM
  from stocklock.infrastructure.workers.product_cleanup import ProductCleanupWorker

  product, _ = await seed(database, ())
  async with database.uow.begin():
    await database.manager.get_session().execute(
      update(ProductORM)
      .where(ProductORM.id == product.id)
      .values(deleted_at=func.clock_timestamp() - timedelta(days=31))
    )
  container = container_for(database)
  try:
    cleanup, erased = await asyncio.wait_for(
      asyncio.gather(
        ProductCleanupWorker(container, timedelta(days=1)).run_once(),
        execute(container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id, mode=DeletionMode.hard)),
        return_exceptions=True,
      ),
      5,
    )
    assert cleanup is None
    assert erased is None or isinstance(erased, ProductNotFound)
    with pytest.raises(ProductNotFound):
      await execute(container, GetProductUseCase, GetProductCommand(product_id=product.id, include_deleted=True))
  finally:
    await container.close()


@pytest.mark.parametrize("transition", ["confirm", "cancel", "expire", "bulk_expire", "worker_expire"])
async def test_active_reservations_finish_after_soft_deletion(database, transition):
  from datetime import timedelta
  from sqlalchemy import update, func
  from stocklock.application.commands.reservation import (
    CancelReservationCommand,
    ExpireReservationCommand,
    ExpireReservationsCommand,
  )
  from stocklock.application.usecases.reservation import CancelReservationUseCase, ExpireReservationUseCase
  from stocklock.application.usecases.expiration import ExpireReservationsUseCase
  from stocklock.infrastructure.models.reservation import ReservationORM
  from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
  from stocklock.domain.errors import ReservationUnavailable
  from stocklock.domain.value_objects.product import StockDelta

  product, [reservation] = await seed(database, (ReservationStatus.active,))
  if transition in ("expire", "bulk_expire", "worker_expire"):
    async with database.uow.begin():
      await database.manager.get_session().execute(
        update(ReservationORM)
        .where(ReservationORM.id == reservation.id)
        .values(expires_at=func.clock_timestamp() - timedelta(days=1))
      )
  container = container_for(database)
  try:
    await execute(container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id))
    with pytest.raises(ProductHasActiveReservations):
      await execute(
        container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id, mode=DeletionMode.hard)
      )
    with pytest.raises(ProductNotFound):
      await execute(
        container, ReserveProductUseCase, CreateReservationCommand(product_id=product.id, quantity=1, key="new")
      )
    operation = {
      "confirm": (ConfirmReservationUseCase, ConfirmReservationCommand(reservation_id=reservation.id)),
      "cancel": (CancelReservationUseCase, CancelReservationCommand(reservation_id=reservation.id)),
      "expire": (ExpireReservationUseCase, ExpireReservationCommand(reservation_id=reservation.id)),
      "bulk_expire": (ExpireReservationsUseCase, ExpireReservationsCommand(reservation_ids=(reservation.id,))),
      "worker_expire": (ExpireReservationsUseCase, ExpireReservationsCommand(reservation_ids=(reservation.id,))),
    }[transition]
    if transition == "worker_expire":
      from stocklock.infrastructure.workers.expiration import ExpirationWorker

      await ExpirationWorker(container, timedelta(seconds=1)).run_once()
    else:
      result = await execute(container, *operation)
    if transition == "confirm":
      assert await execute(container, *operation) == result
    elif transition == "bulk_expire":
      assert result == [reservation.id]
      assert await execute(container, *operation) == []
    elif transition != "worker_expire":
      with pytest.raises(ReservationUnavailable):
        await execute(container, *operation)
    current = await execute(
      container, GetProductUseCase, GetProductCommand(product_id=product.id, include_deleted=True)
    )
    assert current.deleted_at is not None
    assert current.stock_quantity.value == (7 if transition == "confirm" else 8)
    async with database.uow.begin():
      saved = await ReservationRepository(database.manager).find_by_id(reservation.id)
      assert (
        saved.status
        is {
          "confirm": ReservationStatus.confirmed,
          "cancel": ReservationStatus.cancelled,
          "expire": ReservationStatus.expired,
          "bulk_expire": ReservationStatus.expired,
          "worker_expire": ReservationStatus.expired,
        }[transition]
      )
      assert (await database.manager.get_session().get(ReservationORM, reservation.id)).finalized_at is not None
      assert await ProductRepository(database.manager).adjust_stock(product.id, StockDelta(-1)) is None
    await execute(container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id, mode=DeletionMode.hard))
    assert await remaining(database) == (set(), set())
  finally:
    await container.close()


async def test_real_http_soft_deletion_with_active_hold(database):
  from stocklock.bootstrap import create_app

  product, [reservation] = await seed(database, (ReservationStatus.active,))
  app = create_app(container=container_for(database))
  headers = {"Authorization": "Bearer test-secret"}
  async with app.router.lifespan_context(app):
    path = f"/products/{product.id}"
    assert await request(app, "DELETE", path, headers=headers) == (204, None)
    assert (await request(app, "DELETE", path, query={"mode": "hard"}, headers=headers))[0] == 409
    assert (await request(app, "POST", path + "/reservations", body={"quantity": 1, "key": "new"}))[0] == 404
    assert (await request(app, "GET", f"/reservations/{reservation.id}"))[1]["status"] == "active"
    assert (await request(app, "POST", f"/reservations/{reservation.id}/cancel"))[0] == 200
    assert await request(app, "DELETE", path, query={"mode": "hard"}, headers=headers) == (204, None)


@pytest.mark.parametrize("bulk", [False, True])
async def test_failed_stock_return_after_soft_deletion_rolls_back(database, monkeypatch, bulk):
  from datetime import timedelta
  from sqlalchemy import update, func
  from stocklock.application.commands.reservation import CancelReservationCommand, ExpireReservationsCommand
  from stocklock.application.usecases.reservation import CancelReservationUseCase
  from stocklock.application.usecases.expiration import ExpireReservationsUseCase
  from stocklock.infrastructure.models.reservation import ReservationORM
  from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository

  product, [reservation] = await seed(database, (ReservationStatus.active,))
  if bulk:
    async with database.uow.begin():
      await database.manager.get_session().execute(
        update(ReservationORM)
        .where(ReservationORM.id == reservation.id)
        .values(expires_at=func.clock_timestamp() - timedelta(days=1))
      )
  container = container_for(database)
  original = ProductRepository.adjust_stock

  async def fail_after_return(self, id, delta):
    result = await original(self, id, delta)
    assert result is not None
    raise RuntimeError("injected failure after stock return")

  try:
    await execute(container, DeleteProductUseCase, DeleteProductCommand(product_id=product.id))
    monkeypatch.setattr(ProductRepository, "adjust_stock", fail_after_return)
    operation = (
      (ExpireReservationsUseCase, ExpireReservationsCommand(reservation_ids=(reservation.id,)))
      if bulk
      else (CancelReservationUseCase, CancelReservationCommand(reservation_id=reservation.id))
    )
    with pytest.raises(RuntimeError, match="injected failure"):
      await execute(container, *operation)
    async with database.uow.begin():
      saved = await ReservationRepository(database.manager).find_by_id(reservation.id)
      assert saved.status is ReservationStatus.active
      assert (await database.manager.get_session().get(ReservationORM, reservation.id)).finalized_at is None
      current = await ProductRepository(database.manager).find_by_id(product.id)
      assert current.deleted_at is not None and current.stock_quantity.value == 7
  finally:
    await container.close()
