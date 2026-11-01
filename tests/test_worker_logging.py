import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from stocklock.application.usecases.expiration import ExpireReservationsUseCase, ListDueReservationsUseCase
from stocklock.application.usecases.product_cleanup import CleanupProductsUseCase
from stocklock.application.usecases.reservation import TryExpireReservationUseCase
from stocklock.application.usecases.retention import CleanupRetentionUseCase
from stocklock.infrastructure.workers.expiration import ExpirationWorker
from stocklock.infrastructure.workers.product_cleanup import ProductCleanupWorker
from stocklock.infrastructure.workers.retention import RetentionWorker
from stocklock.shared.logging import sweep_id


class Container:
  def __init__(self, services):
    self.services = services

  @asynccontextmanager
  async def enter_scope(self):
    yield self

  async def get(self, cls):
    return self.services[cls]


def summary(caplog):
  records = [r for r in caplog.records if r.getMessage() == "worker.sweep.completed"]
  assert len(records) == 1
  return records[0]


@pytest.mark.parametrize(
  "worker_type,usecase", [(RetentionWorker, CleanupRetentionUseCase), (ProductCleanupWorker, CleanupProductsUseCase)]
)
async def test_cleanup_summaries_count_successful_batches(caplog, worker_type, usecase):
  caplog.set_level(logging.DEBUG, logger="stocklock")
  cleanup = SimpleNamespace(execute=AsyncMock(side_effect=[2, 1]))
  worker = worker_type(Container({usecase: cleanup}), timedelta(seconds=1), batch_size=2)
  await worker.run_once()
  record = summary(caplog)
  assert (record.changed, record.processed, record.batches, record.failed) == (3, 3, 2, 0)
  assert record.levelno == logging.INFO
  assert record.duration_ms >= 0 and record.sweep_id
  assert sweep_id.get() is None
  caplog.clear()
  cleanup.execute.side_effect = [0]
  await worker.run_once()
  assert summary(caplog).levelno == logging.DEBUG


@pytest.mark.parametrize("fallback", [False, True])
async def test_expiration_summary_counts_only_actual_transitions(caplog, fallback):
  caplog.set_level(logging.DEBUG, logger="stocklock")
  ids = [uuid4(), uuid4(), uuid4()]
  bulk = AsyncMock(side_effect=RuntimeError("failure")) if fallback else AsyncMock(return_value=ids[:1])
  individual = AsyncMock(side_effect=[SimpleNamespace(id=ids[0]), None, RuntimeError("failure")])
  worker = ExpirationWorker(
    Container(
      {
        ListDueReservationsUseCase: SimpleNamespace(execute=AsyncMock(side_effect=[ids, []])),
        ExpireReservationsUseCase: SimpleNamespace(execute=bulk),
        TryExpireReservationUseCase: SimpleNamespace(execute=individual),
      }
    ),
    timedelta(seconds=1),
  )
  await worker.run_once()
  record = summary(caplog)
  assert record.changed == 1 and record.processed == 3
  assert record.skipped == (1 if fallback else 2)
  assert record.failed == (1 if fallback else 0)
  assert record.outcome == ("partial_failure" if fallback else "completed")
  assert record.levelno == (logging.ERROR if fallback else logging.INFO)


async def test_partial_cleanup_failure_logs_honest_counts_and_one_traceback(caplog):
  caplog.set_level(logging.DEBUG, logger="stocklock")
  worker = RetentionWorker(
    Container({CleanupRetentionUseCase: SimpleNamespace(execute=AsyncMock(side_effect=[2, RuntimeError("secret")]))}),
    timedelta(seconds=1),
    batch_size=2,
  )
  with pytest.raises(RuntimeError):
    await worker.run_once()
  record = summary(caplog)
  assert record.changed == 2 and record.outcome == "failed" and record.failed == 1
  assert len([r for r in caplog.records if r.exc_info]) == 1
  assert sweep_id.get() is None


async def test_cancellation_has_summary_and_resets_context(caplog):
  caplog.set_level(logging.DEBUG, logger="stocklock")
  entered = asyncio.Event()

  async def wait(**kwargs):
    entered.set()
    await asyncio.Event().wait()

  worker = RetentionWorker(Container({CleanupRetentionUseCase: SimpleNamespace(execute=wait)}), timedelta(seconds=1))
  task = asyncio.create_task(worker.run_once())
  await entered.wait()
  task.cancel()
  with pytest.raises(asyncio.CancelledError):
    await task
  assert summary(caplog).outcome == "cancelled"
  assert not any(r.exc_info for r in caplog.records)
  assert sweep_id.get() is None


@pytest.mark.parametrize("role", ["retention", "product_cleanup"])
def test_actual_worker_cli_emits_lifecycle_events(role, tmp_path):
  import json
  import os
  import subprocess
  import sys
  from pathlib import Path

  environment = {
    **os.environ,
    "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    "LOG_FORMAT": "json",
    "LOG_LEVEL": "INFO",
    "EXPIRED_RESERVATION_RETENTION_SECONDS": "0",
    "CANCELLED_RESERVATION_RETENTION_SECONDS": "0",
    "CONFIRMATION_RETENTION_SECONDS": "0",
    "DELETED_PRODUCT_RETENTION_SECONDS": "0",
  }
  result = subprocess.run(
    [sys.executable, "-m", f"stocklock.infrastructure.workers.{role}"],
    cwd=tmp_path,
    env=environment,
    capture_output=True,
    text=True,
    timeout=10,
  )
  assert result.returncode == 0, result.stderr
  records = [json.loads(line) for line in result.stdout.splitlines()]
  assert len(records) == 3
  assert records[0]["event"] == "worker.started"
  assert "disabled" in records[1]["event"]
  assert records[2]["event"] == "worker.stopped"
  assert all(record["role"] == role for record in records)


async def test_failed_individual_expiration_keeps_id_in_formatted_record(caplog):
  import json

  from stocklock.shared.logging import SafeFormatter

  item = uuid4()
  worker = ExpirationWorker(
    Container(
      {
        ListDueReservationsUseCase: SimpleNamespace(execute=AsyncMock(return_value=[item])),
        ExpireReservationsUseCase: SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("bulk"))),
        TryExpireReservationUseCase: SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("individual"))),
      }
    ),
    timedelta(seconds=1),
  )
  await worker.run_once()
  failures = [r for r in caplog.records if r.getMessage() == "reservation.expiration.failed"]
  assert len(failures) == 1
  payload = json.loads(SafeFormatter("json").format(failures[0]))
  assert payload["reservation_id"] == str(item)
