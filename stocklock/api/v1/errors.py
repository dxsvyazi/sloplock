from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from stocklock.domain.errors import (
  IdempotencyConflict,
  InsufficientStock,
  NotFound,
  ReservationUnavailable,
  StockLimitExceeded,
)
from stocklock.shared.exceptions import ValidationException


async def handle_error(request: Request, error: Exception) -> JSONResponse:
  if isinstance(error, NotFound):
    status_code = 404
  elif isinstance(error, ValidationException):
    status_code = 422
  else:
    status_code = 409

  return JSONResponse(status_code=status_code, content={"detail": str(error)})


def register_error_handlers(app: FastAPI) -> None:
  for error_type in (
    NotFound,
    ValidationException,
    InsufficientStock,
    IdempotencyConflict,
    ReservationUnavailable,
    StockLimitExceeded,
  ):
    app.add_exception_handler(error_type, handle_error)
