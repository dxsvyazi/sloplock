from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, update

from stocklock.domain.entities.product import Product
from stocklock.domain.ports.repositories.product_repository import IProductRepository, ProductDetailField
from stocklock.domain.value_objects.product import StockDelta
from stocklock.infrastructure.exceptions import EntityUpdateConflict
from stocklock.infrastructure.mappers.product import details_to_values, domain_to_orm, orm_to_domain
from stocklock.infrastructure.models.product import ProductORM
from stocklock.infrastructure.models.reservation import ReservationORM
from stocklock.infrastructure.repositories.base import SessionRepository, paginate
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE, MAX_STOCK_QUANTITY
from stocklock.shared.enums import ProductVisibility, ReservationStatus
from stocklock.shared.utils.timestamps import as_utc


class ProductRepository(SessionRepository, IProductRepository):
  async def find_by_id(self, id: UUID, *, for_update: bool = False) -> Product | None:
    stmt = select(ProductORM).where(ProductORM.id == id)

    if for_update:
      stmt = stmt.with_for_update()

    row = await self.session.scalar(stmt.execution_options(populate_existing=True))

    return orm_to_domain(row) if row is not None else None

  async def find_many(
    self,
    *,
    start_id: UUID | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    visibility: ProductVisibility = ProductVisibility.visible,
  ) -> list[Product]:
    stmt = select(ProductORM)

    if visibility is ProductVisibility.visible:
      stmt = stmt.where(ProductORM.deleted_at.is_(None))
    elif visibility is ProductVisibility.deleted:
      stmt = stmt.where(ProductORM.deleted_at.is_not(None))

    stmt = paginate(stmt, ProductORM, start_id, limit)
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
    result = await self._update(product.id, details_to_values(product, changed_fields), ProductORM.deleted_at.is_(None))

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
      product.id,
      {"stock_quantity": product.stock_quantity.value, "updated_at": product.updated_at},
      ProductORM.deleted_at.is_(None),
    )

    if result is None:
      raise EntityUpdateConflict

    return result

  async def adjust_stock(self, id: UUID, delta: StockDelta) -> Product | None:
    change = delta.value

    return await self._update(
      id,
      {"stock_quantity": ProductORM.stock_quantity + change, "updated_at": func.clock_timestamp()},
      ProductORM.deleted_at.is_(None),
      ProductORM.stock_quantity >= -change,
      # A decrement's mathematical upper bound exceeds int32; valid stock is
      # already bounded by the schema, and asyncpg must receive an int32 value.
      ProductORM.stock_quantity <= min(MAX_STOCK_QUANTITY, MAX_STOCK_QUANTITY - change),
    )

  async def save_deletion(self, product: Product) -> None:
    result = await self._update(product.id, {"deleted_at": product.deleted_at, "updated_at": product.updated_at})

    if result is None:
      raise EntityUpdateConflict

  async def hard_delete(self, id: UUID) -> None:
    await self.session.execute(
      delete(ProductORM).where(ProductORM.id == id).execution_options(synchronize_session=False)
    )

  async def purge_deleted(self, cutoff: datetime, *, limit: int) -> int:
    eligible = (
      ProductORM.deleted_at <= as_utc(cutoff),
      ~select(ReservationORM.id).where(ReservationORM.product_id == ProductORM.id).exists(),
    )

    ids = tuple(
      await self.session.scalars(
        select(ProductORM.id).where(*eligible).order_by(ProductORM.id).limit(limit).with_for_update(skip_locked=True)
      )
    )

    if not ids:
      return 0

    deleted = await self.session.scalars(
      delete(ProductORM)
      .where(ProductORM.id.in_(ids), *eligible)
      .returning(ProductORM.id)
      .execution_options(synchronize_session=False)
    )

    return len(deleted.all())
