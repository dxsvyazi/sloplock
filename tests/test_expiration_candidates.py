from datetime import timedelta
from uuid import UUID

from stocklock.application.commands.common import PageCommand
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
from stocklock.shared.enums import ReservationStatus
from tests.service_doubles import Reservations, Store


async def test_due_candidates_include_exact_deadline_and_page_by_id():
  from stocklock.application.usecases.expiration import ListDueReservationsUseCase

  store = Store()
  for number, offset, status in (
    (1, -1, ReservationStatus.active),
    (2, 0, ReservationStatus.active),
    (3, 1, ReservationStatus.active),
    (4, -1, ReservationStatus.cancelled),
  ):
    item = Reservation(
      id=UUID(int=number),
      product_id=UUID(int=10),
      quantity=1,
      key=str(number),
      created_at=store.now - timedelta(minutes=1),
      expires_at=store.now + timedelta(seconds=offset),
      status=status,
    )
    store.reservations[item.id] = item
  flow = ListDueReservationsUseCase(store, ReservationService(Reservations(store)))
  assert await flow.execute(PageCommand(limit=1)) == [UUID(int=1)]
  assert await flow.execute(PageCommand(start_id=UUID(int=1), limit=5)) == [UUID(int=2)]
  assert not store.active


async def test_postgres_due_candidates_filter_status_deadline_and_cursor(database):
  from stocklock.application.usecases.expiration import ListDueReservationsUseCase
  from stocklock.domain.entities.product import Product
  from stocklock.infrastructure.repositories.product_repository import ProductRepository

  reservations = ReservationRepository(database.manager)
  products = ProductRepository(database.manager)
  async with database.uow.begin():
    product = await products.create(Product(name="Item", sku="item", stock_quantity=0))
    now = await reservations.current_time()
    ids = []
    for number, offset in ((1, -1), (2, -1), (3, 3600)):
      item = await reservations.create(
        Reservation(
          id=UUID(int=number),
          product_id=product.id,
          quantity=1,
          key=str(number),
          created_at=now - timedelta(minutes=1),
          expires_at=now + timedelta(seconds=offset),
        )
      )
      ids.append(item.id)
    await reservations.transition(ids[1], ReservationStatus.cancelled)
  flow = ListDueReservationsUseCase(database.uow, ReservationService(reservations))
  assert await flow.execute(PageCommand(limit=1)) == [ids[0]]
  assert await flow.execute(PageCommand(start_id=ids[0])) == []
