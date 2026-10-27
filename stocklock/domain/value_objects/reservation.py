from dataclasses import dataclass

from stocklock.domain.validation import validate_idempotency_key, validate_quantity


@dataclass(frozen=True, slots=True)
class ReservationQuantity:
  value: int

  def __post_init__(self) -> None:
    validate_quantity(self.value, minimum=1)


@dataclass(frozen=True, slots=True)
class IdempotencyKey:
  value: str

  def __post_init__(self) -> None:
    validate_idempotency_key(self.value)
