import asyncio
from collections.abc import Sequence
from dataclasses import dataclass

from stocklock.application.ports.healthcheck import IHealthCheck


@dataclass(slots=True)
class HealthCheck(IHealthCheck):
  healthchecks: Sequence[IHealthCheck]

  async def execute(self) -> bool:
    return all(await asyncio.gather(*(check.execute() for check in self.healthchecks)))
