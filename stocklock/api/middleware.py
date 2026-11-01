"""Request summaries without logging caller-controlled payloads or URLs."""

import asyncio
import logging
from time import perf_counter
from uuid import uuid4

from fastapi.routing import iter_route_contexts
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from stocklock.shared.logging import request_id

logger = logging.getLogger(__name__)
METHODS = frozenset({"GET", "POST", "PATCH", "DELETE", "PUT", "HEAD", "OPTIONS", "TRACE", "CONNECT"})


def _route_template(scope: Scope) -> str:
  selected = scope.get("route")
  # Included FastAPI routers retain the original route in scope. Resolve its
  # effective context to include router prefixes, without logging the raw URL.
  for context in iter_route_contexts(getattr(scope.get("app"), "routes", ())):
    if context.original_route is selected:
      match, _ = context.matches(scope)
      if match != Match.NONE:
        return context.path_format or "unmatched"
  return getattr(selected, "path_format", "unmatched")


class RequestLoggingMiddleware:
  def __init__(self, app: ASGIApp) -> None:
    self.app = app

  async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
    if scope["type"] != "http":
      await self.app(scope, receive, send)
      return

    correlation = str(uuid4())
    token = request_id.set(correlation)
    state = scope.setdefault("state", {})
    state["request_id"] = correlation
    started = perf_counter()
    status = None
    outcome = "completed"

    async def send_response(message: Message) -> None:
      nonlocal status
      if message["type"] == "http.response.start":
        status = message["status"]
        headers = [(k, v) for k, v in message.get("headers", []) if k.lower() != b"x-request-id"]
        message = {**message, "headers": [*headers, (b"x-request-id", correlation.encode("ascii"))]}
      await send(message)

    try:
      await self.app(scope, receive, send_response)
    except asyncio.CancelledError:
      outcome = "cancelled"
      raise
    except Exception:
      outcome = "failed"
      state["log_reason"] = "unhandled_exception"
      raise
    finally:
      try:
        route = _route_template(scope)
        response_status = status if status is not None else (499 if outcome == "cancelled" else 500)
        level = logging.ERROR if outcome == "failed" else logging.INFO
        if route == "/api/v1/healthcheck" and response_status == 200 and outcome == "completed":
          level = logging.DEBUG
        logger.log(
          level,
          "http.request.completed",
          extra={
            "request_id": correlation,
            "method": scope["method"] if scope["method"] in METHODS else "OTHER",
            "route": route,
            "status": response_status,
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "outcome": outcome,
            "reason": state.get("log_reason", f"http.{response_status}"),
          },
        )
      finally:
        request_id.reset(token)
