from dataclasses import dataclass
from datetime import datetime, timedelta

from stocklock.shared.exceptions import ValidationException
from stocklock.shared.utils.timestamps import as_utc


@dataclass(frozen=True, slots=True, kw_only=True)
class ReservationTimePolicy:
  """Lifetime of new holds; existing reservations keep their persisted deadlines."""

  lifetime: timedelta

  def __post_init__(self) -> None:
    if not isinstance(self.lifetime, timedelta) or self.lifetime <= timedelta(0):
      raise ValidationException("Reservation lifetime must be a positive duration")

  def expiration_for(self, created_at: datetime) -> datetime:
    try:
      return as_utc(created_at) + self.lifetime
    except OverflowError as error:
      raise ValidationException("Reservation lifetime exceeds the supported datetime range") from error
