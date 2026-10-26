from uuid import UUID

from stocklock.api.v1.schemas.confirmation import ConfirmationResponse
from stocklock.application.commands.confirmation import ConfirmReservationCommand, GetConfirmationCommand
from stocklock.domain.entities.confirmation import Confirmation


def confirm_request_to_command(reservation_id: UUID) -> ConfirmReservationCommand:
  return ConfirmReservationCommand(reservation_id=reservation_id)


def get_request_to_command(reservation_id: UUID) -> GetConfirmationCommand:
  return GetConfirmationCommand(reservation_id=reservation_id)


def domain_to_response(confirmation: Confirmation) -> ConfirmationResponse:
  return ConfirmationResponse(
    id=confirmation.id,
    reservation_id=confirmation.reservation_id,
    created_at=confirmation.created_at,
  )
