import asyncio
import logging
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from stocklock.api.middleware import RequestLoggingMiddleware
from stocklock.api.v1.errors import register_error_handlers
from stocklock.shared.logging import request_id


async def invoke(app, path="/items/secret", *, method="GET", headers=(), query=b"token=secret"):
  messages = []
  scope = {
    "type": "http",
    "asgi": {"version": "3.0"},
    "http_version": "1.1",
    "method": method,
    "scheme": "http",
    "path": path,
    "raw_path": path.encode(),
    "query_string": query,
    "root_path": "",
    "headers": list(headers),
    "client": ("test", 1),
    "server": ("test", 80),
  }

  async def receive():
    return {"type": "http.request", "body": b""}

  async def send(message):
    messages.append(message)

  try:
    await app(scope, receive, send)
  except RuntimeError:
    pass
  return messages


def make_app():
  app = FastAPI()
  register_error_handlers(app)
  app.add_middleware(CORSMiddleware, allow_origins=["*"], expose_headers=["X-Request-ID"])
  app.add_middleware(RequestLoggingMiddleware)

  @app.get("/items/{item_id}")
  async def item(item_id: str):
    before = request_id.get()
    await asyncio.sleep(0)
    assert request_id.get() == before
    logging.getLogger("stocklock.test").info("inside.request", extra={"observed": before})
    if item_id == "fail":
      raise RuntimeError("secret")
    return {"id": before}

  @app.get("/api/v1/healthcheck")
  async def health(fail: bool = False):
    if fail:
      raise HTTPException(503)
    return True

  return app


def summaries(caplog):
  return [r for r in caplog.records if r.getMessage() == "http.request.completed"]


async def test_concurrent_request_ids_headers_and_safe_routes(caplog):
  caplog.set_level(logging.INFO, logger="stocklock")
  app = make_app()
  first, second = await asyncio.gather(invoke(app), invoke(app, headers=[(b"x-request-id", b"forged")]))
  ids = []
  for messages in (first, second):
    start = next(m for m in messages if m["type"] == "http.response.start")
    value = dict(start["headers"])[b"x-request-id"].decode()
    UUID(value)
    ids.append(value)
  assert ids[0] != ids[1]
  assert request_id.get() is None
  records = summaries(caplog)
  assert len(records) == 2
  assert {r.request_id for r in records} == set(ids)
  assert all(r.route == "/items/{item_id}" and r.status == 200 and r.duration_ms >= 0 for r in records)
  assert "secret" not in caplog.text


async def test_failure_response_has_id_and_one_summary_without_traceback(caplog):
  caplog.set_level(logging.INFO, logger="stocklock")
  messages = await invoke(make_app(), "/items/fail")
  start = next(m for m in messages if m["type"] == "http.response.start")
  (record,) = summaries(caplog)
  assert start["status"] == record.status == 500
  assert dict(start["headers"])[b"x-request-id"].decode() == record.request_id
  assert record.exc_info is None
  assert record.levelno == logging.ERROR
  assert request_id.get() is None
  assert "secret" not in caplog.text


async def test_unmatched_routes_validation_and_cors_preflight(caplog):
  caplog.set_level(logging.INFO, logger="stocklock")
  app = make_app()
  await invoke(app, "/missing/secret")
  await invoke(app, "/api/v1/healthcheck", query=b"fail=invalid-secret")
  messages = await invoke(
    app, method="OPTIONS", headers=[(b"origin", b"https://example.com"), (b"access-control-request-method", b"GET")]
  )
  records = summaries(caplog)
  assert records[0].route == "unmatched"
  assert records[1].status == 422
  assert records[1].reason == "http.422"
  assert dict(messages[0]["headers"])[b"x-request-id"]
  assert "secret" not in caplog.text
  messages = await invoke(app, headers=[(b"origin", b"https://example.com")])
  assert b"X-Request-ID" in dict(messages[0]["headers"])[b"access-control-expose-headers"]


async def test_successful_healthchecks_debug_failures_visible(caplog):
  caplog.set_level(logging.DEBUG, logger="stocklock")
  app = make_app()
  await invoke(app, "/api/v1/healthcheck", query=b"")
  await invoke(app, "/api/v1/healthcheck", query=b"fail=true")
  good, bad = summaries(caplog)
  assert good.levelno == logging.DEBUG
  assert bad.status == 503 and bad.levelno >= logging.INFO


async def test_cancellation_resets_context(caplog):
  entered = asyncio.Event()

  async def wait(scope, receive, send):
    assert request_id.get() is not None
    entered.set()
    await asyncio.Event().wait()

  token = request_id.set("parent")
  try:
    task = asyncio.create_task(invoke(RequestLoggingMiddleware(wait)))
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
      await task
    assert request_id.get() == "parent"
  finally:
    request_id.reset(token)


async def test_browser_can_read_request_id_on_unhandled_error(caplog):
  caplog.set_level(logging.INFO, logger="stocklock")
  messages = await invoke(make_app(), "/items/fail", headers=[(b"origin", b"https://example.com")])
  headers = dict(messages[0]["headers"])
  assert b"access-control-allow-origin" in headers
  assert b"X-Request-ID" in headers[b"access-control-expose-headers"]


async def test_nested_api_routers_keep_full_route_template_and_quiet_healthcheck(caplog):
  from fastapi import APIRouter

  caplog.set_level(logging.DEBUG, logger="stocklock")
  app = FastAPI()
  app.add_middleware(RequestLoggingMiddleware)
  root = APIRouter(prefix="/api/v1")
  health = APIRouter(prefix="/healthcheck")

  @health.get("")
  async def healthy():
    return True

  root.include_router(health)
  app.include_router(root)
  await invoke(app, "/api/v1/healthcheck", query=b"")
  record, = summaries(caplog)
  assert record.route == "/api/v1/healthcheck"
  assert record.levelno == logging.DEBUG
