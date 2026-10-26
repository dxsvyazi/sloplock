import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from stocklock.infrastructure.uow import SqlAlchemyUnitOfWork
from stocklock.infrastructure.session_manager import SessionManager


@dataclass
class Database:
  manager: SessionManager
  uow: SqlAlchemyUnitOfWork
  engine: AsyncEngine


@pytest.fixture
async def database() -> AsyncIterator[Database]:
  url = os.environ.get("STOCKLOCK_TEST_DATABASE_URL")
  if not url:
    pytest.skip("Set STOCKLOCK_TEST_DATABASE_URL to run PostgreSQL integration tests")
  schema = f"test_{uuid4().hex}"
  admin = create_async_engine(url)
  async with admin.begin() as connection:
    await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
  engine = create_async_engine(
    url,
    pool_size=20,
    max_overflow=0,
    connect_args={"server_settings": {"search_path": schema, "statement_timeout": "5000", "lock_timeout": "4000"}},
  )
  try:
    from stocklock.infrastructure.models import BaseORM
    from stocklock.infrastructure.models.confirmation import ConfirmationORM  # noqa: F401
    from stocklock.infrastructure.models.product import ProductORM  # noqa: F401
    from stocklock.infrastructure.models.reservation import ReservationORM  # noqa: F401

    async with engine.begin() as connection:
      await connection.run_sync(BaseORM.metadata.create_all)
    manager = SessionManager(async_sessionmaker(engine, expire_on_commit=False))
    yield Database(manager=manager, uow=SqlAlchemyUnitOfWork(manager), engine=engine)
  finally:
    await engine.dispose()
    async with admin.begin() as connection:
      await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    await admin.dispose()
