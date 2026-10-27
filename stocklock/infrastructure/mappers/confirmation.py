from stocklock.domain.entities.confirmation import Confirmation
from stocklock.infrastructure.models.confirmation import ConfirmationORM


def orm_to_domain(row: ConfirmationORM) -> Confirmation:
  return Confirmation(id=row.id, reservation_id=row.reservation_id, created_at=row.created_at)


def domain_to_orm(confirmation: Confirmation) -> ConfirmationORM:
  return ConfirmationORM(
    id=confirmation.id,
    reservation_id=confirmation.reservation_id,
    created_at=confirmation.created_at,
  )
