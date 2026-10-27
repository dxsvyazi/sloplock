from uuid import UUID

from stocklock.api.v1.schemas.reservation import (
  CreateReservationRequest,
  ListProductReservationsRequest,
  ListReservationsRequest,
  ReservationResponse,
)
from stocklock.application.commands.reservation import (
  CancelReservationCommand,
  CreateReservationCommand,
  ExpireReservationCommand,
  GetReservationCommand,
  ListProductReservationsCommand,
  ListReservationsCommand,
)
from stocklock.domain.entities.reservation import Reservation
from stocklock.shared.enums import ReservationStatus


def create_request_to_command(product_id: UUID, request: CreateReservationRequest) -> CreateReservationCommand:
  return CreateReservationCommand(
    product_id=product_id,
    quantity=request.quantity,
    key=request.key,
  )


def get_request_to_command(reservation_id: UUID) -> GetReservationCommand:
  return GetReservationCommand(reservation_id=reservation_id)


def cancel_request_to_command(reservation_id: UUID) -> CancelReservationCommand:
  return CancelReservationCommand(reservation_id=reservation_id)


def expire_request_to_command(reservation_id: UUID) -> ExpireReservationCommand:
  return ExpireReservationCommand(reservation_id=reservation_id)


def list_request_to_command(request: ListReservationsRequest) -> ListReservationsCommand:
  return ListReservationsCommand(
    start_id=request.start_id,
    limit=request.limit,
    status=ReservationStatus[request.status] if request.status is not None else None,
  )


def list_product_request_to_command(
  product_id: UUID,
  request: ListProductReservationsRequest,
) -> ListProductReservationsCommand:
  return ListProductReservationsCommand(
    product_id=product_id,
    start_id=request.start_id,
    limit=request.limit,
    status=ReservationStatus[request.status] if request.status is not None else None,
  )


def domain_to_response(reservation: Reservation) -> ReservationResponse:
  return ReservationResponse(
    id=reservation.id,
    product_id=reservation.product_id,
    quantity=reservation.quantity.value,
    status=reservation.status.name,
    created_at=reservation.created_at,
    expires_at=reservation.expires_at,
  )
