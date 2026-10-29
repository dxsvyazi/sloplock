from functools import partial
from uuid import UUID

from stocklock.shared.constraints import (
  MAX_IDEMPOTENCY_KEY_BYTES,
  MAX_IDEMPOTENCY_KEY_LENGTH,
  MAX_PAGE_SIZE,
  MAX_STOCK_QUANTITY,
)
from stocklock.shared.exceptions import ValidationException


def validate_int(value: int, *, minimum: int, maximum: int, field: str) -> None:
  if type(value) is not int or not minimum <= value <= maximum:
    raise ValidationException(f"{field} must be an integer between {minimum} and {maximum}")


validate_quantity = partial(validate_int, minimum=0, maximum=MAX_STOCK_QUANTITY, field="Quantity")

validate_page = partial(validate_int, minimum=1, maximum=MAX_PAGE_SIZE, field="Limit")


def validate_text(value: str, *, minimum: int = 1, maximum: int | None = None) -> None:
  if not isinstance(value, str) or len(value.strip()) < minimum or (maximum is not None and len(value) > maximum):
    raise ValidationException("Invalid text length")

  if value != value.strip():
    raise ValidationException("Text must not have surrounding whitespace")


def validate_id(value: UUID) -> None:
  if not isinstance(value, UUID):
    raise ValidationException("Identifier must be a UUID")


def validate_idempotency_key(value: str) -> str:
  """Validate an opaque, case-sensitive key without changing its identity."""
  validate_text(value, maximum=MAX_IDEMPOTENCY_KEY_LENGTH)

  if "\x00" in value:
    raise ValidationException("Idempotency key must not contain NUL")

  try:
    encoded = value.encode("utf-8")
  except UnicodeEncodeError as error:
    raise ValidationException("Idempotency key must be valid Unicode") from error

  if len(encoded) > MAX_IDEMPOTENCY_KEY_BYTES:
    raise ValidationException(f"Idempotency key must not exceed {MAX_IDEMPOTENCY_KEY_BYTES} UTF-8 bytes")

  return value


def require_type[T](value: object, expected: type[T]) -> None:
  """Enforce typed domain boundaries without coercing primitives or other concepts."""
  if not isinstance(value, expected):
    raise ValidationException(f"Expected {expected.__name__}")
