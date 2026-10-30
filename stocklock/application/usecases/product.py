from dataclasses import dataclass

from stocklock.application.commands.product import (
  CorrectProductStockCommand,
  CreateProductCommand,
  DeleteProductCommand,
  GetProductCommand,
  ListProductsCommand,
  UpdateProductCommand,
)
from stocklock.application.ports.clock import IClock
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.domain.entities.product import Product, ProductDetailsPatch
from stocklock.domain.ports.repositories.product_repository import ProductDetailsSnapshot, ProductStockSnapshot
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.value_objects.product import SKU, ProductName, StockQuantity


@dataclass(slots=True)
class CreateProductUseCase:
  uow: IUnitOfWork
  products: ProductService

  async def execute(self, command: CreateProductCommand) -> Product:
    async with self.uow.begin():
      return await self.products.create(
        Product.create(name=command.name, sku=command.sku, stock_quantity=command.stock_quantity)
      )


@dataclass(slots=True)
class GetProductUseCase:
  uow: IUnitOfWork
  products: ProductService

  async def execute(self, command: GetProductCommand) -> Product:
    async with self.uow.begin():
      return await self.products.require(command.product_id, include_deleted=command.include_deleted)


@dataclass(slots=True)
class ListProductsUseCase:
  uow: IUnitOfWork
  products: ProductService

  async def execute(self, command: ListProductsCommand) -> list[Product]:
    async with self.uow.begin():
      return await self.products.list(start_id=command.start_id, limit=command.limit, visibility=command.visibility)


@dataclass(slots=True)
class UpdateProductUseCase:
  uow: IUnitOfWork
  products: ProductService

  async def execute(self, command: UpdateProductCommand) -> Product:
    details: ProductDetailsPatch = {}

    if command.name is not None:
      details["name"] = ProductName(command.name)

    if command.sku is not None:
      details["sku"] = SKU(command.sku)

    async with self.uow.begin():
      product = await self.products.require(command.product_id, for_update=True)

      original = ProductDetailsSnapshot.capture(product)

      product.update_details(details)

      return await self.products.save_details(product, original=original)


@dataclass(slots=True)
class CorrectProductStockUseCase:
  uow: IUnitOfWork
  products: ProductService

  async def execute(self, command: CorrectProductStockCommand) -> Product:
    async with self.uow.begin():
      product = await self.products.require(command.product_id, for_update=True)

      original = ProductStockSnapshot.capture(product)

      product.correct_stock(
        StockQuantity(command.stock_quantity), held_quantity=await self.products.active_held_quantity(product.id)
      )

      return await self.products.save_stock(product, original=original)


@dataclass(slots=True)
class DeleteProductUseCase:
  uow: IUnitOfWork
  products: ProductService
  clock: IClock

  async def execute(self, command: DeleteProductCommand) -> None:
    async with self.uow.begin():
      product = await self.products.require(command.product_id, for_update=True, include_deleted=True)

      await self.products.delete(product, mode=command.mode, at=await self.clock.now())
