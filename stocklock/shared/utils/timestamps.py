from datetime import datetime, timezone

from stocklock.shared.exceptions import ValidationException


def as_utc(value: datetime) -> datetime:
  """Normalize an aware timestamp without guessing a timezone for naive data."""
  if value.tzinfo is None or value.utcoffset() is None:
    raise ValidationException("Timestamp must be timezone-aware")

  return value.astimezone(timezone.utc)
