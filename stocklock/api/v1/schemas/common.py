from datetime import timezone
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator, AwareDatetime, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from stocklock.shared.constraints import (
  DEFAULT_PAGE_SIZE,
  MAX_PAGE_SIZE,
  MAX_PRODUCT_NAME_LEN,
  MAX_STOCK_QUANTITY,
  MIN_PRODUCT_NAME_LEN,
)

ProductName = Annotated[
  str, StringConstraints(strip_whitespace=True, min_length=MIN_PRODUCT_NAME_LEN, max_length=MAX_PRODUCT_NAME_LEN)
]
NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
StockQuantity = Annotated[int, Field(strict=True, ge=0, le=MAX_STOCK_QUANTITY)]
ReservationQuantity = Annotated[int, Field(strict=True, gt=0, le=MAX_STOCK_QUANTITY)]
StatusName = Literal["active", "confirmed", "expired", "cancelled"]
UTCDateTime = Annotated[AwareDatetime, AfterValidator(lambda value: value.astimezone(timezone.utc))]


class APISchema(BaseModel):
  model_config = ConfigDict(extra="forbid", frozen=True)


class PageRequest(APISchema):
  start_id: UUID | None = None
  limit: Annotated[int, Field(strict=True, ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE

  @field_validator("limit", mode="before")
  @classmethod
  def parse_query_limit(cls, value: object) -> object:
    # Query parameters arrive as strings; body quantities remain strict integers.
    if isinstance(value, str):
      try:
        return int(value)
      except ValueError:
        pass

    return value
