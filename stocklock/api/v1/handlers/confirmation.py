from uuid import UUID

from fastapi import APIRouter
from wireup import Injected

from stocklock.api.v1.mappers import confirmation as mapper
from stocklock.api.v1.schemas.confirmation import ConfirmationResponse
from stocklock.application.usecases.confirmations import ConfirmReservationUseCase, GetConfirmationUseCase

router = APIRouter(prefix="/reservations", tags=["confirmations"])


@router.post("/{reservation_id}/confirm")
async def confirm_reservation(
  reservation_id: UUID, usecase: Injected[ConfirmReservationUseCase]
) -> ConfirmationResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.confirm_request_to_command(reservation_id)))


@router.get("/{reservation_id}/confirmation")
async def get_confirmation(reservation_id: UUID, usecase: Injected[GetConfirmationUseCase]) -> ConfirmationResponse:
  return mapper.domain_to_response(await usecase.execute(mapper.get_request_to_command(reservation_id)))
