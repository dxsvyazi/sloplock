import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.application.usecases.healthcheck import HealthCheck
from stocklock.bootstrap import create_app
from stocklock.project.container import create_container
from tests.test_api import request
from tests.test_healthcheck import HealthCheckStub


@pytest.mark.parametrize("healthy,expected_status", [(True, 200), (False, 503)])
async def test_healthcheck_http_status_and_cache_policy(healthy, expected_status):
  container = create_container(session_maker=async_sessionmaker())
  app = create_app(container=container)
  response_headers = {}

  async def capture_response(scope, receive, send):
    async def capture_send(message):
      if message["type"] == "http.response.start":
        response_headers.update(dict(message["headers"]))
      await send(message)

    await app(scope, receive, capture_send)

  async with app.router.lifespan_context(app):
    with container.override({HealthCheck: HealthCheck([HealthCheckStub(healthy)])}):
      code, payload = await request(capture_response, "GET", "/healthcheck")

  assert code == expected_status
  assert payload == (True if healthy else {"detail": "Service Unavailable"})
  assert response_headers[b"cache-control"] == b"no-store"


async def test_healthcheck_route_exposes_no_usecase_parameter():
  container = create_container(session_maker=async_sessionmaker())
  try:
    app = create_app(container=container)
    operation = app.openapi()["paths"]["/api/v1/healthcheck"]["get"]
    assert not operation.get("parameters", [])
  finally:
    await container.close()
