"""Application composition root and dependency lifetimes."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from wireup import AsyncContainer, create_async_container, injectable

from stocklock.application.policies.reservation import ReservationTimePolicy
from stocklock.application.policies.product_cleanup import ProductCleanupPolicy
from stocklock.application.usecases.product_cleanup import CleanupProductsUseCase
from stocklock.application.policies.retention import RetentionPolicy
from stocklock.application.ports.clock import IClock
from stocklock.application.ports.uow import IUnitOfWork
from stocklock.application.usecases.confirmations import ConfirmReservationUseCase, GetConfirmationUseCase
from stocklock.application.usecases.expiration import ExpireReservationsUseCase, ListDueReservationsUseCase
from stocklock.application.usecases.retention import CleanupRetentionUseCase
from stocklock.application.usecases.product import (
  CorrectProductStockUseCase,
  CreateProductUseCase,
  DeleteProductUseCase,
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
  TryExpireReservationUseCase,
)
from stocklock.domain.ports.repositories.confirmation_repository import IConfirmationRepository
from stocklock.domain.ports.repositories.product_repository import IProductRepository
from stocklock.domain.ports.repositories.reservation_repository import IReservationRepository
from stocklock.domain.services.confirmation_service import ConfirmationService
from stocklock.domain.services.product_service import ProductService
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.infrastructure.clock import PostgresClock
from stocklock.infrastructure.repositories.confirmation_repository import ConfirmationRepository
from stocklock.infrastructure.repositories.product_repository import ProductRepository
from stocklock.infrastructure.repositories.reservation_repository import ReservationRepository
from stocklock.infrastructure.session_manager import SessionManager
from stocklock.infrastructure.uow import SqlAlchemyUnitOfWork
from stocklock.project.configs.database import DatabaseSettings
from stocklock.project.configs.admin import AdminSettings
from stocklock.project.configs.time_policy import TimePolicySettings


@injectable(lifetime="singleton")
def reservation_time_policy(settings: TimePolicySettings) -> ReservationTimePolicy:
  return ReservationTimePolicy(lifetime=settings.reservation_lifetime)


@injectable(lifetime="singleton")
def retention_policy(settings: TimePolicySettings) -> RetentionPolicy:
  return RetentionPolicy(
    expired=settings.expired_reservation_retention,
    cancelled=settings.cancelled_reservation_retention,
    confirmed=settings.confirmation_retention,
  )


@injectable(lifetime="singleton")
def product_cleanup_policy(settings: TimePolicySettings) -> ProductCleanupPolicy:
  return ProductCleanupPolicy(retention=settings.deleted_product_retention)


@injectable(lifetime="scoped")
def cleanup_products_use_case(
  uow: IUnitOfWork,
  products: IProductRepository,
  policy: ProductCleanupPolicy,
  clock: IClock,
) -> CleanupProductsUseCase:
  return CleanupProductsUseCase(uow, products, policy, clock)


@injectable(lifetime="scoped")
def cleanup_retention_use_case(
  uow: IUnitOfWork, reservations: IReservationRepository, policy: RetentionPolicy, clock: IClock
) -> CleanupRetentionUseCase:
  return CleanupRetentionUseCase(uow, reservations, policy, clock)


@injectable(lifetime="scoped")
def product_repository(manager: SessionManager) -> IProductRepository:
  return ProductRepository(manager)


@injectable(lifetime="scoped")
def reservation_repository(manager: SessionManager) -> IReservationRepository:
  return ReservationRepository(manager)


@injectable(lifetime="scoped")
def confirmation_repository(manager: SessionManager) -> IConfirmationRepository:
  return ConfirmationRepository(manager)


@injectable(lifetime="scoped")
def clock(manager: SessionManager) -> IClock:
  return PostgresClock(manager)


@injectable(lifetime="scoped")
def unit_of_work(manager: SessionManager) -> IUnitOfWork:
  return SqlAlchemyUnitOfWork(manager)


@injectable(lifetime="scoped")
def product_service(products: IProductRepository) -> ProductService:
  return ProductService(products)


@injectable(lifetime="scoped")
def reservation_service(reservations: IReservationRepository) -> ReservationService:
  return ReservationService(reservations)


@injectable(lifetime="scoped")
def confirmation_service(confirmations: IConfirmationRepository) -> ConfirmationService:
  return ConfirmationService(confirmations)


@injectable(lifetime="scoped")
def create_product_use_case(uow: IUnitOfWork, products: ProductService) -> CreateProductUseCase:
  return CreateProductUseCase(uow, products)


@injectable(lifetime="scoped")
def delete_product_use_case(uow: IUnitOfWork, products: ProductService, clock: IClock) -> DeleteProductUseCase:
  return DeleteProductUseCase(uow, products, clock)


@injectable(lifetime="scoped")
def get_product_use_case(uow: IUnitOfWork, products: ProductService) -> GetProductUseCase:
  return GetProductUseCase(uow, products)


@injectable(lifetime="scoped")
def list_products_use_case(uow: IUnitOfWork, products: ProductService) -> ListProductsUseCase:
  return ListProductsUseCase(uow, products)


@injectable(lifetime="scoped")
def update_product_use_case(uow: IUnitOfWork, products: ProductService) -> UpdateProductUseCase:
  return UpdateProductUseCase(uow, products)


@injectable(lifetime="scoped")
def correct_product_stock_use_case(uow: IUnitOfWork, products: ProductService) -> CorrectProductStockUseCase:
  return CorrectProductStockUseCase(uow, products)


@injectable(lifetime="scoped")
def reserve_product_use_case(
  uow: IUnitOfWork,
  products: ProductService,
  reservations: ReservationService,
  time_policy: ReservationTimePolicy,
  clock: IClock,
) -> ReserveProductUseCase:
  return ReserveProductUseCase(uow, products, reservations, time_policy, clock)


@injectable(lifetime="scoped")
def get_reservation_use_case(uow: IUnitOfWork, reservations: ReservationService) -> GetReservationUseCase:
  return GetReservationUseCase(uow, reservations)


@injectable(lifetime="scoped")
def list_reservations_use_case(uow: IUnitOfWork, reservations: ReservationService) -> ListReservationsUseCase:
  return ListReservationsUseCase(uow, reservations)


@injectable(lifetime="scoped")
def list_due_reservations_use_case(uow: IUnitOfWork, reservations: ReservationService) -> ListDueReservationsUseCase:
  return ListDueReservationsUseCase(uow, reservations)


@injectable(lifetime="scoped")
def expire_reservations_use_case(
  uow: IUnitOfWork, reservations: ReservationService, products: ProductService
) -> ExpireReservationsUseCase:
  return ExpireReservationsUseCase(uow, reservations, products)


@injectable(lifetime="scoped")
def list_product_reservations_use_case(
  uow: IUnitOfWork, products: ProductService, reservations: ReservationService
) -> ListProductReservationsUseCase:
  return ListProductReservationsUseCase(uow, products, reservations)


@injectable(lifetime="scoped")
def cancel_reservation_use_case(
  uow: IUnitOfWork, products: ProductService, reservations: ReservationService
) -> CancelReservationUseCase:
  return CancelReservationUseCase(uow, products, reservations)


@injectable(lifetime="scoped")
def expire_reservation_use_case(
  uow: IUnitOfWork, products: ProductService, reservations: ReservationService, clock: IClock
) -> ExpireReservationUseCase:
  return ExpireReservationUseCase(uow, products, reservations, clock)


@injectable(lifetime="scoped")
def try_expire_reservation_use_case(
  uow: IUnitOfWork, products: ProductService, reservations: ReservationService, clock: IClock
) -> TryExpireReservationUseCase:
  return TryExpireReservationUseCase(uow, products, reservations, clock)


@injectable(lifetime="scoped")
def confirm_reservation_use_case(
  uow: IUnitOfWork, reservations: ReservationService, confirmations: ConfirmationService, clock: IClock
) -> ConfirmReservationUseCase:
  return ConfirmReservationUseCase(uow, reservations, confirmations, clock)


@injectable(lifetime="scoped")
def get_confirmation_use_case(
  uow: IUnitOfWork, reservations: ReservationService, confirmations: ConfirmationService
) -> GetConfirmationUseCase:
  return GetConfirmationUseCase(uow, reservations, confirmations)


@injectable(lifetime="singleton")
async def database_engine(settings: DatabaseSettings) -> AsyncIterator[AsyncEngine]:
  engine = create_async_engine(settings.STOCKLOCK_DATABASE_URL.get_secret_value(), pool_pre_ping=True)

  try:
    yield engine
  finally:
    await engine.dispose()


@injectable(lifetime="singleton")
def database_session_maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
  return async_sessionmaker(engine, expire_on_commit=False)


@injectable(lifetime="scoped")
def session_manager(session_maker: async_sessionmaker[AsyncSession]) -> SessionManager:
  return SessionManager(session_maker)


def create_container(
  *,
  session_maker: async_sessionmaker[AsyncSession] | None = None,
  database_settings: DatabaseSettings | None = None,
  time_settings: TimePolicySettings | None = None,
  admin_settings: AdminSettings | None = None,
) -> AsyncContainer:
  """Create a container; Wireup's FastAPI integration owns shutdown.

  Workers and tests must enter a scope for workflows and close the root container.
  An injected session maker remains owned by its caller.
  """
  settings = time_settings if time_settings is not None else TimePolicySettings()

  @injectable(lifetime="singleton")
  def time_policy_settings() -> TimePolicySettings:
    return settings

  @injectable(lifetime="singleton")
  def administrative_settings() -> AdminSettings:
    return admin_settings if admin_settings is not None else AdminSettings()

  @injectable(lifetime="singleton")
  def db_settings() -> DatabaseSettings:
    return database_settings or DatabaseSettings()  # type: ignore

  @injectable(lifetime="singleton")
  def supplied_session_maker() -> async_sessionmaker[AsyncSession]:
    assert session_maker is not None
    return session_maker

  return create_async_container(
    injectables=[
      time_policy_settings,
      administrative_settings,
      db_settings,
      *([database_engine, database_session_maker] if session_maker is None else [supplied_session_maker]),
      reservation_time_policy,
      retention_policy,
      product_cleanup_policy,
      cleanup_products_use_case,
      cleanup_retention_use_case,
      session_manager,
      clock,
      unit_of_work,
      product_repository,
      reservation_repository,
      confirmation_repository,
      product_service,
      reservation_service,
      confirmation_service,
      create_product_use_case,
      delete_product_use_case,
      get_product_use_case,
      list_products_use_case,
      update_product_use_case,
      correct_product_stock_use_case,
      reserve_product_use_case,
      get_reservation_use_case,
      list_reservations_use_case,
      list_due_reservations_use_case,
      expire_reservations_use_case,
      list_product_reservations_use_case,
      cancel_reservation_use_case,
      expire_reservation_use_case,
      try_expire_reservation_use_case,
      confirm_reservation_use_case,
      get_confirmation_use_case,
    ]
  )
