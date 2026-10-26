from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from uuid6 import uuid7

from stocklock.shared.enums import ReservationStatus
from stocklock.shared.utils import utc_now


@dataclass(slots=True, kw_only=True)
class Reservation:
  id: UUID = field(default_factory=uuid7)
  product_id: UUID
  quantity: int
  status: ReservationStatus = ReservationStatus.active
  key: str

  created_at: datetime = field(default_factory=utc_now)
  expires_at: datetime
