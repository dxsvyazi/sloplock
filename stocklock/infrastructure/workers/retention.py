"""Run with python -m stocklock.infrastructure.workers.retention."""

import asyncio
import logging
import signal
from dataclasses import dataclass
from datetime import timedelta

from wireup import AsyncContainer

from stocklock.application.policies.retention import RetentionPolicy
from stocklock.application.usecases.retention import CleanupRetentionUseCase
from stocklock.domain.validation import validate_page, validate_quantity
from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.project.container import create_container

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RetentionWorker:
  container: AsyncContainer
  interval: timedelta
  batch_size: int = 100
  max_batches: int = 100
  operation_timeout: timedelta = timedelta(seconds=30)

  def __post_init__(self) -> None:
    validate_page(self.batch_size)
    validate_quantity(self.max_batches, minimum=1)
    for duration in (self.interval, self.operation_timeout):
      if not isinstance(duration, timedelta) or duration <= timedelta(0):
        raise ValueError("Worker interval and operation timeout must be positive durations")

  async def run_once(self, *, stop: asyncio.Event | None = None) -> None:
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

  async def run(self, stop: asyncio.Event) -> None:
    while not stop.is_set():
      try:
        await self.run_once(stop=stop)
      except Exception:
        logger.exception("Retention sweep failed; retrying after the configured interval")

      try:
        await asyncio.wait_for(stop.wait(), timeout=self.interval.total_seconds())
      except TimeoutError:
        pass


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
