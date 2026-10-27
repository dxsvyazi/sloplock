from typing import Self
from uuid import UUID

from pydantic import model_validator

from stocklock.api.v1.schemas.common import (
  APISchema,
  NonBlankString,
  PageRequest,
  ProductName,
  StockQuantity,
  UTCDateTime,
)
from stocklock.shared.exceptions import ValidationException


class CreateProductRequest(APISchema):
  name: ProductName
  sku: NonBlankString
  stock_quantity: StockQuantity


class UpdateProductRequest(APISchema):
  name: ProductName | None = None
  sku: NonBlankString | None = None

  @model_validator(mode="after")
  def validate_changes(self) -> Self:
    if not self.model_fields_set or any(getattr(self, name) is None for name in self.model_fields_set):
      raise ValidationException("Supply at least one product detail; explicit null values are not allowed")

    return self


class CorrectProductStockRequest(APISchema):
  stock_quantity: StockQuantity


class ListProductsRequest(PageRequest):
  pass


class ProductResponse(APISchema):
  id: UUID
  name: ProductName
  sku: NonBlankString
  stock_quantity: StockQuantity
  created_at: UTCDateTime
  updated_at: UTCDateTime | None
