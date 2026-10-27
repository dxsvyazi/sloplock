from stocklock.domain.entities.reservation import Reservation
from stocklock.infrastructure.models.reservation import ReservationORM
from stocklock.shared.enums import ReservationStatus


def orm_to_domain(row: ReservationORM) -> Reservation:
  return Reservation(
    id=row.id,
    product_id=row.product_id,
    quantity=row.quantity,
    status=ReservationStatus(row.status),
    key=row.key,
    created_at=row.created_at,
    expires_at=row.expires_at,
  )


def domain_to_orm(reservation: Reservation) -> ReservationORM:
  """Build an insert model. Terminal transitions belong to conditional repository operations."""
  return ReservationORM(
    id=reservation.id,
    product_id=reservation.product_id,
    quantity=reservation.quantity,
    status=reservation.status.value,
    key=reservation.key,
    created_at=reservation.created_at,
    expires_at=reservation.expires_at,
  )
