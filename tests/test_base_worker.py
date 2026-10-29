import asyncio
from datetime import timedelta

import pytest

from stocklock.infrastructure.workers.base import BaseWorker
from stocklock.infrastructure.workers.expiration import ExpirationWorker
from stocklock.infrastructure.workers.retention import RetentionWorker


class FailingWorker(BaseWorker):
  exception_message = "A test sweep failed"
  calls = 0

  async def _run_once(self, *, stop=None):
    self.calls += 1
    if self.calls == 1:
      raise RuntimeError("injected")
    stop.set()


async def test_shared_loop_logs_retries_and_stops(caplog):
  worker = FailingWorker(None, timedelta(milliseconds=1))
  stop = asyncio.Event()
  await asyncio.wait_for(worker.run(stop), 1)
  assert worker.calls == 2
  assert "A test sweep failed" in caplog.text
  await worker.run(stop)
  assert worker.calls == 2


async def test_shared_loop_propagates_cancellation():
  entered = asyncio.Event()

  class WaitingWorker(BaseWorker):
    async def _run_once(self, *, stop=None):
      entered.set()
      await asyncio.Event().wait()

  task = asyncio.create_task(WaitingWorker(None, timedelta(seconds=1)).run(asyncio.Event()))
  await asyncio.wait_for(entered.wait(), 1)
  task.cancel()
  with pytest.raises(asyncio.CancelledError):
    await task


def test_existing_workers_derive_abstract_base():
  assert issubclass(ExpirationWorker, BaseWorker)
  assert issubclass(RetentionWorker, BaseWorker)
  with pytest.raises(TypeError):
    BaseWorker(None, timedelta(days=1))


@pytest.mark.parametrize("worker", [ExpirationWorker, RetentionWorker, FailingWorker])
@pytest.mark.parametrize(
  "kwargs",
  [
    {"interval": timedelta(0)},
    {"batch_size": True},
    {"batch_size": 101},
    {"max_batches": True},
    {"max_batches": 0},
    {"operation_timeout": timedelta(0)},
  ],
)
def test_base_validates_common_attributes(worker, kwargs):
  with pytest.raises(ValueError):
    worker(None, **({"interval": timedelta(days=1)} | kwargs))
