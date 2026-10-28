from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException
from stocklock.shared.utils.timestamps import as_utc


@dataclass(frozen=True, slots=True, kw_only=True)
class RetentionPolicy:
  expired: timedelta | None
  cancelled: timedelta | None
  confirmed: timedelta | None

  def __post_init__(self) -> None:
    for duration in (self.expired, self.cancelled, self.confirmed):
      if duration is not None and (not isinstance(duration, timedelta) or duration <= timedelta(0)):
        raise ValidationException("Retention must be a positive duration or None for unlimited history")

  @property
  def enabled(self) -> bool:
    return any(duration is not None for duration in (self.expired, self.cancelled, self.confirmed))

  def cutoffs(self, now: datetime) -> dict[ReservationStatus, datetime]:
    now = as_utc(now)
    result = {}
    for status, duration in (
      (ReservationStatus.expired, self.expired),
      (ReservationStatus.cancelled, self.cancelled),
      (ReservationStatus.confirmed, self.confirmed),
    ):
      if duration is not None:
        try:
          result[status] = now - duration
        except OverflowError:
          result[status] = datetime.min.replace(tzinfo=timezone.utc)
    return result
