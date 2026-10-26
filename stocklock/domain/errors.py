from stocklock.shared.exceptions import DynamicException, StaticException
from stocklock.shared.exceptions import StockLockError as StockLockError


class NotFound(DynamicException):
  pass


class ProductNotFound(StaticException, NotFound):
  message = "Product not found"


class ReservationNotFound(StaticException, NotFound):
  message = "Reservation not found"


class InsufficientStock(StaticException):
  message = "Not enough available stock"


class IdempotencyConflict(StaticException):
  message = "Idempotency key was used for a different quantity"


class ReservationUnavailable(DynamicException):
  pass


class StockLimitExceeded(StaticException):
  message = "Returning held units would exceed the supported stock range"


class StockCapacityExceeded(StockLimitExceeded):
  message = "Stock correction must leave room to return all active reservations"


class MissingConfirmation(StaticException):
  message = "Confirmed reservation has no confirmation result"
