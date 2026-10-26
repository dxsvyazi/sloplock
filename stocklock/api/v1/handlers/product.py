from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from wireup import Injected

from stocklock.api.v1.mappers import product as mapper
from stocklock.api.v1.schemas.product import (
  CorrectProductStockRequest,
  CreateProductRequest,
  ListProductsRequest,
  ProductResponse,
  UpdateProductRequest,
)
from stocklock.application.usecases.products import (
  CorrectProductStockUseCase,
  CreateProductUseCase,
  GetProductUseCase,
  ListProductsUseCase,
  UpdateProductUseCase,
)

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", status_code=201)
async def create_product(request: CreateProductRequest, usecase: Injected[CreateProductUseCase]) -> ProductResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.create_request_to_command(request)))


@router.get("")
async def list_products(
  request: Annotated[ListProductsRequest, Query()],
  usecase: Injected[ListProductsUseCase],
) -> list[ProductResponse]:
  return [mapper.domain_to_response(item) for item in await usecase.execute(mapper.list_request_to_command(request))]


@router.get("/{product_id}")
async def get_product(product_id: UUID, usecase: Injected[GetProductUseCase]) -> ProductResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.get_request_to_command(product_id)))


@router.patch("/{product_id}")
async def update_product(
  product_id: UUID,
  request: UpdateProductRequest,
  usecase: Injected[UpdateProductUseCase],
) -> ProductResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.update_request_to_command(product_id, request)))


@router.patch("/{product_id}/stock")
async def correct_product_stock(
  product_id: UUID,
  request: CorrectProductStockRequest,
  usecase: Injected[CorrectProductStockUseCase],
) -> ProductResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.stock_request_to_command(product_id, request)))
