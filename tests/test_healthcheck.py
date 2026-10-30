import asyncio
from dataclasses import dataclass

import pytest

from stocklock.application.ports.healthcheck import IHealthCheck
from stocklock.application.usecases.healthcheck import HealthCheck


@dataclass
class HealthCheckStub(IHealthCheck):
  healthy: bool

  async def execute(self) -> bool:
    return self.healthy


@pytest.mark.parametrize(
  "results,expected",
  [
    ([], True),
    ([True], True),
    ([True, True], True),
    ([False], False),
    ([True, False], False),
    ([False, True], False),
    ([False, False], False),
  ],
)
async def test_healthcheck_requires_every_dependency_to_be_healthy(results, expected):
  usecase = HealthCheck([HealthCheckStub(result) for result in results])

  assert await usecase.execute() is expected


async def test_healthcheck_runs_dependencies_concurrently():
  first_started = asyncio.Event()
  second_started = asyncio.Event()

  class FirstCheck(IHealthCheck):
    async def execute(self) -> bool:
      first_started.set()
      await second_started.wait()
      return True

  class SecondCheck(IHealthCheck):
    async def execute(self) -> bool:
      second_started.set()
      await first_started.wait()
      return True

  assert await asyncio.wait_for(HealthCheck([FirstCheck(), SecondCheck()]).execute(), timeout=1) is True


async def test_healthcheck_propagates_dependency_errors():
  class FailingCheck(IHealthCheck):
    async def execute(self) -> bool:
      raise ConnectionError("Database unavailable")

  with pytest.raises(ConnectionError, match="Database unavailable"):
    await HealthCheck([FailingCheck()]).execute()
