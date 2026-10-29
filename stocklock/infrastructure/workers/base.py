"""Common limits and stop-aware retry loop for infrastructure workers."""

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from typing import ClassVar

from wireup import AsyncContainer

from stocklock.domain.validation import validate_page, validate_quantity


@dataclass(slots=True)
class BaseWorker(ABC):
  container: AsyncContainer
  interval: timedelta
  batch_size: int = 100
  max_batches: int = 100
  operation_timeout: timedelta = timedelta(seconds=30)
  exception_message: ClassVar[str] = "Worker sweep failed; retrying after the configured interval"

  def __post_init__(self) -> None:
    validate_page(self.batch_size)
    validate_quantity(self.max_batches, minimum=1)

    for duration in (self.interval, self.operation_timeout):
      if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise ValueError("Worker interval and operation timeout must be positive durations")

  @abstractmethod
  async def _run_once(self, *, stop: asyncio.Event | None = None) -> None: ...

  async def run_once(self, *, stop: asyncio.Event | None = None) -> None:
    """Run a single sweep, propagating errors to the caller."""
    await self._run_once(stop=stop)

  async def run(self, stop: asyncio.Event) -> None:
    while not stop.is_set():
      try:
        await self.run_once(stop=stop)
      except Exception:
        logging.getLogger(type(self).__module__).exception(self.exception_message)

      try:
        await asyncio.wait_for(stop.wait(), timeout=self.interval.total_seconds())
      except TimeoutError:
        pass
