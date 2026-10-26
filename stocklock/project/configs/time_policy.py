"""Environment time policies; launch the expiration worker separately."""

from datetime import timedelta
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from stocklock.project.configs import CustomBaseSettings

type PositiveSeconds = Annotated[int, Field(gt=0, le=2**31 - 1)]
type RetentionSeconds = Annotated[int, Field(ge=0, le=2**31 - 1)]


class TimePolicySettings(CustomBaseSettings):
  """Whole seconds; zero retention means keep indefinitely, not immediate deletion."""

  model_config = SettingsConfigDict(frozen=True)

  RESERVATION_LIFETIME_SECONDS: PositiveSeconds = 900
  EXPIRATION_CLEANUP_INTERVAL_SECONDS: PositiveSeconds = 60
  RETENTION_CLEANUP_INTERVAL_SECONDS: PositiveSeconds = 86400
  EXPIRED_RESERVATION_RETENTION_SECONDS: RetentionSeconds = 0
  CANCELLED_RESERVATION_RETENTION_SECONDS: RetentionSeconds = 0
  CONFIRMATION_RETENTION_SECONDS: RetentionSeconds = 0

  @field_validator(
    "RESERVATION_LIFETIME_SECONDS",
    "EXPIRATION_CLEANUP_INTERVAL_SECONDS",
    "RETENTION_CLEANUP_INTERVAL_SECONDS",
    "EXPIRED_RESERVATION_RETENTION_SECONDS",
    "CANCELLED_RESERVATION_RETENTION_SECONDS",
    "CONFIRMATION_RETENTION_SECONDS",
    mode="before",
  )
  @classmethod
  def validate_whole_seconds(cls, value: object) -> int | str:
    if type(value) is int:
      return value

    if isinstance(value, str) and value.isascii() and value.isdecimal():
      return value

    raise ValueError("Time policies must be whole seconds expressed as an integer")

  @property
  def reservation_lifetime(self) -> timedelta:
    return timedelta(seconds=self.RESERVATION_LIFETIME_SECONDS)

  @property
  def expiration_cleanup_interval(self) -> timedelta:
    return timedelta(seconds=self.EXPIRATION_CLEANUP_INTERVAL_SECONDS)

  @property
  def retention_cleanup_interval(self) -> timedelta:
    return timedelta(seconds=self.RETENTION_CLEANUP_INTERVAL_SECONDS)

  @property
  def expired_reservation_retention(self) -> timedelta | None:
    return _retention_duration(self.EXPIRED_RESERVATION_RETENTION_SECONDS)

  @property
  def cancelled_reservation_retention(self) -> timedelta | None:
    return _retention_duration(self.CANCELLED_RESERVATION_RETENTION_SECONDS)

  @property
  def confirmation_retention(self) -> timedelta | None:
    return _retention_duration(self.CONFIRMATION_RETENTION_SECONDS)


def _retention_duration(seconds: int) -> timedelta | None:
  return timedelta(seconds=seconds) if seconds else None
