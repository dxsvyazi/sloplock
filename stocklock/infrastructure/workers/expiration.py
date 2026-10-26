"""Run with python -m stocklock.infrastructure.workers.expiration."""

import asyncio
import logging
import signal
from dataclasses import dataclass, field
from datetime import timedelta
from uuid import UUID

from wireup import AsyncContainer

from stocklock.application.commands.common import PageCommand
from stocklock.application.commands.reservation import ExpireReservationCommand
from stocklock.application.usecases.expiration import ListDueReservationsUseCase
from stocklock.application.usecases.reservations import ExpireReservationUseCase
from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.project.container import create_container

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExpirationWorker:
  container: AsyncContainer
  interval: timedelta
  batch_size: int = 100
  max_batches: int = 100
  operation_timeout: timedelta = timedelta(seconds=30)
  _cursor: UUID | None = field(default=None, init=False)

  def __post_init__(self) -> None:
    if self.interval <= timedelta(0) or self.max_batches < 1 or self.operation_timeout <= timedelta(0):
      raise ValueError("Worker interval, batch count, and operation timeout must be positive")

  async def run_once(self, *, stop: asyncio.Event | None = None) -> None:
    for _ in range(self.max_batches):
      if stop is not None and stop.is_set():
        return

      async with asyncio.timeout(self.operation_timeout.total_seconds()):
        async with self.container.enter_scope() as scope:
          candidates = await scope.get(ListDueReservationsUseCase)
          ids = await candidates.execute(PageCommand(start_id=self._cursor, limit=self.batch_size))

      if not ids:
        self._cursor = None
        return

      for reservation_id in ids:
        if stop is not None and stop.is_set():
          return

        try:
          async with asyncio.timeout(self.operation_timeout.total_seconds()):
            async with self.container.enter_scope() as scope:
              expire = await scope.get(ExpireReservationUseCase)

              await expire.execute(ExpireReservationCommand(reservation_id=reservation_id))
        except Exception:
          logger.exception("Failed to expire reservation %s", reservation_id)
      # Advance even past failed holds; revisit failures on the next sweep.
      self._cursor = ids[-1]

      if len(ids) < self.batch_size:
        self._cursor = None
        return

  async def run(self, stop: asyncio.Event) -> None:
    while not stop.is_set():
      try:
        await self.run_once(stop=stop)
      except Exception:
        logger.exception("Expiration sweep failed; retrying after the configured interval")

      try:
        await asyncio.wait_for(stop.wait(), timeout=self.interval.total_seconds())
      except TimeoutError:
        pass


async def main() -> None:
  container = create_container()
  stop = asyncio.Event()
  loop = asyncio.get_running_loop()
  signals = (signal.SIGINT, signal.SIGTERM)

  try:
    for signum in signals:
      loop.add_signal_handler(signum, stop.set)

    settings = await container.get(TimePolicySettings)

    await ExpirationWorker(container, settings.expiration_cleanup_interval).run(stop)
  finally:
    for signum in signals:
      loop.remove_signal_handler(signum)

    await container.close()


if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO)
  asyncio.run(main())
