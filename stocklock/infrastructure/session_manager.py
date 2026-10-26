from asyncio import Task, current_task
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal, overload

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from stocklock.infrastructure.exceptions import (
  NoActiveSession,
  SessionTaskMismatch,
  TransactionAlreadyActive,
  TransactionTaskRequired,
)


@dataclass(slots=True, frozen=True)
class _SessionScope:
  session: AsyncSession
  owner: Task


@dataclass(slots=True, frozen=True)
class SessionManager:
  """Provide a session only inside an explicit, task-owned transaction scope."""

  session_maker: async_sessionmaker[AsyncSession]
  _context: ContextVar[_SessionScope | None] = field(
    default_factory=lambda: ContextVar("_session_context", default=None),
    init=False,
    repr=False,
  )

  @overload
  def get_session(self, raises: Literal[False]) -> AsyncSession | None: ...

  @overload
  def get_session(self, raises: Literal[True] = True) -> AsyncSession: ...

  def get_session(self, raises: Literal[True, False] = True) -> AsyncSession | None:
    if (scope := self._context.get()) is None:
      if raises:
        raise NoActiveSession
      return None

    if scope.owner is not current_task():
      raise SessionTaskMismatch

    return scope.session

  @asynccontextmanager
  async def begin(self) -> AsyncGenerator[AsyncSession]:
    """Commit on success; roll back on failure. Nested scopes are rejected."""

    if self.get_session(False) is not None:
      raise TransactionAlreadyActive

    if (owner := current_task()) is None:
      raise TransactionTaskRequired

    async with self.session_maker() as session:
      async with session.begin():
        token = self._context.set(_SessionScope(session=session, owner=owner))

        try:
          yield session
        finally:
          self._context.reset(token)
