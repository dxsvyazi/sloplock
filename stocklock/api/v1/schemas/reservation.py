from typing import Annotated, Self
from uuid import UUID

from pydantic import AfterValidator, StringConstraints, model_validator

from stocklock.api.v1.schemas.common import (
  APISchema,
  PageRequest,
  ReservationQuantity,
  StatusName,
  UTCDateTime,
)
from stocklock.domain.validation import validate_idempotency_key
from stocklock.shared.constraints import MAX_IDEMPOTENCY_KEY_LENGTH
from stocklock.shared.exceptions import InvalidExpiration


IdempotencyKey = Annotated[
  str,
  StringConstraints(min_length=1, max_length=MAX_IDEMPOTENCY_KEY_LENGTH),
  AfterValidator(validate_idempotency_key),
]


class CreateReservationRequest(APISchema):
  quantity: ReservationQuantity
  key: IdempotencyKey


class ListReservationsRequest(PageRequest):
  status: StatusName | None = None


class ListProductReservationsRequest(ListReservationsRequest):
  pass


class ReservationResponse(APISchema):
  id: UUID
  product_id: UUID
  quantity: ReservationQuantity
  status: StatusName
  created_at: UTCDateTime
  expires_at: UTCDateTime

  @model_validator(mode="after")
  def validate_expiration(self) -> Self:

    if self.expires_at <= self.created_at:
      raise InvalidExpiration

    return self
