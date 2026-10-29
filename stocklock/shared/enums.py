from enum import Enum, auto


class ReservationStatus(Enum):
  active = auto()
  confirmed = auto()
  expired = auto()
  cancelled = auto()


class ProductVisibility(Enum):
  visible = "visible"
  deleted = "deleted"
  all = "all"


class DeletionMode(Enum):
  soft = "soft"
  hard = "hard"
