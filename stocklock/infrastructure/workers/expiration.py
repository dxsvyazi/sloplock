"""Run with python -m stocklock.infrastructure.workers.expiration."""

import asyncio
import logging
import signal
from dataclasses import dataclass, field
from uuid import UUID

from stocklock.application.commands.common import PageCommand
from stocklock.application.commands.reservation import ExpireReservationCommand, ExpireReservationsCommand
from stocklock.application.usecases.expiration import ExpireReservationsUseCase, ListDueReservationsUseCase
from stocklock.application.usecases.reservation import TryExpireReservationUseCase
from stocklock.infrastructure.workers.base import BaseWorker
from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.project.container import create_container

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ExpirationWorker(BaseWorker):
  exception_message = "Expiration sweep failed; retrying after the configured interval"
  _cursor: UUID | None = field(default=None, init=False)

  async def _run_once(self, *, stop: asyncio.Event | None = None) -> None:
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

      if stop is not None and stop.is_set():
        return

      try:
        async with asyncio.timeout(self.operation_timeout.total_seconds()):
          async with self.container.enter_scope() as scope:
            expire = await scope.get(ExpireReservationsUseCase)
            await expire.execute(ExpireReservationsCommand(reservation_ids=tuple(ids)))
      except Exception:
        logger.exception("Bulk expiration failed; retrying %s reservations individually", len(ids))
        await self._expire_individually(ids, stop=stop)
      # Advance even past failed holds; revisit failures on the next sweep.
      self._cursor = ids[-1]

      if len(ids) < self.batch_size:
        self._cursor = None
        return

  async def _expire_individually(self, ids: list[UUID], *, stop: asyncio.Event | None) -> None:
    for reservation_id in ids:
      if stop is not None and stop.is_set():
        return

      try:
        async with asyncio.timeout(self.operation_timeout.total_seconds()):
          async with self.container.enter_scope() as scope:
            expire = await scope.get(TryExpireReservationUseCase)
            await expire.execute(ExpireReservationCommand(reservation_id=reservation_id))
      except Exception:
        logger.exception("Failed to expire reservation %s", reservation_id)


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
