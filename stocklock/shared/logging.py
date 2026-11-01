"""Safe console records and task-local operational context; no framework imports."""

import json
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import PurePath
from uuid import UUID

request_id: ContextVar[str | None] = ContextVar("log_request_id", default=None)
sweep_id: ContextVar[str | None] = ContextVar("log_sweep_id", default=None)

# Uvicorn also logs arbitrary lifespan failure strings, including formatted
# tracebacks. Trust specific server templates, never the logger name alone.
UVICORN_TEMPLATES = frozenset(
  {
    "Waiting for application startup.",
    "Application startup complete.",
    "Application startup failed. Exiting.",
    "Waiting for application shutdown.",
    "Application shutdown complete.",
    "Application shutdown failed. Exiting.",
    "ASGI 'lifespan' protocol appears unsupported.",
    "Exception in 'lifespan' protocol\n",
    "Exception in ASGI application\n",
    "Started server process [%d]",
    "Finished server process [%d]",
    "Shutting down",
    '"workers" flag is ignored when reloading is enabled.',
    "Uvicorn running on %s://%s:%d (Press CTRL+C to quit)",
    "Uvicorn running on %s://[%s]:%d (Press CTRL+C to quit)",
    "Started reloader process [%d] using %s",
    "Stopping reloader process [%d]",
    "Waiting for connections to close. (CTRL+C to force quit)",
    "Waiting for background tasks to complete. (CTRL+C to force quit)",
    "Cancel %s running task(s), timeout graceful shutdown exceeded",
    "Invalid HTTP request received.",
    "Exceeded maximum concurrency limit.",
    "ASGI callable returned without starting response.",
    "ASGI callable returned without completing response.",
  }
)

FIELDS = frozenset(
  {
    "request_id",
    "sweep_id",
    "product_id",
    "reservation_id",
    "confirmation_id",
    "quantity",
    "outcome",
    "method",
    "route",
    "status",
    "duration_ms",
    "reason",
    "mode",
    "changed_fields",
    "previous_stock",
    "stock_quantity",
    "processed",
    "changed",
    "skipped",
    "failed",
    "batches",
  }
)


def _safe_value(value: object) -> object:
  if value is None or type(value) in (bool, int, float):
    return value
  if type(value) is str:
    return value[:256]
  if isinstance(value, UUID):
    return UUID.__str__(value)
  if type(value) in (list, tuple) and all(type(item) is str for item in value):
    return [item[:64] for item in value[:16]]
  return None


def _exception_details(error: BaseException, *, depth: int = 0) -> dict:
  # Never call str(error), read source lines, or inspect frame locals.
  frames = []
  trace = error.__traceback__
  while trace is not None and len(frames) < 40:
    code = trace.tb_frame.f_code
    frames.append(f"{PurePath(code.co_filename).name}:{trace.tb_lineno}:{code.co_name}")
    trace = trace.tb_next
  result = {"type": type(error).__name__, "frames": frames}
  if depth < 4:
    cause = error.__cause__ or (None if error.__suppress_context__ else error.__context__)
    if cause is not None:
      result["cause"] = _exception_details(cause, depth=depth + 1)
    if isinstance(error, BaseExceptionGroup):
      result["exceptions"] = [_exception_details(item, depth=depth + 1) for item in error.exceptions[:8]]
  return result


class LogContextFilter(logging.Filter):
  def __init__(self, role: str) -> None:
    super().__init__()
    self.role = role

  def filter(self, record: logging.LogRecord) -> bool:
    record.role = self.role
    record.request_id = request_id.get()
    record.sweep_id = sweep_id.get()
    return True


class SafeFormatter(logging.Formatter):
  """Allowlisted fields and message-free exceptions in either console format."""

  def __init__(self, format: str = "text") -> None:
    super().__init__()
    self.output_format = format

  def format(self, record: logging.LogRecord) -> str:
    server_record = record.name == "uvicorn" or record.name.startswith("uvicorn.")
    event = "server.message" if server_record else "dependency.message"
    controlled_message = record.name.startswith("stocklock.") or (
      server_record and type(record.msg) is str and record.msg in UVICORN_TEMPLATES
    )
    if controlled_message and type(record.msg) is str:
      args = record.args
      if not args or (type(args) is tuple and all(type(v) in (str, int, float) for v in args)):
        event = record.getMessage()[:512]
    payload = {
      "timestamp": datetime.fromtimestamp(record.created, timezone.utc)
      .isoformat(timespec="milliseconds")
      .replace("+00:00", "Z"),
      "level": record.levelname,
      "logger": record.name,
      "role": getattr(record, "role", "unknown"),
      "event": event,
    }
    for name in sorted(FIELDS):
      value = _safe_value(getattr(record, name, None))
      if value is not None:
        payload[name] = value
    if record.exc_info and record.exc_info[1] is not None:
      payload["exception"] = _exception_details(record.exc_info[1])
    elif isinstance(record.msg, BaseException):
      payload["exception"] = _exception_details(record.msg)
    if self.output_format == "json":
      return json.dumps(payload, ensure_ascii=True)
    return " ".join(f"{key}={json.dumps(value, ensure_ascii=True)}" for key, value in payload.items())
