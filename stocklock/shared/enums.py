from enum import Enum, auto


class ReservationStatus(Enum):
  active = auto()
  confirmed = auto()
  expired = auto()
  cancelled = auto()
