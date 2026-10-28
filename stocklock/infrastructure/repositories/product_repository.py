from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update

from stocklock.domain.entities.product import Product
from stocklock.domain.ports.repositories.product_repository import IProductRepository, ProductDetailField
from stocklock.domain.value_objects.product import StockDelta
from stocklock.infrastructure.exceptions import EntityUpdateConflict
from stocklock.infrastructure.mappers.product import details_to_values, domain_to_orm, orm_to_domain
from stocklock.infrastructure.models.product import ProductORM
from stocklock.infrastructure.models.reservation import ReservationORM
from stocklock.infrastructure.repositories.base import SessionRepository, paginate
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE, MAX_STOCK_QUANTITY
from stocklock.shared.enums import ReservationStatus


class ProductRepository(SessionRepository, IProductRepository):
  async def find_by_id(self, id: UUID, *, for_update: bool = False) -> Product | None:
    stmt = select(ProductORM).where(ProductORM.id == id)

    if for_update:
      stmt = stmt.with_for_update()

    row = await self.session.scalar(stmt.execution_options(populate_existing=True))

    return orm_to_domain(row) if row is not None else None

  async def find_many(self, *, start_id: UUID | None = None, limit: int = DEFAULT_PAGE_SIZE) -> list[Product]:
    stmt = paginate(select(ProductORM), ProductORM, start_id, limit)
    rows = await self.session.scalars(stmt.execution_options(populate_existing=True))

    return [orm_to_domain(row) for row in rows]

  async def create(self, product: Product) -> Product:
    self.session.add(domain_to_orm(product))
    await self.session.flush()

    return product

  async def _update(self, id: UUID, values: dict[str, Any], *conditions) -> Product | None:
    stmt = (
      update(ProductORM)
      .where(ProductORM.id == id, *conditions)
      .values(**values)
      .returning(ProductORM)
      .execution_options(synchronize_session=False, populate_existing=True)
    )

    row = await self.session.scalar(stmt)

    return row and orm_to_domain(row)

  async def save_details(self, product: Product, *, changed_fields: frozenset[ProductDetailField]) -> Product:
    result = await self._update(product.id, details_to_values(product, changed_fields))

    if result is None:
      raise EntityUpdateConflict

    return result

  async def active_held_quantity(self, id: UUID) -> int:
    # Separate statement after the lock: READ COMMITTED must see holds inserted
    # by a transaction we waited for. Never lock reservations in this order.
    held = await self.session.scalar(
      select(func.coalesce(func.sum(ReservationORM.quantity), 0)).where(
        ReservationORM.product_id == id, ReservationORM.status == ReservationStatus.active
      )
    )

    assert held is not None

    return held

  async def save_stock(self, product: Product) -> Product:
    result = await self._update(
      product.id, {"stock_quantity": product.stock_quantity.value, "updated_at": product.updated_at}
    )

    if result is None:
      raise EntityUpdateConflict

    return result

  async def adjust_stock(self, id: UUID, delta: StockDelta) -> Product | None:
    change = delta.value

    return await self._update(
      id,
      {"stock_quantity": ProductORM.stock_quantity + change, "updated_at": func.clock_timestamp()},
      ProductORM.stock_quantity >= -change,
      # A decrement's mathematical upper bound exceeds int32; valid stock is
      # already bounded by the schema, and asyncpg must receive an int32 value.
      ProductORM.stock_quantity <= min(MAX_STOCK_QUANTITY, MAX_STOCK_QUANTITY - change),
    )
