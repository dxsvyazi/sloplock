from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from stocklock.api.v1.mappers import confirmation as confirmation_api
from stocklock.api.v1.mappers import product as product_api
from stocklock.api.v1.mappers import reservation as reservation_api
from stocklock.api.v1.schemas.product import (
  CorrectProductStockRequest,
  CreateProductRequest,
  ListProductsRequest,
  ProductResponse,
  UpdateProductRequest,
)
from stocklock.api.v1.schemas.reservation import (
  CreateReservationRequest,
  ListProductReservationsRequest,
  ListReservationsRequest,
)
from stocklock.application.commands.product import CreateProductCommand
from stocklock.application.commands.reservation import CreateReservationCommand
from stocklock.domain.entities.confirmation import Confirmation
from stocklock.domain.entities.product import Product
from stocklock.domain.entities.reservation import Reservation
from stocklock.infrastructure.mappers import confirmation as confirmation_db
from stocklock.infrastructure.mappers import product as product_db
from stocklock.infrastructure.mappers import reservation as reservation_db
from stocklock.shared.enums import ReservationStatus
from stocklock.shared.exceptions import ValidationException

PRODUCT_ID = UUID("01900000-0000-7000-8000-000000000001")
RESERVATION_ID = UUID("01900000-0000-7000-8000-000000000002")
CONFIRMATION_ID = UUID("01900000-0000-7000-8000-000000000003")
CREATED = datetime(2026, 1, 1, tzinfo=timezone.utc)


@pytest.mark.parametrize("value", [-1, True, 1.5, "1", 2**31])
def test_product_stock_requires_a_nonnegative_database_integer(value):
  with pytest.raises(ValidationError):
    CreateProductRequest(name="Widget", sku="W1", stock_quantity=value)


def test_product_request_trims_details_and_accepts_zero_stock():
  request = CreateProductRequest(name=" Widget ", sku=" W1 ", stock_quantity=0)
  assert (request.name, request.sku, request.stock_quantity) == ("Widget", "W1", 0)


@pytest.mark.parametrize("changes", [{"name": "abc"}, {"name": "x" * 257}, {"sku": "  "}, {"id": str(PRODUCT_ID)}])
def test_invalid_product_details_and_unowned_fields_are_rejected(changes):
  with pytest.raises(ValidationError):
    CreateProductRequest.model_validate({"name": "Widget", "sku": "W1", "stock_quantity": 0, **changes})


def test_patch_distinguishes_omitted_fields():
  request = UpdateProductRequest(name="New widget")
  command = product_api.update_request_to_command(PRODUCT_ID, request)
  assert command.name == "New widget"
  assert command.sku is None


@pytest.mark.parametrize("payload", [{}, {"name": None}, {"sku": None}, {"stock_quantity": 2}])
def test_patch_rejects_null_or_empty_updates(payload):
  with pytest.raises(ValidationError):
    UpdateProductRequest.model_validate(payload)


@pytest.mark.parametrize(
  "changes",
  [
    {"quantity": 0},
    {"quantity": -1},
    {"quantity": True},
    {"key": " "},
    {"expires_at": "2026-01-01T00:00:00Z"},
    {"status": "confirmed"},
  ],
)
def test_reservation_cannot_supply_server_owned_fields_or_nonpositive_quantity(changes):
  with pytest.raises(ValidationError):
    CreateReservationRequest.model_validate({"quantity": 1, "key": "retry-1", **changes})


def test_list_filters_use_status_names():
  request = ListReservationsRequest(status="active", limit=100)
  command = reservation_api.list_request_to_command(request)
  assert command.status == ReservationStatus.active


@pytest.mark.parametrize("payload", [{"status": 1}, {"status": "unknown"}, {"limit": 0}, {"limit": 101}])
def test_list_filters_reject_invalid_status_and_page_size(payload):
  with pytest.raises(ValidationError):
    ListReservationsRequest.model_validate(payload)


def test_pagination_accepts_http_query_strings():
  request = ListProductsRequest.model_validate({"start_id": str(PRODUCT_ID), "limit": "25"})
  assert (request.start_id, request.limit) == (PRODUCT_ID, 25)


@pytest.mark.parametrize("value", [True, 1.5, "1.5", "1.0"])
def test_pagination_rejects_boolean_and_fractional_limits(value):
  with pytest.raises(ValidationError):
    ListProductsRequest(limit=value)


def test_commands_validate_without_transport_models_and_are_immutable():
  with pytest.raises(ValidationException):
    CreateProductCommand(name="Widget", sku="W1", stock_quantity=-1)
  with pytest.raises(ValidationException):
    CreateReservationCommand(product_id=PRODUCT_ID, quantity=0, key="retry-1")

  command = CreateProductCommand(name="Widget", sku="W1", stock_quantity=0)

  with pytest.raises(FrozenInstanceError):
    command.stock_quantity = 10


