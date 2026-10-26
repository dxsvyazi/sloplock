from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from stocklock.infrastructure.session_manager import SessionManager


@dataclass(slots=True, frozen=True)
class SqlAlchemyUnitOfWork:
  session_manager: SessionManager

  @asynccontextmanager
  async def begin(self) -> AsyncGenerator[None]:
    async with self.session_manager.begin():
      yield
