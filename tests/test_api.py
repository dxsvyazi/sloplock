import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from urllib.parse import urlencode
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.application.usecases.confirmations import ConfirmReservationUseCase, GetConfirmationUseCase
from stocklock.application.usecases.product import (
  CorrectProductStockUseCase,
  CreateProductUseCase,
  GetProductUseCase,
  ListProductsUseCase,
  UpdateProductUseCase,
)
from stocklock.application.usecases.reservation import (
  CancelReservationUseCase,
  ExpireReservationUseCase,
  GetReservationUseCase,
  ListProductReservationsUseCase,
  ListReservationsUseCase,
  ReserveProductUseCase,
)
from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.errors import InsufficientStock, ProductNotFound
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.infrastructure.session_manager import SessionManager
from stocklock.shared.enums import ReservationStatus


async def request(app, method, path, body=None, query=None, headers=None):
  messages = []
  sent = False

  async def receive():
    nonlocal sent
    if not sent:
      sent = True
      return {"type": "http.request", "body": json.dumps(body).encode() if body is not None else b""}
    return {"type": "http.disconnect"}

  async def send(message):
    messages.append(message)

  await asyncio.wait_for(
    asyncio.create_task(
      app(
        {
          "type": "http",
          "asgi": {"version": "3.0"},
          "http_version": "1.1",
          "method": method,
          "scheme": "http",
          "path": "/api/v1" + path,
          "raw_path": ("/api/v1" + path).encode(),
          "query_string": urlencode(query or {}).encode(),
          "root_path": "",
          "headers": [
            (b"content-type", b"application/json"),
            *((k.lower().encode(), v.encode()) for k, v in (headers or {}).items()),
          ],
          "client": ("test", 1),
          "server": ("test", 80),
        },
        receive,
        send,
      )
    ),
    timeout=5,
  )
  status = next(m["status"] for m in messages if m["type"] == "http.response.start")
  payload = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
  return status, json.loads(payload) if payload else None


@pytest.fixture
async def api():
  from stocklock.bootstrap import create_app
  from stocklock.project.container import create_container

  container = create_container(session_maker=async_sessionmaker())
  app = create_app(container=container)
  async with app.router.lifespan_context(app):
    yield app, container


PRODUCT = Product.create(name="Widget", sku="W1", stock_quantity=5)
RESERVATION = Reservation(
  product_id=PRODUCT.id,
  quantity=ReservationQuantity(2),
  key=IdempotencyKey("retry"),
  created_at=datetime.now(timezone.utc),
  expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
)
CONFIRMATION = Confirmation(reservation_id=RESERVATION.id)


@pytest.mark.parametrize(
  "method,path,usecase,body,result,status",
  [
    ("POST", "/products", CreateProductUseCase, {"name": "Widget", "sku": "W1", "stock_quantity": 5}, PRODUCT, 201),
    ("GET", "/products", ListProductsUseCase, None, [PRODUCT], 200),
    ("GET", f"/products/{PRODUCT.id}", GetProductUseCase, None, PRODUCT, 200),
    ("PATCH", f"/products/{PRODUCT.id}", UpdateProductUseCase, {"name": "New name"}, PRODUCT, 200),
    ("PATCH", f"/products/{PRODUCT.id}/stock", CorrectProductStockUseCase, {"stock_quantity": 3}, PRODUCT, 200),
    (
      "POST",
      f"/products/{PRODUCT.id}/reservations",
      ReserveProductUseCase,
      {"quantity": 2, "key": "retry"},
      RESERVATION,
      201,
    ),
    ("GET", f"/products/{PRODUCT.id}/reservations", ListProductReservationsUseCase, None, [RESERVATION], 200),
    ("GET", "/reservations", ListReservationsUseCase, None, [RESERVATION], 200),
    ("GET", f"/reservations/{RESERVATION.id}", GetReservationUseCase, None, RESERVATION, 200),
    ("POST", f"/reservations/{RESERVATION.id}/cancel", CancelReservationUseCase, None, RESERVATION, 200),
    ("POST", f"/reservations/{RESERVATION.id}/expire", ExpireReservationUseCase, None, RESERVATION, 200),
    ("POST", f"/reservations/{RESERVATION.id}/confirm", ConfirmReservationUseCase, None, CONFIRMATION, 200),
    ("GET", f"/reservations/{RESERVATION.id}/confirmation", GetConfirmationUseCase, None, CONFIRMATION, 200),
  ],
)
async def test_routes_delegate_and_serialize(api, method, path, usecase, body, result, status):
  app, container = api
  execute = AsyncMock(return_value=result)
  with container.override({usecase: SimpleNamespace(execute=execute)}):
    code, payload = await request(app, method, path, body)
  assert code == status
  execute.assert_awaited_once()
  serialized = payload[0] if isinstance(payload, list) else payload
  assert serialized["id"] == str((result[0] if isinstance(result, list) else result).id)
  command = execute.call_args.args[0]
  if "product_id" in path or path.startswith(f"/products/{PRODUCT.id}"):
    assert command.product_id == PRODUCT.id
  if "/reservations/" in path:
    assert command.reservation_id == RESERVATION.id


