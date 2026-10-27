from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from stocklock.domain.entities.base import BaseEntity
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.validation import validate_id
from stocklock.shared.utils import utc_now
from stocklock.shared.utils.timestamps import as_utc


@dataclass(frozen=True, slots=True, kw_only=True)
class Confirmation(BaseEntity):
  reservation_id: UUID
  created_at: datetime = field(default_factory=utc_now)

  def __post_init__(self) -> None:
    validate_id(self.id)
    validate_id(self.reservation_id)

    self._set("created_at", as_utc(self.created_at))

  @classmethod
  def from_reservation(cls, reservation: Reservation) -> "Confirmation":
    reservation.ensure_confirmed()

    return cls(reservation_id=reservation.id)
