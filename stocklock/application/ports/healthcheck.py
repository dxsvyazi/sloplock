from abc import ABC, abstractmethod


class IHealthCheck(ABC):
  @abstractmethod
  async def execute(self) -> bool: ...
