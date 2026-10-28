from dataclasses import dataclass
from datetime import datetime
from typing import cast

from sqlalchemy import func, select

from stocklock.application.ports.clock import IClock
from stocklock.infrastructure.exceptions import ServerTimeUnavailable
from stocklock.infrastructure.session_manager import SessionManager
from stocklock.shared.utils.timestamps import as_utc


@dataclass(slots=True)
class PostgresClock(IClock):
  session_manager: SessionManager

  async def now(self) -> datetime:
    """Read wall time through the caller's active transaction session."""
    session = self.session_manager.get_session()

    if (time := cast(datetime | None, await session.scalar(select(func.clock_timestamp())))) is None:
      raise ServerTimeUnavailable

    return as_utc(time)
