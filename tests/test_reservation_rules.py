from datetime import timedelta
from uuid import uuid4

import pytest

from stocklock.domain.entities.reservation import Reservation
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.utils import utc_now


@pytest.mark.parametrize("status", list(ReservationStatus))
@pytest.mark.parametrize(
  "target", [ReservationStatus.confirmed, ReservationStatus.expired, ReservationStatus.cancelled]
)
@pytest.mark.parametrize("seconds", [-1, 0, 1])
def test_reservation_terminal_eligibility(status, target, seconds):
  from stocklock.domain.services.reservation_service import can_transition

  now = utc_now()
  item = Reservation(
    product_id=uuid4(),
    quantity=1,
    status=status,
    key="test",
    expires_at=now + timedelta(seconds=seconds),
  )
  expected = status is ReservationStatus.active and (
    target is ReservationStatus.cancelled
    or (target is ReservationStatus.confirmed and seconds == 1)
    or (target is ReservationStatus.expired and seconds in (-1, 0))
  )
  assert can_transition(item, target, now) is expected
