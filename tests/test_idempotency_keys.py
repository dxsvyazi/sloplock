from datetime import timedelta
from importlib import import_module
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from stocklock.api.v1.schemas.reservation import CreateReservationRequest
from stocklock.application.commands.reservation import CreateReservationCommand
from stocklock.domain.entities.reservation import Reservation
from stocklock.domain.services.reservation_service import ReservationService
from stocklock.domain.validation import validate_idempotency_key
from stocklock.infrastructure.models.product import ProductORM
from stocklock.infrastructure.models.reservation import ReservationORM
from stocklock.shared.exceptions import ValidationException
from stocklock.shared.utils import utc_now
from tests.service_doubles import Reservations, Store
from tests.test_api import request


INVALID_KEYS = ["", " ", " key", "key ", "a\x00b", "a" * 257, "😀" * 257, "\ud800", "\udfff", None, 123]
VALID_KEYS = ["a", "a" * 256, "😀" * 256, "é" * 256, "Key", "key", "a b"]


@pytest.mark.parametrize("key", INVALID_KEYS)
def test_invalid_keys_are_rejected_at_every_input_boundary(key):
  with pytest.raises(ValidationException):
    validate_idempotency_key(key)
  with pytest.raises(ValidationError):
    CreateReservationRequest(quantity=1, key=key)
  with pytest.raises(ValidationException):
    Reservation(product_id=uuid4(), quantity=1, key=key, expires_at=utc_now() + timedelta(minutes=1))


@pytest.mark.parametrize("key", VALID_KEYS)
def test_valid_keys_preserve_exact_identity(key):
  validate_idempotency_key(key)
  assert CreateReservationCommand(product_id=uuid4(), quantity=1, key=key).key == key
  assert CreateReservationRequest(quantity=1, key=key).key == key
  reservation = Reservation(product_id=uuid4(), quantity=1, key=key, expires_at=utc_now() + timedelta(minutes=1))
  assert reservation.key == key


@pytest.mark.parametrize("key", INVALID_KEYS)
async def test_domain_service_rejects_invalid_keys(key):
  service = ReservationService(Reservations(Store()))
  with pytest.raises(ValidationException):
    await service.find_retry(uuid4(), key, 1)
  with pytest.raises(ValidationException):
    await service.create(
      Reservation(product_id=uuid4(), quantity=1, key=key, expires_at=utc_now() + timedelta(minutes=1))
    )


def test_key_limits_are_visible_in_openapi_schema():
  key = CreateReservationRequest.model_json_schema()["properties"]["key"]
  assert key["minLength"] == 1
  assert key["maxLength"] == 256


@pytest.mark.parametrize("key", ["", "a" * 257, "😀" * 257])
async def test_database_rejects_key_lengths_without_application_validation(database, key):
  product_id = uuid4()
  async with database.engine.begin() as connection:
    await connection.execute(insert(ProductORM).values(id=product_id, name="Widget", sku="W1", stock_quantity=5))
  now = utc_now()
  with pytest.raises(IntegrityError, match="ck_reservations_key_length_valid"):
    async with database.engine.begin() as connection:
      await connection.execute(
        insert(ReservationORM).values(
          id=uuid4(),
          product_id=product_id,
          quantity=1,
          status=1,
          key=key,
          created_at=now,
          expires_at=now + timedelta(minutes=1),
        )
      )


async def test_real_api_rejects_oversized_keys_without_changing_stock(database):
  from stocklock.bootstrap import create_app
  from stocklock.project.container import create_container

  app = create_app(
    container=create_container(session_maker=async_sessionmaker(database.engine, expire_on_commit=False))
  )
  async with app.router.lifespan_context(app):
    status, product = await request(app, "POST", "/products", {"name": "Widget", "sku": "W1", "stock_quantity": 5})
    assert status == 201
    product_id = product["id"]
    for key in ["a" * 8192, "😀" * 257, " key", "a\x00b"]:
      status, _ = await request(app, "POST", f"/products/{product_id}/reservations", {"quantity": 1, "key": key})
      assert status == 422
    status, product = await request(app, "GET", f"/products/{product_id}")
    assert status == 200
    assert product["stock_quantity"] == 5
    status, reservations = await request(app, "GET", f"/products/{product_id}/reservations")
    assert status == 200
    assert reservations == []
    accepted = []
    for key in ["😀" * 256, "Key", "key", "Key"]:
      status, result = await request(app, "POST", f"/products/{product_id}/reservations", {"quantity": 1, "key": key})
      assert status == 201
      accepted.append(result["id"])
    assert accepted[1] != accepted[2]
    assert accepted[1] == accepted[3]
  async with database.engine.connect() as connection:
    assert (await connection.scalars(select(ReservationORM.key))).all() == ["😀" * 256, "Key", "key"]


async def test_key_migration_rejects_incompatible_existing_keys_without_rewriting(database):
  migration = import_module("migrations.versions.0002_reservation_keys")
  product_id = uuid4()
  now = utc_now()
  existing_key = "a" * 257
  async with database.engine.begin() as connection:
    await connection.execute(text("ALTER TABLE reservations DROP CONSTRAINT ck_reservations_key_length_valid"))
    await connection.execute(insert(ProductORM).values(id=product_id, name="Widget", sku="W1", stock_quantity=5))
    await connection.execute(
      insert(ReservationORM).values(
        id=uuid4(),
        product_id=product_id,
        quantity=1,
        status=1,
        key=existing_key,
        created_at=now,
        expires_at=now + timedelta(minutes=1),
      )
    )

  def upgrade(connection):
    with Operations.context(MigrationContext.configure(connection)):
      migration.upgrade()

  with pytest.raises(IntegrityError, match="ck_reservations_key_length_valid"):
    async with database.engine.begin() as connection:
      await connection.run_sync(upgrade)
  async with database.engine.connect() as connection:
    assert (await connection.scalars(select(ReservationORM.key))).all() == [existing_key]