@pytest.mark.parametrize(
  "body",
  [
    {"name": "Widget", "sku": "W", "stock_quantity": -1},
    {"name": "Widget", "sku": "W", "stock_quantity": True},
  ],
)
async def test_invalid_body_rejected_before_usecase(api, body):
  app, container = api
  execute = AsyncMock()
  with container.override({CreateProductUseCase: SimpleNamespace(execute=execute)}):
    assert (await request(app, "POST", "/products", body))[0] == 422
  execute.assert_not_awaited()


async def test_filters_and_query_validation(api):
  app, container = api
  execute = AsyncMock(return_value=[])
  cursor = uuid4()
  with container.override({ListReservationsUseCase: SimpleNamespace(execute=execute)}):
    assert (await request(app, "GET", "/reservations", query={"status": "active", "limit": 2, "start_id": cursor}))[
      0
    ] == 200
    command = execute.call_args.args[0]
    assert (command.status, command.limit, command.start_id) == (ReservationStatus.active, 2, cursor)
    for query in ({"status": "bad"}, {"limit": 0}, {"limit": "x"}, {"start_id": "bad"}):
      assert (await request(app, "GET", "/reservations", query=query))[0] == 422
  assert execute.await_count == 1


@pytest.mark.parametrize("error,status", [(ProductNotFound(), 404), (InsufficientStock(), 409)])
async def test_domain_errors(api, error, status):
  app, container = api
  with container.override({GetProductUseCase: SimpleNamespace(execute=AsyncMock(side_effect=error))}):
    code, payload = await request(app, "GET", f"/products/{PRODUCT.id}")
  assert code == status
  assert payload == {"detail": str(error)}


@pytest.mark.parametrize(
  "action,scenario,status,detail",
  [
    ("cancel", "missing", 404, "Reservation not found"),
    ("cancel", "terminal", 409, "Reservation is no longer active"),
    ("expire", "missing", 404, "Reservation not found"),
    ("expire", "terminal", 409, "Reservation is not eligible for expiration"),
    ("expire", "active", 409, "Reservation is not eligible for expiration"),
    ("confirmation", "missing", 404, "Reservation not found"),
    ("confirmation", "active", 404, "Confirmation not found"),
  ],
)
async def test_failed_requests_use_real_workflows_and_central_error_handlers(api, action, scenario, status, detail):
  from stocklock.application.ports.clock import IClock
  from stocklock.application.ports.uow import IUnitOfWork
  from stocklock.domain.ports.repositories.confirmation_repository import IConfirmationRepository
  from stocklock.domain.ports.repositories.product_repository import IProductRepository
  from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository
  from tests.service_doubles import Clock, Confirmations, Products, Reservations, Store

  app, container = api
  store = Store(now=RESERVATION.created_at)
  store.products[PRODUCT.id] = PRODUCT
  if scenario != "missing":
    from copy import deepcopy

    item = deepcopy(RESERVATION)
    if scenario == "terminal":
      item.cancel()
    store.reservations[item.id] = item
  with container.override(
    {
      IUnitOfWork: store,
      IClock: Clock(store),
      IProductRepository: Products(store),
      IReservationRepository: Reservations(store),
      IConfirmationRepository: Confirmations(store),
    }
  ):
    code, payload = await request(
      app, "GET" if action == "confirmation" else "POST", f"/reservations/{RESERVATION.id}/{action}"
    )
  assert code == status
  assert payload == {"detail": detail}
  assert store.products[PRODUCT.id].stock_quantity.value == 5
  assert not store.active


