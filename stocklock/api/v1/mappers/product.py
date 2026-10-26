from uuid import UUID

from stocklock.api.v1.schemas.product import (
  CorrectProductStockRequest,
  CreateProductRequest,
  ListProductsRequest,
  ProductResponse,
  UpdateProductRequest,
)
from stocklock.application.commands.product import (
  CorrectProductStockCommand,
  CreateProductCommand,
  GetProductCommand,
  ListProductsCommand,
  UpdateProductCommand,
)
from stocklock.domain.entities.product import Product


def create_request_to_command(request: CreateProductRequest) -> CreateProductCommand:
  return CreateProductCommand(name=request.name, sku=request.sku, stock_quantity=request.stock_quantity)


def get_request_to_command(product_id: UUID) -> GetProductCommand:
  return GetProductCommand(product_id=product_id)


def update_request_to_command(product_id: UUID, request: UpdateProductRequest) -> UpdateProductCommand:
  return UpdateProductCommand(product_id=product_id, name=request.name, sku=request.sku)


def stock_request_to_command(product_id: UUID, request: CorrectProductStockRequest) -> CorrectProductStockCommand:
  return CorrectProductStockCommand(product_id=product_id, stock_quantity=request.stock_quantity)


def list_request_to_command(request: ListProductsRequest) -> ListProductsCommand:
  return ListProductsCommand(start_id=request.start_id, limit=request.limit)


def domain_to_response(product: Product) -> ProductResponse:
  return ProductResponse(
    id=product.id,
    name=product.name,
    sku=product.sku,
    stock_quantity=product.stock_quantity,
    created_at=product.created_at,
    updated_at=product.updated_at,
  )
