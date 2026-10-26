from dataclasses import dataclass
from uuid import UUID

from stocklock.domain.entities.product import Product
from stocklock.domain.errors import InsufficientStock, ProductNotFound, StockLimitExceeded
from stocklock.domain.ports.repositories.product_repository import IProductRepository, ProductDetailsPatch
from stocklock.domain.validation import validate_id, validate_page, validate_quantity, validate_text
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE, MAX_PRODUCT_NAME_LEN, MIN_PRODUCT_NAME_LEN
from stocklock.shared.exceptions import ValidationException


def validate_details(details: ProductDetailsPatch) -> None:
  if not details or details.keys() - {"name", "sku"}:
    raise ValidationException("Supply product name and/or SKU only")

  if "name" in details:
    validate_text(details["name"], minimum=MIN_PRODUCT_NAME_LEN, maximum=MAX_PRODUCT_NAME_LEN)

  if "sku" in details:
    validate_text(details["sku"])


@dataclass(slots=True)
class ProductService:
  """Individual inventory operations; the caller owns the transaction."""

  products: IProductRepository

  async def create(self, *, name: str, sku: str, stock_quantity: int) -> Product:
    validate_details({"name": name, "sku": sku})
    validate_quantity(stock_quantity)

    return await self.products.create(Product(name=name, sku=sku, stock_quantity=stock_quantity))

  async def require(self, product_id: UUID, *, for_update: bool = False) -> Product:
    validate_id(product_id)

    product = await self.products.find_by_id(product_id, for_update=for_update)

    if product is None:
      raise ProductNotFound

    return product

  async def list(self, *, start_id: UUID | None = None, limit: int = DEFAULT_PAGE_SIZE) -> list[Product]:
    validate_page(start_id, limit)

    return await self.products.find_many(start_id=start_id, limit=limit)

  async def update_details(self, product_id: UUID, *, details: ProductDetailsPatch) -> Product:
    validate_id(product_id)
    validate_details(details)

    product = await self.products.update_details(product_id, details=details.copy())

    if product is None:
      raise ProductNotFound

    return product

  async def correct_stock(self, product_id: UUID, quantity: int) -> Product:
    validate_id(product_id)
    validate_quantity(quantity)

    product = await self.products.set_stock(product_id, quantity)

    if product is None:
      raise ProductNotFound

    return product

  async def hold_stock(self, product_id: UUID, quantity: int) -> Product:
    validate_id(product_id)
    validate_quantity(quantity, minimum=1)

    product = await self.products.adjust_stock(product_id, -quantity)

    if product is None:
      raise InsufficientStock

    return product

  async def return_stock(self, product_id: UUID, quantity: int) -> Product:
    validate_id(product_id)
    validate_quantity(quantity, minimum=1)

    product = await self.products.adjust_stock(product_id, quantity)

    if product is None:
      raise StockLimitExceeded

    return product
