import asyncio

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from stocklock.infrastructure.uow import SqlAlchemyUnitOfWork
from stocklock.infrastructure.exceptions import NoActiveSession, SessionTaskMismatch, TransactionAlreadyActive
from stocklock.infrastructure.session_manager import SessionManager
from stocklock.shared.exceptions import DynamicException


class TransactionTestFailure(DynamicException):
  """An intentional failure used to verify transaction cleanup."""


class TrackingSession(AsyncSession):
  async def close(self):
    self.info["closed"] = True
    await super().close()


@pytest.fixture
def manager() -> SessionManager:
  return SessionManager(async_sessionmaker(class_=TrackingSession))


@pytest.fixture
def uow(manager: SessionManager):
  return SqlAlchemyUnitOfWork(manager)


async def test_success_commits_and_removes_session_before_next_scope(
  manager: SessionManager, uow: SqlAlchemyUnitOfWork
):
  commits = []

  async with uow.begin():
    first = manager.get_session(raises=True)

    event.listen(first.sync_session, "after_commit", lambda session: commits.append(True))

  assert commits == [True]
  assert first.info["closed"]
  assert manager.get_session(raises=False) is None

  with pytest.raises(NoActiveSession):
    manager.get_session(raises=True)

  async with uow.begin():
    assert manager.get_session(raises=True) is not first


async def test_body_failure_rolls_back_and_cleans_context(manager: SessionManager, uow: SqlAlchemyUnitOfWork):
  rollbacks = []
  session: AsyncSession | None = None

  with pytest.raises(TransactionTestFailure, match="body failed"):
    async with uow.begin():
      session = manager.get_session(raises=True)

      if not session.in_transaction():
        await session.begin()

      event.listen(session.sync_session, "after_rollback", lambda session: rollbacks.append(True))

      raise TransactionTestFailure("body failed")

  assert session
  assert rollbacks == [True]
  assert session.info["closed"]
  assert manager.get_session(raises=False) is None


async def test_commit_failure_still_closes_and_clears_context(manager: SessionManager, uow: SqlAlchemyUnitOfWork):
  session: AsyncSession | None = None

  def fail_commit(session):
    raise TransactionTestFailure("commit failed")

  with pytest.raises(TransactionTestFailure, match="commit failed"):
    async with uow.begin():
      session = manager.get_session(raises=True)
      event.listen(session.sync_session, "before_commit", fail_commit)

  assert session
  assert session.info.get("closed", False)
  assert manager.get_session(raises=False) is None


async def test_rollback_failure_still_closes_and_clears_context(manager: SessionManager, uow: SqlAlchemyUnitOfWork):
  session: AsyncSession | None = None

  def fail_rollback(session):
    raise TransactionTestFailure("rollback failed")

  with pytest.raises(TransactionTestFailure, match="rollback failed"):
    async with uow.begin():
      session = manager.get_session(raises=True)

      if not session.in_transaction():
        await session.begin()

      event.listen(session.sync_session, "after_rollback", fail_rollback)

      raise TransactionTestFailure("body failed")

  assert session
  assert session.info.get("closed", False)
  assert manager.get_session(raises=False) is None


async def test_nested_scope_rejected_without_finishing_outer_transaction(
  manager: SessionManager, uow: SqlAlchemyUnitOfWork
):
  async with uow.begin():
    session = manager.get_session(raises=True)

    with pytest.raises(TransactionAlreadyActive):
      async with uow.begin():
        pytest.fail("Nested scope was allowed")

    assert manager.get_session(raises=True) is session
    assert session.in_transaction()
    assert not session.info.get("closed", False)


async def test_inherited_session_cannot_be_used_by_child_task(manager: SessionManager, uow: SqlAlchemyUnitOfWork):
  async def child():
    with pytest.raises(SessionTaskMismatch):
      manager.get_session(raises=True)

    with pytest.raises(SessionTaskMismatch):
      async with uow.begin():
        pytest.fail("Child reused the parent transaction")

  async with uow.begin():
    await asyncio.create_task(child())


async def test_concurrent_independent_scopes_have_distinct_sessions(manager: SessionManager, uow: SqlAlchemyUnitOfWork):
  sessions = []
  barrier = asyncio.Barrier(2)

  async def worker():
    async with uow.begin():
      session = manager.get_session(raises=True)

      sessions.append(session)

      await barrier.wait()
      assert manager.get_session(raises=True) is session

    assert manager.get_session(raises=False) is None

  await asyncio.gather(worker(), worker())
  assert sessions[0] is not sessions[1]


async def test_cancellation_rolls_back_and_releases_session(manager: SessionManager, uow: SqlAlchemyUnitOfWork):
  entered = asyncio.Event()
  sessions = []
  rollbacks = []

  async def worker():
    try:
      async with uow.begin():
        session = manager.get_session(raises=True)
        sessions.append(session)

        if not session.in_transaction():
          await session.begin()

        event.listen(session.sync_session, "after_rollback", lambda session: rollbacks.append(True))
        entered.set()

        await asyncio.Event().wait()
    finally:
      assert manager.get_session(raises=False) is None

  task = asyncio.create_task(worker())

  await entered.wait()

  task.cancel()

  with pytest.raises(asyncio.CancelledError):
    await task

  assert rollbacks == [True]
  assert sessions[0].info["closed"]
