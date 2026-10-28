"""Exercise snapshot saves directly inside a caller-owned test transaction."""

from uuid import UUID

from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.ports.repositories.product_repository import (
  IProductRepository,
  ProductDetailsSnapshot,
  ProductStockSnapshot,
)
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository, ReservationSnapshot
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.domain.value_objects.product import SKU, ProductName, StockQuantity
from stocklock.shared.enums import ReservationStatus


async def update_details(
  products: IProductRepository | ProductService, id: UUID, *, details: dict[str, str]
) -> Product | None:
  service = products if isinstance(products, ProductService) else ProductService(products)
  product = await service.products.find_by_id(id, for_update=True)
  if product is None:
    return None
  original = ProductDetailsSnapshot.capture(product)
  values = {
    name: ProductName(value) if name == "name" else SKU(value) if name == "sku" else value
    for name, value in details.items()
  }
  product.update_details(values)
  return await service.save_details(product, original=original)


async def set_stock(products: IProductRepository | ProductService, id: UUID, quantity: int) -> Product | None:
  service = products if isinstance(products, ProductService) else ProductService(products)
  product = await service.products.find_by_id(id, for_update=True)
  if product is None:
    return None
  original = ProductStockSnapshot.capture(product)
  product.correct_stock(StockQuantity(quantity), held_quantity=await service.active_held_quantity(id))
  return await service.save_stock(product, original=original)


async def transition(
  reservations: IReservationRepository | ReservationService, id: UUID, target: ReservationStatus
) -> Reservation | None:
  service = reservations if isinstance(reservations, ReservationService) else ReservationService(reservations)
  reservation = await service.get(id, for_update=True)
  if reservation is None:
    return None
  original = ReservationSnapshot.capture(reservation)
  Reservation.validate_target(target)
  if target is ReservationStatus.cancelled:
    changed = reservation.cancel()
  elif target is ReservationStatus.confirmed:
    changed = reservation.confirm(await service.current_time())
  else:
    changed = reservation.expire(await service.current_time())
  if not changed:
    return None
  return await service.save_transition(reservation, original=original)
