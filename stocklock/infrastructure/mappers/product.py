from typing import Any

from stocklock.domain.entities.product import Product
from stocklock.domain.ports.repositories.product_repository import ProductDetailField
from stocklock.domain.value_objects.product import SKU, ProductName, StockQuantity
from stocklock.infrastructure.models.product import ProductORM
from stocklock.shared.exceptions import ValidationException


def details_to_values(product: Product, changed_fields: frozenset[ProductDetailField]) -> dict[str, Any]:
  if not changed_fields or changed_fields - {"name", "sku"}:
    raise ValidationException("Supply changed product detail fields only")

  return {name: getattr(product, name).value for name in changed_fields} | {"updated_at": product.updated_at}


def orm_to_domain(row: ProductORM) -> Product:
  return Product(
    id=row.id,
    name=ProductName(row.name),
    sku=SKU(row.sku),
    stock_quantity=StockQuantity(row.stock_quantity),
    created_at=row.created_at,
    updated_at=row.updated_at,
    deleted_at=row.deleted_at,
  )


def domain_to_orm(product: Product) -> ProductORM:
  """Build an insert model. Stock updates require repository concurrency control."""
  return ProductORM(
    id=product.id,
    name=product.name.value,
    sku=product.sku.value,
    stock_quantity=product.stock_quantity.value,
    created_at=product.created_at,
    updated_at=product.updated_at,
    deleted_at=product.deleted_at,
  )