@pytest.mark.parametrize(
  "mapper",
  [
    reservation_api.get_request_to_command,
    reservation_api.cancel_request_to_command,
    reservation_api.expire_request_to_command,
    confirmation_api.get_request_to_command,
    confirmation_api.confirm_request_to_command,
  ],
  ids=["get-reservation", "cancel-reservation", "expire-reservation", "get-confirmation", "confirm-reservation"],
)
def test_path_only_commands_keep_the_target_reservation(mapper):
  assert mapper(RESERVATION_ID).reservation_id == RESERVATION_ID
  with pytest.raises(ValidationException):
    mapper("not-a-uuid")


def test_product_stock_correction_is_absolute_and_separate_from_details():
  command = product_api.stock_request_to_command(PRODUCT_ID, CorrectProductStockRequest(stock_quantity=0))
  assert (command.product_id, command.stock_quantity) == (PRODUCT_ID, 0)
  with pytest.raises(ValidationError):
    CorrectProductStockRequest(stock_quantity=-1)


def test_pagination_and_product_filter_survive_mapping():
  command = product_api.list_request_to_command(ListProductsRequest(start_id=PRODUCT_ID, limit=3))
  assert (command.start_id, command.limit) == (PRODUCT_ID, 3)
  request = ListProductReservationsRequest(start_id=RESERVATION_ID, limit=2, status="cancelled")
  command = reservation_api.list_product_request_to_command(PRODUCT_ID, request)
  assert (command.product_id, command.start_id, command.limit, command.status) == (
    PRODUCT_ID,
    RESERVATION_ID,
    2,
    ReservationStatus.cancelled,
  )


def test_response_requires_aware_timestamps():
  payload = dict(id=PRODUCT_ID, name="Widget", sku="W1", stock_quantity=0, updated_at=None)
  with pytest.raises(ValidationError):
    ProductResponse(**payload, created_at=CREATED.replace(tzinfo=None))
  response = ProductResponse(**payload, created_at=CREATED.astimezone(timezone(timedelta(hours=7))))
  assert response.created_at == CREATED
  assert response.created_at.utcoffset() == timedelta(0)


def test_product_mapping_preserves_identity_and_history():
  product = Product(
    id=PRODUCT_ID,
    name="Widget",
    sku="W1",
    stock_quantity=7,
    created_at=CREATED,
    updated_at=CREATED + timedelta(hours=1),
  )
  restored = product_db.orm_to_domain(product_db.domain_to_orm(product))
  response = product_api.domain_to_response(restored)
  assert response.id == PRODUCT_ID
  assert response.created_at == CREATED
  assert response.updated_at == CREATED + timedelta(hours=1)
  assert response.stock_quantity == 7


@pytest.mark.parametrize("status", list(ReservationStatus), ids=lambda status: status.name)
def test_reservation_maps_integer_storage_status_to_public_name(status):
  reservation = Reservation(
    id=RESERVATION_ID,
    product_id=PRODUCT_ID,
    quantity=3,
    status=status,
    key="retry-1",
    created_at=CREATED,
    expires_at=CREATED + timedelta(minutes=10),
  )
  row = reservation_db.domain_to_orm(reservation)
  assert type(row.status) is int
  restored = reservation_db.orm_to_domain(row)
  assert restored == reservation
  response = reservation_api.domain_to_response(restored).model_dump(mode="json")
  assert response["status"] == status.name
  assert "key" not in response


def test_confirmation_mapping_preserves_existing_result():
  confirmation = Confirmation(id=CONFIRMATION_ID, reservation_id=RESERVATION_ID, created_at=CREATED)
  restored = confirmation_db.orm_to_domain(confirmation_db.domain_to_orm(confirmation))
  response = confirmation_api.domain_to_response(restored)
  assert (response.id, response.reservation_id, response.created_at) == (CONFIRMATION_ID, RESERVATION_ID, CREATED)


def test_persistence_rejects_naive_times_and_normalizes_aware_times():
  product = Product(
    id=PRODUCT_ID,
    name="Widget",
    sku="W1",
    stock_quantity=0,
    created_at=CREATED.replace(tzinfo=timezone(timedelta(hours=7))),
  )
  row = product_db.domain_to_orm(product)
  assert row.created_at.utcoffset() == timedelta(0)
  row.created_at = datetime(2026, 1, 1)
  with pytest.raises(ValidationException):
    product_db.orm_to_domain(row)
