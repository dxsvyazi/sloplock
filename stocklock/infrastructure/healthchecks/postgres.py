from dataclasses import dataclass

from sqlalchemy import select

from stocklock.application.ports.healthcheck import IHealthCheck
from stocklock.infrastructure.session_manager import SessionManager


@dataclass(slots=True)
class PostgresHealthCheck(IHealthCheck):
  session_manager: SessionManager

  async def execute(self) -> bool:
    async with self.session_manager.begin() as session:
      row = await session.scalar(select(1))

    return row == 1
