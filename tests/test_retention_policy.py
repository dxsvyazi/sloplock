from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from stocklock.project.configs.time_policy import TimePolicySettings
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException


def test_cutoffs_use_each_enabled_status_and_normalize_utc():
  from stocklock.application.policies.retention import RetentionPolicy

  policy = RetentionPolicy(expired=timedelta(days=30), cancelled=None, confirmed=timedelta(days=1))
  now = datetime(2026, 10, 28, 7, tzinfo=timezone(timedelta(hours=7)))
  assert policy.enabled
  assert policy.cutoffs(now) == {
    ReservationStatus.expired: datetime(2026, 9, 28, tzinfo=timezone.utc),
    ReservationStatus.confirmed: datetime(2026, 10, 27, tzinfo=timezone.utc),
  }


def test_all_disabled_has_no_cutoffs():
  from stocklock.application.policies.retention import RetentionPolicy

  policy = RetentionPolicy(expired=None, cancelled=None, confirmed=None)
  assert not policy.enabled
  assert policy.cutoffs(datetime(2026, 10, 28, tzinfo=timezone.utc)) == {}


@pytest.mark.parametrize("duration", [timedelta(0), timedelta(seconds=-1), 1, True])
def test_policy_rejects_nonpositive_or_untyped_durations(duration):
  from stocklock.application.policies.retention import RetentionPolicy

  with pytest.raises(ValidationException):
    RetentionPolicy(expired=duration, cancelled=None, confirmed=None)


def test_policy_rejects_naive_time_and_handles_underflow():
  from stocklock.application.policies.retention import RetentionPolicy

  policy = RetentionPolicy(expired=timedelta(days=30), cancelled=None, confirmed=None)
  with pytest.raises(ValidationException):
    policy.cutoffs(datetime(2026, 1, 1))
  assert policy.cutoffs(datetime.min.replace(tzinfo=timezone.utc)) == {
    ReservationStatus.expired: datetime.min.replace(tzinfo=timezone.utc)
  }


def test_retention_worker_defaults_and_disable_settings():
  settings = TimePolicySettings(
    EXPIRED_RESERVATION_RETENTION_SECONDS=0,
    CANCELLED_RESERVATION_RETENTION_SECONDS=0,
    CONFIRMATION_RETENTION_SECONDS=0,
    _env_file=None,
  )
  assert settings.expired_reservation_retention is None
  assert settings.cancelled_reservation_retention is None
  assert settings.confirmation_retention is None
  assert settings.RETENTION_BATCH_SIZE == 100
  assert settings.RETENTION_MAX_BATCHES == 100
  assert settings.retention_operation_timeout == timedelta(seconds=30)


@pytest.mark.parametrize(
  "name,value",
  [
    ("RETENTION_BATCH_SIZE", 0),
    ("RETENTION_BATCH_SIZE", 101),
    ("RETENTION_MAX_BATCHES", 0),
    ("RETENTION_OPERATION_TIMEOUT_SECONDS", 0),
    ("RETENTION_MAX_BATCHES", True),
    ("RETENTION_BATCH_SIZE", 1.5),
  ],
)
def test_invalid_retention_worker_settings(name, value):
  with pytest.raises(ValidationError):
    TimePolicySettings(**{name: value}, _env_file=None)
