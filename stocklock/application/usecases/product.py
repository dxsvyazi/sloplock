from dataclasses import dataclass

from stocklock.application.commands.product import (
  CorrectProductStockCommand,
  CreateProductCommand,
  GetProductCommand,
  ListProductsCommand,
  UpdateProductCommand,
)
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.domain.entities.product import Product
from stocklock.domain.ports.repositories.product_repository import ProductDetailsPatch
from stocklock.domain.services.product_service import ProductService


@dataclass(slots=True)
class CreateProductUseCase:
  uow: IUnitOfWork
  products: ProductService

  async def execute(self, command: CreateProductCommand) -> Product:
    async with self.uow.begin():
      return await self.products.create(name=command.name, sku=command.sku, stock_quantity=command.stock_quantity)


@dataclass(slots=True)
class GetProductUseCase:
  uow: IUnitOfWork
  products: ProductService

  async def execute(self, command: GetProductCommand) -> Product:
    async with self.uow.begin():
      return await self.products.require(command.product_id)


@dataclass(slots=True)
class ListProductsUseCase:
  uow: IUnitOfWork
  products: ProductService

  async def execute(self, command: ListProductsCommand) -> list[Product]:
    async with self.uow.begin():
      return await self.products.list(start_id=command.start_id, limit=command.limit)


@dataclass(slots=True)
class UpdateProductUseCase:
  uow: IUnitOfWork
  products: ProductService

  async def execute(self, command: UpdateProductCommand) -> Product:
    details: ProductDetailsPatch = {}

    if command.name is not None:
      details["name"] = command.name

    if command.sku is not None:
      details["sku"] = command.sku

    async with self.uow.begin():
      return await self.products.update_details(command.product_id, details=details)


@dataclass(slots=True)
class CorrectProductStockUseCase:
  uow: IUnitOfWork
  products: ProductService

  async def execute(self, command: CorrectProductStockCommand) -> Product:
    async with self.uow.begin():
      return await self.products.correct_stock(command.product_id, command.stock_quantity)
