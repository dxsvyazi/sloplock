from abc import ABC, abstractmethod
from datetime import datetime


class IClock(ABC):
  @abstractmethod
  async def now(self) -> datetime:
    """Return authoritative, aware UTC wall time, including elapsed lock waits."""
    ...
