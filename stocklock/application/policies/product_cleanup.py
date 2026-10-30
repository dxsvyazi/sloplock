from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from stocklock.shared.exceptions import ValidationException
from stocklock.shared.utils.timestamps import as_utc


@dataclass(frozen=True, slots=True, kw_only=True)
class ProductCleanupPolicy:
  retention: timedelta | None

  def __post_init__(self) -> None:
    if self.retention is not None and (not isinstance(self.retention, timedelta) or self.retention <= timedelta(0)):
      raise ValidationException("Product retention must be positive or None to disable cleanup")

  @property
  def enabled(self) -> bool:
    return self.retention is not None

  def cutoff(self, now: datetime) -> datetime | None:
    if self.retention is None:
      return None

    try:
      return as_utc(now) - self.retention
    except OverflowError:
      return datetime.min.replace(tzinfo=timezone.utc)
