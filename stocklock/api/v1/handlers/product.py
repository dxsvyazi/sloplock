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
from stocklock.api.v1.security import AdminCredentials, require_admin
from stocklock.application.commands.product import DeleteProductCommand
from stocklock.application.usecases.product import (
  CorrectProductStockUseCase,
  CreateProductUseCase,
  DeleteProductUseCase,
  GetProductUseCase,
  ListProductsUseCase,
  UpdateProductUseCase,
)
from stocklock.project.configs.admin import AdminSettings
from stocklock.shared.enums import DeletionMode, ProductVisibility

router = APIRouter(prefix="/products", tags=["products"])


@router.post("", status_code=201)
async def create_product(request: CreateProductRequest, usecase: Injected[CreateProductUseCase]) -> ProductResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.create_request_to_command(request)))


@router.get("")
async def list_products(
  request: Annotated[ListProductsRequest, Query()],
  usecase: Injected[ListProductsUseCase],
  credentials: AdminCredentials,
  admin_settings: Injected[AdminSettings],
) -> list[ProductResponse]:
  if request.visibility is not ProductVisibility.visible:
    require_admin(credentials, admin_settings)

  items = await usecase.execute(mapper.list_request_to_command(request))

  return [mapper.domain_to_response(item) for item in items]


@router.get("/{product_id}")
async def get_product(
  product_id: UUID,
  usecase: Injected[GetProductUseCase],
  credentials: AdminCredentials,
  admin_settings: Injected[AdminSettings],
  include_deleted: bool = False,
) -> ProductResponse:
  if include_deleted:
    require_admin(credentials, admin_settings)

  return mapper.domain_to_response(
    await usecase.execute(mapper.get_request_to_command(product_id, include_deleted=include_deleted))
  )


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


@router.delete("/{product_id}", status_code=204)
async def delete_product(
  product_id: UUID,
  usecase: Injected[DeleteProductUseCase],
  credentials: AdminCredentials,
  admin_settings: Injected[AdminSettings],
  mode: DeletionMode = DeletionMode.soft,
) -> None:
  require_admin(credentials, admin_settings)

  await usecase.execute(DeleteProductCommand(product_id=product_id, mode=mode))
