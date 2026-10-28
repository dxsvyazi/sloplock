from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.infrastructure.clock import PostgresClock
from stocklock.infrastructure.exceptions import NoActiveSession
from stocklock.infrastructure.session_manager import SessionManager


async def test_clock_requires_an_active_transaction():
  clock = PostgresClock(SessionManager(async_sessionmaker()))

  with pytest.raises(NoActiveSession):
    await clock.now()


async def test_postgres_clock_advances_within_transaction_and_returns_utc(database):
  clock = PostgresClock(database.manager)

  async with database.uow.begin():
    session = database.manager.get_session()
    await session.execute(text("SET LOCAL TIME ZONE 'Asia/Krasnoyarsk'"))
    transaction_start = await session.scalar(text("SELECT transaction_timestamp()"))
    first = await clock.now()
    await session.execute(text("SELECT pg_sleep(0.01)"))
    second = await clock.now()

  assert transaction_start <= first < second
  assert first.utcoffset() == second.utcoffset() == timedelta(0)
