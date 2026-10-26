from typing import ClassVar


class StockLockError(Exception):
  """Base class for StockLock failures."""


class StaticException(StockLockError):
  """A failure with a fixed, class-level message."""

  message: ClassVar[str]

  def __init__(self) -> None:
    super().__init__(self.message)


class DynamicException(StockLockError):
  """A failure whose message describes the particular violation."""

  def __init__(self, message: str) -> None:
    super().__init__(message)


class ValidationException(DynamicException, ValueError):
  """Invalid input; ValueError compatibility lets Pydantic collect violations."""


class InvalidReservationStatus(StaticException, ValidationException):
  message = "Invalid reservation status"


class InvalidTransitionTarget(StaticException, ValidationException):
  message = "Target must be a terminal reservation status"


class MissingProductDetails(StaticException, ValidationException):
  message = "Supply at least one product detail"


class InvalidExpiration(StaticException, ValidationException):
  message = "expires_at must be after created_at"
