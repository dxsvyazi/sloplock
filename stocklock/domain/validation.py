from uuid import UUID

from stocklock.shared.constraints import (
  DEFAULT_PAGE_SIZE,
  MAX_IDEMPOTENCY_KEY_BYTES,
  MAX_IDEMPOTENCY_KEY_LENGTH,
  MAX_PAGE_SIZE,
  MAX_STOCK_QUANTITY,
)
from stocklock.shared.exceptions import ValidationException


def validate_quantity(value: int, *, minimum: int = 0, maximum: int = MAX_STOCK_QUANTITY) -> None:
  if type(value) is not int or not minimum <= value <= maximum:
    raise ValidationException(f"Quantity must be an integer between {minimum} and {maximum}")


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


def validate_page(limit: int = DEFAULT_PAGE_SIZE) -> None:
  validate_quantity(limit, minimum=1, maximum=MAX_PAGE_SIZE)
