"""Common limits and stop-aware retry loop for infrastructure workers."""

import asyncio
import logging
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import timedelta
from time import perf_counter
from typing import ClassVar
from uuid import uuid4

from wireup import AsyncContainer

from stocklock.domain.validation import validate_page, validate_quantity
from stocklock.shared.logging import sweep_id


@dataclass(slots=True)
class SweepProgress:
  processed: int = 0
  changed: int = 0
  skipped: int = 0
  failed: int = 0
  batches: int = 0


_progress: ContextVar[SweepProgress | None] = ContextVar("worker_progress", default=None)
logger = logging.getLogger(__name__)


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

  @property
  def progress(self) -> SweepProgress:
    progress = _progress.get()
    if progress is None:
      raise RuntimeError("Worker progress requires a sweep context")
    return progress

  async def run_once(self, *, stop: asyncio.Event | None = None) -> None:
    """Run a single sweep, propagating errors to the caller."""
    progress = SweepProgress()
    progress_token = _progress.set(progress)
    correlation = str(uuid4())
    token = sweep_id.set(correlation)
    started = perf_counter()
    outcome = "completed"
    try:
      await self._run_once(stop=stop)
      if progress.failed:
        outcome = "partial_failure"
      elif stop is not None and stop.is_set():
        outcome = "stopped"
      elif progress.batches >= self.max_batches:
        outcome = "bounded"
    except asyncio.CancelledError:
      outcome = "cancelled"
      raise
    except Exception:
      outcome = "failed"
      progress.failed += 1
      logger.exception(self.exception_message)
      raise
    finally:
      try:
        level = logging.ERROR if progress.failed else logging.INFO
        if not progress.processed and outcome == "completed":
          level = logging.DEBUG
        logger.log(
          level,
          "worker.sweep.completed",
          extra={
            "sweep_id": correlation,
            "outcome": outcome,
            "processed": progress.processed,
            "changed": progress.changed,
            "skipped": progress.skipped,
            "failed": progress.failed,
            "batches": progress.batches,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
          },
        )
      finally:
        sweep_id.reset(token)
        _progress.reset(progress_token)

  async def run(self, stop: asyncio.Event) -> None:
    while not stop.is_set():
      try:
        await self.run_once(stop=stop)
      except Exception:
        # run_once already recorded the failure and traceback in its sweep context.
        pass

      try:
        await asyncio.wait_for(stop.wait(), timeout=self.interval.total_seconds())
      except TimeoutError:
        pass
