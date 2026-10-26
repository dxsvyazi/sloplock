from stocklock.domain.entities.product import Product
from stocklock.infrastructure.models.product import ProductORM
from stocklock.shared.utils.timestamps import as_utc


def orm_to_domain(row: ProductORM) -> Product:
  return Product(
    id=row.id,
    name=row.name,
    sku=row.sku,
    stock_quantity=row.stock_quantity,
    created_at=as_utc(row.created_at),
    updated_at=as_utc(row.updated_at) if row.updated_at is not None else None,
  )


def domain_to_orm(product: Product) -> ProductORM:
  """Build an insert model. Stock updates require repository concurrency control."""
  return ProductORM(
    id=product.id,
    name=product.name,
    sku=product.sku,
    stock_quantity=product.stock_quantity,
    created_at=as_utc(product.created_at),
    updated_at=as_utc(product.updated_at) if product.updated_at is not None else None,
  )
