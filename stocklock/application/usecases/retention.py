from dataclasses import dataclass

from stocklock.application.policies.retention import RetentionPolicy
from stocklock.application.ports.clock import IClock
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository
from stocklock.domain.validation import validate_page


@dataclass(slots=True)
class CleanupRetentionUseCase:
  uow: IUnitOfWork
  reservations: IReservationRepository
  policy: RetentionPolicy
  clock: IClock

  async def execute(self, *, limit: int = 100) -> int:
    validate_page(limit)
    if not self.policy.enabled:
      return 0

    async with self.uow.begin():
      return await self.reservations.purge_terminal(self.policy.cutoffs(await self.clock.now()), limit=limit)