async def test_container_scopes_share_graph_and_isolate_managers():
  from stocklock.project.container import create_container

  container = create_container(session_maker=async_sessionmaker())
  try:
    async with container.enter_scope() as first, container.enter_scope() as second:
      manager = await first.get(SessionManager)
      flow = await first.get(ReserveProductUseCase)
      assert flow is await first.get(ReserveProductUseCase)
      assert flow.uow.session_manager is manager
      assert flow.products.products.session_manager is manager
      assert flow.reservations.reservations.session_manager is manager
      assert await second.get(SessionManager) is not manager
  finally:
    await container.close()


async def test_owned_engine_is_disposed_when_app_shuts_down(monkeypatch):
  from stocklock.bootstrap import create_app
  from stocklock.project import container as composition
  from stocklock.project.configs.database import DatabaseSettings
  from stocklock.project.configs.time_policy import TimePolicySettings

  engine = SimpleNamespace(dispose=AsyncMock())
  make_engine = Mock(return_value=engine)
  monkeypatch.setattr(composition, "create_async_engine", make_engine)
  settings = DatabaseSettings(STOCKLOCK_DATABASE_URL="postgresql+asyncpg://localhost/stocklock", _env_file=None)
  container = composition.create_container(database_settings=settings)
  app = create_app(container=container)
  async with app.router.lifespan_context(app):
    from sqlalchemy.ext.asyncio import AsyncEngine

    assert await container.get(AsyncEngine) is engine
    assert await container.get(AsyncEngine) is engine
    assert await container.get(TimePolicySettings) is await container.get(TimePolicySettings)
    engine.dispose.assert_not_awaited()
  make_engine.assert_called_once_with(settings.STOCKLOCK_DATABASE_URL.get_secret_value(), pool_pre_ping=True)
  engine.dispose.assert_awaited_once()


async def test_openapi_includes_every_route_and_hides_injected_usecases(api):
  app, _ = api
  schema = app.openapi()
  assert len(schema["paths"]) == 10
  for path in schema["paths"].values():
    for operation in path.values():
      assert all(parameter["name"] != "usecase" for parameter in operation.get("parameters", []))


async def test_http_uses_real_scoped_workflow_and_closes_transaction(api):
  from stocklock.domain.ports.repositories.product_repository import IProductRepository

  app, container = api
  repository = SimpleNamespace(find_by_id=AsyncMock(return_value=PRODUCT))
  # An unbound session maker can open a transaction; the fake repository performs no SQL.
  # This runs the real use case, service and UOW through Wireup's request scope.
  with container.override({IProductRepository: repository}):
    for _ in range(2):
      status, payload = await request(app, "GET", f"/products/{PRODUCT.id}")
      assert status == 200
      assert payload["id"] == str(PRODUCT.id)
  assert repository.find_by_id.await_count == 2


@pytest.mark.parametrize(
  "method,path,body",
  [
    ("GET", "/products/not-a-uuid", None),
    ("PATCH", f"/products/{PRODUCT.id}", {}),
    ("PATCH", f"/products/{PRODUCT.id}", {"name": None}),
    ("PATCH", f"/products/{PRODUCT.id}/stock", {"stock_quantity": -1}),
    ("POST", f"/products/{PRODUCT.id}/reservations", {"quantity": 0, "key": "retry"}),
    ("POST", f"/products/{PRODUCT.id}/reservations", {"quantity": 1, "key": " "}),
    ("POST", f"/products/{PRODUCT.id}/reservations", {"quantity": 1, "key": "retry", "expires_at": "tomorrow"}),
  ],
)
async def test_boundary_validation(api, method, path, body):
  app, _ = api
  assert (await request(app, method, path, body))[0] == 422
