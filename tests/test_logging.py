import json
import logging
from logging.config import dictConfig
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stocklock.project.configs.logging import LoggingSettings
from stocklock.project.logging import logging_config
from stocklock.shared.logging import SafeFormatter, request_id


@pytest.mark.parametrize("format", ["text", "json"])
def test_safe_single_line_output_and_context(format):
  resource = uuid4()
  record = logging.LogRecord("stocklock.test", logging.INFO, __file__, 1, "reservation.created", (), None)
  record.product_id = resource
  record.quantity = 2
  record.authorization = "Bearer secret"
  record.body = {"key": "secret"}
  record.outcome = "created\nforged"
  record.request_id = "request-1"
  output = SafeFormatter(format).format(record)
  assert len(output.splitlines()) == 1
  assert str(resource) in output
  assert "secret" not in output
  assert "request-1" in output
  assert "\\n" in output
  if format == "json":
    payload = json.loads(output)
    assert payload["quantity"] == 2
    assert payload["timestamp"].endswith("Z")
    assert payload["event"] == "reservation.created"


@pytest.mark.parametrize("format", ["text", "json"])
def test_traceback_omits_messages_source_and_locals(format):
  try:
    try:
      raise ValueError("password=secret-inner")
    except ValueError as cause:
      raise RuntimeError("key=secret-outer") from cause
  except RuntimeError:
    import sys

    record = logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1, "ASGI failure", (), sys.exc_info())
  output = SafeFormatter(format).format(record)
  assert "secret" not in output
  assert "RuntimeError" in output
  assert "ValueError" in output
  assert "test_traceback_omits_messages_source_and_locals" in output
  assert len(output.splitlines()) == 1


def test_unrecognized_extras_and_objects_are_not_stringified():
  class Unsafe:
    def __str__(self):
      raise AssertionError("Must not stringify arbitrary objects")

  record = logging.LogRecord("dependency", logging.ERROR, __file__, 1, Unsafe(), (), None)
  record.product_id = Unsafe()
  record.password = Unsafe()
  output = SafeFormatter("json").format(record)
  assert "product_id" not in json.loads(output)


@pytest.mark.parametrize("values", [{"LOG_LEVEL": "TRACE"}, {"LOG_FORMAT": "xml"}])
def test_invalid_logging_settings_rejected(values):
  with pytest.raises(ValidationError):
    LoggingSettings(_env_file=None, **values)


def test_configuration_routes_once_and_captures_context(capsys, monkeypatch):
  monkeypatch.setenv("LOG_FORMAT", "json")
  root = logging.getLogger()
  names = ("stocklock", "uvicorn", "uvicorn.error", "uvicorn.access")
  loggers = [root, *(logging.getLogger(name) for name in names)]
  saved = [(item, item.handlers[:], item.level, item.propagate, item.disabled) for item in loggers]
  token = request_id.set("correlation")
  try:
    dictConfig(logging_config("api"))
    logging.getLogger("stocklock.test").info("operation.complete")
    logging.getLogger("uvicorn.error").info("Server started")
    logging.getLogger("uvicorn.access").info("raw secret path")
    captured = capsys.readouterr()
    lines = (captured.out + captured.err).splitlines()
    assert len(lines) == 2
    records = [json.loads(line) for line in lines]
    assert all(item["role"] == "api" and item["request_id"] == "correlation" for item in records)
  finally:
    request_id.reset(token)
    for item, handlers, level, propagate, disabled in saved:
      item.handlers, item.level, item.propagate, item.disabled = handlers, level, propagate, disabled


def test_project_uuid7_identifiers_are_serialized():
  from uuid6 import uuid7

  resource = uuid7()
  record = logging.LogRecord("stocklock.test", logging.INFO, __file__, 1, "product.created", (), None)
  record.product_id = resource
  assert json.loads(SafeFormatter("json").format(record))["product_id"] == str(resource)


@pytest.mark.parametrize("phase", ["startup", "shutdown"])
async def test_actual_uvicorn_lifespan_failure_does_not_leak_formatted_tracebacks(phase):
  import io
  from contextlib import asynccontextmanager

  from starlette.applications import Starlette
  from uvicorn import Config
  from uvicorn.lifespan.on import LifespanOn

  @asynccontextmanager
  async def lifespan(app):
    if phase == "startup":
      raise RuntimeError("password=LIFESPAN_SECRET")
    yield
    raise RuntimeError("password=LIFESPAN_SECRET")

  stream = io.StringIO()
  handler = logging.StreamHandler(stream)
  handler.setFormatter(SafeFormatter("json"))
  logger = logging.getLogger("uvicorn.error")
  saved = logger.handlers[:], logger.level, logger.propagate
  logger.handlers, logger.level, logger.propagate = [handler], logging.INFO, False
  try:
    state = LifespanOn(Config(Starlette(lifespan=lifespan), lifespan="on", log_config=None))
    await state.startup()
    if phase == "shutdown":
      await state.shutdown()
    output = stream.getvalue()
    assert "LIFESPAN_SECRET" not in output
    assert "Traceback (most recent call last)" not in output
    assert any("failed" in json.loads(line)["event"] for line in output.splitlines())
  finally:
    logger.handlers, logger.level, logger.propagate = saved


def test_plain_uvicorn_failure_message_is_not_trusted():
  record = logging.LogRecord("uvicorn.error", logging.ERROR, __file__, 1, "password=RAW_SECRET", (), None)
  output = SafeFormatter("json").format(record)
  assert "RAW_SECRET" not in output
  assert json.loads(output)["event"] == "server.message"
