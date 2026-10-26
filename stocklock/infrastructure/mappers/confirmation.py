from stocklock.domain.entities.confirmation import Confirmation
from stocklock.infrastructure.models.confirmation import ConfirmationORM
from stocklock.shared.utils.timestamps import as_utc


def orm_to_domain(row: ConfirmationORM) -> Confirmation:
  return Confirmation(id=row.id, reservation_id=row.reservation_id, created_at=as_utc(row.created_at))


def domain_to_orm(confirmation: Confirmation) -> ConfirmationORM:
  return ConfirmationORM(
    id=confirmation.id,
    reservation_id=confirmation.reservation_id,
    created_at=as_utc(confirmation.created_at),
  )
