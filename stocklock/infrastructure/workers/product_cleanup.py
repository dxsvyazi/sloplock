"""Run with python -m stocklock.infrastructure.workers.product_cleanup."""

import asyncio
import logging
import signal
from dataclasses import dataclass

from stocklock.application.policies.product_cleanup import ProductCleanupPolicy
from stocklock.application.usecases.product_cleanup import CleanupProductsUseCase
from stocklock.infrastructure.workers.base import BaseWorker
from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.project.container import create_container

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ProductCleanupWorker(BaseWorker):
  exception_message = "Product cleanup sweep failed; retrying after the configured interval"

  async def _run_once(self, *, stop: asyncio.Event | None = None) -> None:
    for _ in range(self.max_batches):
      if stop is not None and stop.is_set():
        return

      async with asyncio.timeout(self.operation_timeout.total_seconds()):
        async with self.container.enter_scope() as scope:
          cleanup = await scope.get(CleanupProductsUseCase)
          deleted = await cleanup.execute(limit=self.batch_size)

      if deleted:
        logger.info("Deleted %s soft-deleted products without reservations", deleted)

      if deleted < self.batch_size:
        return


async def main() -> None:
  container = create_container()
  stop = asyncio.Event()
  loop = asyncio.get_running_loop()
  registered_signals = []

  try:
    policy = await container.get(ProductCleanupPolicy)

    if not policy.enabled:
      logger.info("Product cleanup disabled; keeping soft-deleted products indefinitely")
      return

    for signum in (signal.SIGINT, signal.SIGTERM):
      loop.add_signal_handler(signum, stop.set)
      registered_signals.append(signum)

    settings = await container.get(TimePolicySettings)

    await ProductCleanupWorker(
      container,
      settings.product_cleanup_interval,
      batch_size=settings.PRODUCT_CLEANUP_BATCH_SIZE,
      max_batches=settings.PRODUCT_CLEANUP_MAX_BATCHES,
      operation_timeout=settings.product_cleanup_operation_timeout,
    ).run(stop)
  finally:
    for signum in registered_signals:
      loop.remove_signal_handler(signum)

    await container.close()


if __name__ == "__main__":
  logging.basicConfig(level=logging.INFO)
  asyncio.run(main())
