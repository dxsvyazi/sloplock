from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self
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
    if target not in (ReservationStatus.confirmed, ReservationStatus.expired, ReservationStatus.cancelled):
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

  def can_transition(self, target: ReservationStatus, now: datetime) -> bool:
    self.validate_target(target)

    now = as_utc(now)

    if self.status is not ReservationStatus.active:
      return False

    if target is ReservationStatus.confirmed:
      return now < self.expires_at

    if target is ReservationStatus.expired:
      return now >= self.expires_at

    return True

  def transition(self, target: ReservationStatus, now: datetime) -> bool:
    if not self.can_transition(target, now):
      return False

    self._set("status", target)

    return True

  def confirm(self, now: datetime) -> None:
    if not self.transition(ReservationStatus.confirmed, now):
      raise ReservationUnavailable("Reservation is no longer active and unexpired")

  def cancel(self, now: datetime) -> bool:
    return self.transition(ReservationStatus.cancelled, now)

  def expire(self, now: datetime) -> bool:
    return self.transition(ReservationStatus.expired, now)
