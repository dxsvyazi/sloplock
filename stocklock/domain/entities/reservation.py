from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Self
from uuid import UUID

from stocklock.domain.entities.base import BaseEntity
from stocklock.domain.errors import IdempotencyConflict, ReservationUnavailable
from stocklock.domain.validation import require_type, validate_id
from stocklock.domain.value_objects.reservation import IdempotencyKey, ReservationQuantity
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import (
  InvalidExpiration,
  InvalidReservationStatus,
  InvalidTransitionTarget,
  ValidationException,
)
from stocklock.shared.utils import utc_now
from stocklock.shared.utils.timestamps import as_utc

_ALLOWED_TRANSITION: Final[frozenset] = frozenset(
  (ReservationStatus.confirmed, ReservationStatus.expired, ReservationStatus.cancelled)
)


@dataclass(frozen=True, slots=True, kw_only=True)
class Reservation(BaseEntity):
  __hash__: Any = None

  product_id: UUID
  quantity: ReservationQuantity
  status: ReservationStatus = ReservationStatus.active
  key: IdempotencyKey
  created_at: datetime = field(default_factory=utc_now)
  expires_at: datetime

  def __post_init__(self) -> None:
    validate_id(self.id)
    validate_id(self.product_id)
    require_type(self.key, IdempotencyKey)
    require_type(self.quantity, ReservationQuantity)
    self.validate_status(self.status)

    created_at, expires_at = as_utc(self.created_at), as_utc(self.expires_at)

    if expires_at <= created_at:
      raise InvalidExpiration

    self._set("created_at", created_at)
    self._set("expires_at", expires_at)

  @classmethod
  def create(cls, *, product_id: UUID, quantity: int, key: str, created_at: datetime, expires_at: datetime) -> Self:
    """Create an active hold using the caller's authoritative clock and lifetime policy."""
    return cls(
      product_id=product_id,
      quantity=ReservationQuantity(quantity),
      key=IdempotencyKey(key),
      created_at=created_at,
      expires_at=expires_at,
    )

  @staticmethod
  def validate_status(status: ReservationStatus) -> None:
    if not isinstance(status, ReservationStatus):
      raise InvalidReservationStatus

  @staticmethod
  def validate_target(target: ReservationStatus) -> None:
    if target not in _ALLOWED_TRANSITION:
      raise InvalidTransitionTarget

  def ensure_new(self) -> None:
    """Insertion is restricted to active holds; hydration may restore terminal states."""
    if self.status is not ReservationStatus.active:
      raise ValidationException("New reservations must be active")

  def ensure_retry(self, quantity: ReservationQuantity) -> None:
    require_type(quantity, ReservationQuantity)

    if self.quantity != quantity:
      raise IdempotencyConflict

  def ensure_confirmed(self) -> None:
    if self.status is not ReservationStatus.confirmed:
      raise ReservationUnavailable("A confirmation requires a confirmed reservation")

  def confirm(self, now: datetime) -> bool:
    if self.status is not ReservationStatus.active or as_utc(now) >= self.expires_at:
      return False

    self._set("status", ReservationStatus.confirmed)

    return True

  def cancel(self) -> bool:
    if self.status is not ReservationStatus.active:
      return False

    self._set("status", ReservationStatus.cancelled)

    return True

  def expire(self, now: datetime) -> bool:
    if self.status is not ReservationStatus.active or as_utc(now) < self.expires_at:
      return False

    self._set("status", ReservationStatus.expired)

    return True
