"""Compatibility entry point for callers supplying their own session factory."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from wireup import AsyncContainer

from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.project.container import create_container


def create_persistence_container(
  session_maker: async_sessionmaker[AsyncSession],
  *,
  time_settings: TimePolicySettings | None = None,
) -> AsyncContainer:
  return create_container(session_maker=session_maker, time_settings=time_settings)
