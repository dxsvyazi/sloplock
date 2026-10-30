from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from stocklock.application.usecases.healthcheck import HealthCheck
from stocklock.infrastructure.healthchecks.postgres import PostgresHealthCheck
from stocklock.infrastructure.session_manager import SessionManager
from stocklock.project.container import create_container


@pytest.mark.parametrize("result,expected", [(1, True), (0, False), (None, False)])
async def test_postgres_healthcheck_validates_query_result(result, expected):
  class Manager:
    @asynccontextmanager
    async def begin(self):
      yield AsyncMock(scalar=AsyncMock(return_value=result))

  assert await PostgresHealthCheck(Manager()).execute() is expected


async def test_postgres_healthcheck_propagates_database_errors():
  class Manager:
    @asynccontextmanager
    async def begin(self):
      raise OperationalError("SELECT 1", {}, ConnectionError("Database unavailable"))
      yield  # pragma: no cover

  with pytest.raises(OperationalError):
    await PostgresHealthCheck(Manager()).execute()


async def test_postgres_healthcheck_opens_and_closes_its_own_transaction(database):
  check = PostgresHealthCheck(database.manager)

  for _ in range(2):
    assert await check.execute() is True
    assert database.manager.get_session(raises=False) is None


async def test_container_resolves_healthcheck_with_working_postgres_dependency(database):
  container = create_container(session_maker=database.manager.session_maker)
  try:
    async with container.enter_scope() as scope:
      usecase = await scope.get(HealthCheck)
      assert await usecase.execute() is True
      manager = await scope.get(SessionManager)
      assert manager.get_session(raises=False) is None
  finally:
    await container.close()
