"""Run with python -m stocklock.infrastructure.workers.retention."""

import asyncio
import logging
import signal
from dataclasses import dataclass

from stocklock.application.policies.retention import RetentionPolicy
from stocklock.application.usecases.retention import CleanupRetentionUseCase
from stocklock.infrastructure.workers.base import BaseWorker
from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.project.container import create_container

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RetentionWorker(BaseWorker):
  exception_message = "Retention sweep failed; retrying after the configured interval"

  async def _run_once(self, *, stop: asyncio.Event | None = None) -> None:
    for _ in range(self.max_batches):
      if stop is not None and stop.is_set():
        return

      async with asyncio.timeout(self.operation_timeout.total_seconds()):
        async with self.container.enter_scope() as scope:
          cleanup = await scope.get(CleanupRetentionUseCase)
          deleted = await cleanup.execute(limit=self.batch_size)

      if deleted:
        logger.info("Deleted %s terminal reservations and their associated confirmations", deleted)

      if deleted < self.batch_size:
        return


async def main() -> None:
  container = create_container()
  stop = asyncio.Event()
  loop = asyncio.get_running_loop()
  registered_signals = []

  try:
    policy = await container.get(RetentionPolicy)

    if not policy.enabled:
      logger.info("Retention cleanup disabled; keeping all history indefinitely")
      return

    for signum in (signal.SIGINT, signal.SIGTERM):
      loop.add_signal_handler(signum, stop.set)
      registered_signals.append(signum)

    settings = await container.get(TimePolicySettings)

    await RetentionWorker(
      container,
      settings.retention_cleanup_interval,
      batch_size=settings.RETENTION_BATCH_SIZE,
      max_batches=settings.RETENTION_MAX_BATCHES,
      operation_timeout=settings.retention_operation_timeout,
    ).run(stop)
  finally:
    for signum in registered_signals:
      loop.remove_signal_handler(signum)

    await container.close()


if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO)
  asyncio.run(main())
