from dataclasses import dataclass

from stocklock.application.policies.product_cleanup import ProductCleanupPolicy
from stocklock.application.ports.clock import IClock
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.domain.ports.repositories.product_repository import IProductRepository
from stocklock.domain.validation import validate_page


@dataclass(slots=True)
class CleanupProductsUseCase:
  uow: IUnitOfWork
  products: IProductRepository
  policy: ProductCleanupPolicy
  clock: IClock

  async def execute(self, *, limit: int = 100) -> int:
    if not self.policy.enabled:
      return 0

    validate_page(limit)

    async with self.uow.begin():
      cutoff = self.policy.cutoff(await self.clock.now())

      assert cutoff is not None

      return await self.products.purge_deleted(cutoff, limit=limit)
