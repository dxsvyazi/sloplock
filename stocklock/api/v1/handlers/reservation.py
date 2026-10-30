from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from wireup import Injected

from stocklock.api.v1.mappers import reservation as mapper
from stocklock.api.v1.schemas.reservation import (
  CreateReservationRequest,
  ListProductReservationsRequest,
  ListReservationsRequest,
  ReservationResponse,
)
from stocklock.api.v1.security import AdminCredentials, require_admin
from stocklock.application.usecases.reservation import (
  CancelReservationUseCase,
  ExpireReservationUseCase,
  GetReservationUseCase,
  ListProductReservationsUseCase,
  ListReservationsUseCase,
  ReserveProductUseCase,
)
from stocklock.project.configs.admin import AdminSettings
from stocklock.shared.enums import ProductVisibility

router = APIRouter(tags=["reservations"])


@router.post("/products/{product_id}/reservations", status_code=201)
async def reserve_product(
  product_id: UUID,
  request: CreateReservationRequest,
  usecase: Injected[ReserveProductUseCase],
) -> ReservationResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.create_request_to_command(product_id, request)))


@router.get("/products/{product_id}/reservations")
async def list_product_reservations(
  product_id: UUID,
  request: Annotated[ListProductReservationsRequest, Query()],
  usecase: Injected[ListProductReservationsUseCase],
  credentials: AdminCredentials,
  admin_settings: Injected[AdminSettings],
) -> list[ReservationResponse]:
  if request.product_visibility is ProductVisibility.deleted:
    require_admin(credentials, admin_settings)

  items = await usecase.execute(mapper.list_product_request_to_command(product_id, request))

  return [mapper.domain_to_response(item) for item in items]


@router.get("/reservations")
async def list_reservations(
  request: Annotated[ListReservationsRequest, Query()],
  usecase: Injected[ListReservationsUseCase],
  credentials: AdminCredentials,
  admin_settings: Injected[AdminSettings],
) -> list[ReservationResponse]:
  if request.product_visibility is ProductVisibility.deleted:
    require_admin(credentials, admin_settings)

  items = await usecase.execute(mapper.list_request_to_command(request))

  return [mapper.domain_to_response(item) for item in items]


@router.get("/reservations/{reservation_id}")
async def get_reservation(reservation_id: UUID, usecase: Injected[GetReservationUseCase]) -> ReservationResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.get_request_to_command(reservation_id)))


@router.post("/reservations/{reservation_id}/cancel")
async def cancel_reservation(reservation_id: UUID, usecase: Injected[CancelReservationUseCase]) -> ReservationResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.cancel_request_to_command(reservation_id)))


@router.post("/reservations/{reservation_id}/expire")
async def expire_reservation(reservation_id: UUID, usecase: Injected[ExpireReservationUseCase]) -> ReservationResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.expire_request_to_command(reservation_id)))
