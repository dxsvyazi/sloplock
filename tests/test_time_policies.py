from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from stocklock.shared.exceptions import ValidationException


TIME_FIELDS: tuple[str, ...] = (
  "RESERVATION_LIFETIME_SECONDS",
  "EXPIRATION_CLEANUP_INTERVAL_SECONDS",
  "RETENTION_CLEANUP_INTERVAL_SECONDS",
  "EXPIRED_RESERVATION_RETENTION_SECONDS",
  "CANCELLED_RESERVATION_RETENTION_SECONDS",
  "CONFIRMATION_RETENTION_SECONDS",
)


@pytest.fixture(autouse=True)
def isolated_time_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
  monkeypatch.chdir(tmp_path)
  for name in TIME_FIELDS:
    monkeypatch.delenv(name, raising=False)


def test_default_policy_has_fifteen_minute_holds_and_thirty_day_retention() -> None:
  from stocklock.project.configs.time_policy import TimePolicySettings

  settings = TimePolicySettings()
  assert settings.reservation_lifetime == timedelta(minutes=15)
  assert settings.expiration_cleanup_interval == timedelta(minutes=1)
  assert settings.retention_cleanup_interval == timedelta(days=1)
  assert settings.expired_reservation_retention == timedelta(days=30)
  assert settings.cancelled_reservation_retention == timedelta(days=30)
  assert settings.confirmation_retention == timedelta(days=30)


def test_environment_overrides_dotenv_and_all_durations_are_converted(
  monkeypatch: pytest.MonkeyPatch,
  tmp_path: Path,
) -> None:
  from stocklock.project.configs.time_policy import TimePolicySettings

  (tmp_path / ".env").write_text(
    "RESERVATION_LIFETIME_SECONDS=120\nEXPIRATION_CLEANUP_INTERVAL_SECONDS=10\n"
    "RETENTION_CLEANUP_INTERVAL_SECONDS=3600\nEXPIRED_RESERVATION_RETENTION_SECONDS=86400\n"
    "CANCELLED_RESERVATION_RETENTION_SECONDS=172800\nCONFIRMATION_RETENTION_SECONDS=604800\n",
    encoding="utf-8",
  )
  monkeypatch.setenv("RESERVATION_LIFETIME_SECONDS", "180")
  settings = TimePolicySettings()
  assert settings.reservation_lifetime == timedelta(minutes=3)
  assert settings.expiration_cleanup_interval == timedelta(seconds=10)
  assert settings.retention_cleanup_interval == timedelta(hours=1)
  assert settings.expired_reservation_retention == timedelta(days=1)
  assert settings.cancelled_reservation_retention == timedelta(days=2)
  assert settings.confirmation_retention == timedelta(days=7)


@pytest.mark.parametrize("name", TIME_FIELDS)
@pytest.mark.parametrize("value", ["-1", "1.5", "1.0", "NaN", "inf", "true", "", "2147483648"])
def test_invalid_environment_duration_is_rejected(
  monkeypatch: pytest.MonkeyPatch,
  name: str,
  value: str,
) -> None:
  from stocklock.project.configs.time_policy import TimePolicySettings

  monkeypatch.setenv(name, value)
  with pytest.raises(ValidationError):
    TimePolicySettings()


@pytest.mark.parametrize("name", TIME_FIELDS[:3])
def test_lifetime_and_worker_intervals_cannot_be_zero(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
  from stocklock.project.configs.time_policy import TimePolicySettings

  monkeypatch.setenv(name, "0")
  with pytest.raises(ValidationError):
    TimePolicySettings()


def test_programmatic_settings_reject_booleans_and_floats() -> None:
  from stocklock.project.configs.time_policy import TimePolicySettings

  with pytest.raises(ValidationError):
    TimePolicySettings(RESERVATION_LIFETIME_SECONDS=True)
  with pytest.raises(ValidationError):
    TimePolicySettings(RESERVATION_LIFETIME_SECONDS=1.0)  # type: ignore[arg-type]


def test_policy_normalizes_to_utc_and_uses_supplied_creation_time() -> None:
  from stocklock.application.policies.reservation import ReservationTimePolicy

  policy = ReservationTimePolicy(lifetime=timedelta(seconds=90))
  created_at = datetime(2026, 1, 1, 7, tzinfo=timezone(timedelta(hours=7)))
  assert policy.expiration_for(created_at) == datetime(2026, 1, 1, 0, 1, 30, tzinfo=timezone.utc)
  assert policy.expiration_for(created_at).tzinfo is timezone.utc


@pytest.mark.parametrize("lifetime", [timedelta(0), timedelta(seconds=-1)])
def test_policy_rejects_nonpositive_lifetime(lifetime: timedelta) -> None:
  from stocklock.application.policies.reservation import ReservationTimePolicy

  with pytest.raises(ValidationException):
    ReservationTimePolicy(lifetime=lifetime)


def test_policy_rejects_naive_time_and_datetime_overflow() -> None:
  from stocklock.application.policies.reservation import ReservationTimePolicy

  policy = ReservationTimePolicy(lifetime=timedelta(seconds=90))
  with pytest.raises(ValidationException):
    policy.expiration_for(datetime(2026, 1, 1))
  with pytest.raises(ValidationException):
    policy.expiration_for(datetime.max.replace(tzinfo=timezone.utc))
