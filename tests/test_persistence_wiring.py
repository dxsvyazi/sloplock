from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.application.ports.uow import IUnitOfWork
from stocklock.application.usecases.confirmations import ConfirmReservationUseCase, GetConfirmationUseCase
from stocklock.application.usecases.product import (
  CorrectProductStockUseCase,
  CreateProductUseCase,
  GetProductUseCase,
  ListProductsUseCase,
  UpdateProductUseCase,
)
from stocklock.application.usecases.reservation import (
  CancelReservationUseCase,
  ExpireReservationUseCase,
  GetReservationUseCase,
  ListProductReservationsUseCase,
  ListReservationsUseCase,
  ReserveProductUseCase,
)
from stocklock.domain.ports.repositories.confirmation_repository import IConfirmationRepository
from stocklock.domain.ports.repositories.product_repository import IProductRepository
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository
from stocklock.domain.services.confirmation_service import ConfirmationService
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.infrastructure.session_manager import SessionManager


async def test_container_wires_services_and_individual_flows_to_one_transaction_context():
  from stocklock.project.persistence import create_persistence_container

  container = create_persistence_container(async_sessionmaker())
  try:
    async with container.enter_scope() as scope:
      manager = await scope.get(SessionManager)
      uow = await scope.get(IUnitOfWork)
      services = {
        "products": await scope.get(ProductService),
        "reservations": await scope.get(ReservationService),
        "confirmations": await scope.get(ConfirmationService),
      }
      for name, port in (
        ("products", IProductRepository),
        ("reservations", IReservationRepository),
        ("confirmations", IConfirmationRepository),
      ):
        repo = await scope.get(port)
        assert getattr(services[name], name) is repo
        assert repo.session_manager is manager
      for cls in (
        CreateProductUseCase,
        GetProductUseCase,
        ListProductsUseCase,
        UpdateProductUseCase,
        CorrectProductStockUseCase,
        ReserveProductUseCase,
        GetReservationUseCase,
        ListReservationsUseCase,
        ListProductReservationsUseCase,
        CancelReservationUseCase,
        ExpireReservationUseCase,
        ConfirmReservationUseCase,
        GetConfirmationUseCase,
      ):
        flow = await scope.get(cls)
        assert flow.uow is uow
        for name, service in services.items():
          if hasattr(flow, name):
            assert getattr(flow, name) is service
      async with uow.begin():
        assert manager.get_session(raises=True).in_transaction()
  finally:
    await container.close()
