from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from stocklock.application.usecases.product import DeleteProductUseCase, ListProductsUseCase, GetProductUseCase
from stocklock.application.usecases.reservation import ListReservationsUseCase
from stocklock.domain.errors import ProductHasActiveReservations, ProductNotFound
from stocklock.project.configs.admin import AdminSettings
from stocklock.shared.enums import DeletionMode, ProductVisibility
from tests.test_api import api as api_fixture, request, PRODUCT

api = api_fixture


@pytest.mark.parametrize("mode", ["soft", "hard"])
async def test_protected_delete_returns_empty_204_and_maps_mode(api, mode):
  app, container = api
  execute = AsyncMock(return_value=None)
  with container.override(
    {
      AdminSettings: AdminSettings(ADMIN_API_TOKEN="test-secret", _env_file=None),
      DeleteProductUseCase: SimpleNamespace(execute=execute),
    }
  ):
    status, payload = await request(
      app, "DELETE", f"/products/{PRODUCT.id}", query={"mode": mode}, headers={"Authorization": "Bearer test-secret"}
    )
  assert status == 204 and payload is None
  assert execute.await_args.args[0].mode is DeletionMode(mode)


@pytest.mark.parametrize("token,status", [(None, 401), ("wrong", 401), ("test-secret", 204)])
async def test_authentication_before_deletion(api, token, status):
  app, container = api
  execute = AsyncMock(return_value=None)
  headers = {"Authorization": f"Bearer {token}"} if token else {}
  with container.override(
    {
      AdminSettings: AdminSettings(ADMIN_API_TOKEN="test-secret", _env_file=None),
      DeleteProductUseCase: SimpleNamespace(execute=execute),
    }
  ):
    assert (await request(app, "DELETE", f"/products/{PRODUCT.id}", headers=headers))[0] == status
  assert execute.await_count == int(status == 204)


async def test_unconfigured_admin_access_is_disabled(api):
  app, container = api
  with container.override({AdminSettings: AdminSettings(ADMIN_API_TOKEN=None, _env_file=None)}):
    assert (await request(app, "DELETE", f"/products/{PRODUCT.id}"))[0] == 503


@pytest.mark.parametrize("error,status", [(ProductNotFound(), 404), (ProductHasActiveReservations(), 409)])
async def test_delete_maps_application_errors(api, error, status):
  app, container = api
  with container.override(
    {
      AdminSettings: AdminSettings(ADMIN_API_TOKEN="test-secret", _env_file=None),
      DeleteProductUseCase: SimpleNamespace(execute=AsyncMock(side_effect=error)),
    }
  ):
    assert (await request(app, "DELETE", f"/products/{PRODUCT.id}", headers={"Authorization": "Bearer test-secret"}))[
      0
    ] == status


@pytest.mark.parametrize(
  "path,query,usecase",
  [
    ("/products", {"visibility": "all"}, ListProductsUseCase),
    ("/products", {"visibility": "deleted"}, ListProductsUseCase),
    (f"/products/{PRODUCT.id}", {"include_deleted": "true"}, GetProductUseCase),
    ("/reservations", {"product_visibility": "deleted"}, ListReservationsUseCase),
  ],
)
async def test_hidden_inspection_requires_auth_and_maps_filter(api, path, query, usecase):
  app, container = api
  execute = AsyncMock(return_value=PRODUCT if usecase is GetProductUseCase else [])
  with container.override(
    {
      AdminSettings: AdminSettings(ADMIN_API_TOKEN="test-secret", _env_file=None),
      usecase: SimpleNamespace(execute=execute),
    }
  ):
    assert (await request(app, "GET", path, query=query))[0] == 401
    assert execute.await_count == 0
    assert (await request(app, "GET", path, query=query, headers={"Authorization": "Bearer test-secret"}))[0] == 200
  command = execute.await_args.args[0]
  if "visibility" in query:
    assert command.visibility is ProductVisibility(query["visibility"])
  elif "product_visibility" in query:
    assert command.product_visibility is ProductVisibility.deleted
  else:
    assert command.include_deleted is True


@pytest.mark.parametrize(
  "path,method,query",
  [
    ("/products", "GET", {"visibility": "invalid"}),
    ("/reservations", "GET", {"product_visibility": "invalid"}),
    (f"/products/{PRODUCT.id}", "DELETE", {"mode": "invalid"}),
  ],
)
async def test_invalid_filters_and_mode_are_rejected(api, path, method, query):
  app, container = api
  with container.override({AdminSettings: AdminSettings(ADMIN_API_TOKEN="test-secret", _env_file=None)}):
    assert (await request(app, method, path, query=query, headers={"Authorization": "Bearer test-secret"}))[0] == 422
