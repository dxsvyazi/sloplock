from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from stocklock.domain.errors import (
  IdempotencyConflict,
  InsufficientStock,
  NotFound,
  ProductHasActiveReservations,
  ReservationUnavailable,
  StockLimitExceeded,
)
from stocklock.shared.exceptions import ValidationException


async def handle_error(request: Request, error: Exception) -> JSONResponse:
  request.scope.setdefault("state", {})["log_reason"] = type(error).__name__
  if isinstance(error, NotFound):
    status_code = 404
  elif isinstance(error, ValidationException):
    status_code = 422
  else:
    status_code = 409

  return JSONResponse(status_code=status_code, content={"detail": str(error)})


def register_error_handlers(app: FastAPI) -> None:
  # Starlette's outer ServerErrorMiddleware sends this response after the request
  # logging middleware has re-raised. Recover the ID from scope, not task context.
  app.add_exception_handler(Exception, handle_unexpected_error)
  for error_type in (
    NotFound,
    ProductHasActiveReservations,
    ValidationException,
    InsufficientStock,
    IdempotencyConflict,
    ReservationUnavailable,
    StockLimitExceeded,
  ):
    app.add_exception_handler(error_type, handle_error)


async def handle_unexpected_error(request: Request, error: Exception) -> PlainTextResponse:
  correlation = request.scope.get("state", {}).get("request_id")
  headers = {"X-Request-ID": correlation} if correlation is not None else {}
  # The outer error response bypasses CORSMiddleware. Match the API's existing
  # allow-all-origins/credentials policy so browser clients can read the ID too.
  if origin := request.headers.get("origin"):
    headers.update(
      {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Expose-Headers": "X-Request-ID",
        "Vary": "Origin",
      }
    )
  return PlainTextResponse("Internal Server Error", status_code=500, headers=headers)
