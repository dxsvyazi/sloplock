from typing import Any, cast
from uuid import UUID

from sqlalchemy import func, select, update

from stocklock.domain.entities.product import Product
from stocklock.domain.inventory import validate_stock_return_capacity
from stocklock.domain.ports.repositories.product_repository import IProductRepository, ProductDetailsPatch
from stocklock.infrastructure.mappers.product import domain_to_orm, orm_to_domain
from stocklock.infrastructure.models.product import ProductORM
from stocklock.infrastructure.models.reservation import ReservationORM
from stocklock.infrastructure.repositories.base import SessionRepository, paginate
from stocklock.shared.constraints import (
  DEFAULT_PAGE_SIZE,
  MAX_PRODUCT_NAME_LEN,
  MAX_STOCK_QUANTITY,
  MIN_PRODUCT_NAME_LEN,
)
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import MissingProductDetails, ValidationException


def validate_stock(value: int) -> None:
  if type(value) is not int or not 0 <= value <= MAX_STOCK_QUANTITY:
    raise ValidationException("Stock must be a nonnegative database integer")


def validate_stock_delta(delta: int) -> None:
  if type(delta) is not int or not -MAX_STOCK_QUANTITY <= delta <= MAX_STOCK_QUANTITY:
    raise ValidationException("Stock delta must fit the stock range")


def validate_update_details(details: ProductDetailsPatch) -> None:
  if (name := details.get("name")) is not None:
    if not isinstance(name, str) or not MIN_PRODUCT_NAME_LEN <= len(name.strip()) <= MAX_PRODUCT_NAME_LEN:
      raise ValidationException("Invalid product name")

  if (sku := details.get("sku")) is not None:
    if not isinstance(sku, str) or not sku.strip():
      raise ValidationException("Invalid product SKU")

  if not details:
    raise MissingProductDetails


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
    validate_stock(product.stock_quantity)

    row = domain_to_orm(product)

    self.session.add(row)
    await self.session.flush()

    return orm_to_domain(row)

  async def _update(self, id: UUID, values: dict[str, Any], *conditions) -> Product | None:
    stmt = (
      update(ProductORM)
      .where(ProductORM.id == id, *conditions)
      .values(**values, updated_at=func.clock_timestamp())
      .returning(ProductORM)
      .execution_options(synchronize_session=False, populate_existing=True)
    )

    row = await self.session.scalar(stmt)

    return row and orm_to_domain(row)

  async def update_details(self, id: UUID, *, details: ProductDetailsPatch) -> Product | None:
    validate_update_details(details)

    if details.get("name"):
      details["name"] = details["name"].strip()  # type: ignore

    if details.get("sku"):
      details["sku"] = details["sku"].strip()  # type: ignore

    return await self._update(id, cast(dict[str, Any], details))

  async def set_stock(self, id: UUID, quantity: int) -> Product | None:
    validate_stock(quantity)

    if await self.find_by_id(id, for_update=True) is None:
      return None

    # Separate statement after the lock: READ COMMITTED must see holds inserted
    # by a transaction we waited for. Never lock reservations in this order.
    held = await self.session.scalar(
      select(func.coalesce(func.sum(ReservationORM.quantity), 0)).where(
        ReservationORM.product_id == id, ReservationORM.status == ReservationStatus.active
      )
    )

    assert held is not None

    validate_stock_return_capacity(quantity, held)

    return await self._update(id, {"stock_quantity": quantity})

  async def adjust_stock(self, id: UUID, delta: int) -> Product | None:
    validate_stock_delta(delta)

    # Test bounds before addition, so even the predicate cannot overflow int4.
    return await self._update(
      id,
      {"stock_quantity": ProductORM.stock_quantity + delta},
      ProductORM.stock_quantity >= max(0, -delta),
      ProductORM.stock_quantity <= min(MAX_STOCK_QUANTITY, MAX_STOCK_QUANTITY - delta),
    )
