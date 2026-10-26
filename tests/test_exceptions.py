from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from stocklock.api.v1.schemas.reservation import ReservationResponse
from stocklock.domain.validation import validate_quantity
from stocklock.shared.exceptions import DynamicException, StaticException, ValidationException


def test_static_exception_has_fixed_message_and_no_message_argument():
  class Failure(StaticException):
    message = "Fixed failure"

  assert str(Failure()) == "Fixed failure"
  assert Failure().args == ("Fixed failure",)
  with pytest.raises(TypeError):
    Failure("override")


def test_dynamic_validation_preserves_message_and_hierarchy():
  with pytest.raises(ValidationException, match="between 0 and 3") as caught:
    validate_quantity(4, maximum=3)
  assert isinstance(caught.value, DynamicException)


def test_custom_validation_still_becomes_pydantic_validation_error():
  now = datetime.now(timezone.utc)
  with pytest.raises(ValidationError, match="expires_at must be after created_at"):
    ReservationResponse(
      id="01900000-0000-7000-8000-000000000001",
      product_id="01900000-0000-7000-8000-000000000002",
      quantity=1,
      status="active",
      created_at=now,
      expires_at=now,
    )


def test_fixed_not_found_preserves_workflow_catch_types():
  from stocklock.domain.errors import NotFound, ProductNotFound, StockLockError

  error = ProductNotFound()
  assert str(error) == "Product not found"
  assert isinstance(error, StaticException)
  assert isinstance(error, NotFound)
  assert isinstance(error, StockLockError)


def test_repeated_validation_uses_same_static_exception_across_layers():
  from stocklock.application.commands.product import UpdateProductCommand
  from stocklock.infrastructure.repositories.product_repository import validate_update_details
  from stocklock.shared.exceptions import MissingProductDetails

  with pytest.raises(MissingProductDetails) as caught:
    validate_update_details({})
  assert isinstance(caught.value, StaticException)
  assert isinstance(caught.value, ValidationException)

  with pytest.raises(MissingProductDetails):
    UpdateProductCommand(product_id=uuid4())


@pytest.mark.parametrize("cursor", ["bad", 123, True])
def test_invalid_pagination_cursor_is_rejected_without_transport(cursor):
  from stocklock.application.commands.product import ListProductsCommand

  with pytest.raises(ValidationException, match="UUID"):
    ListProductsCommand(start_id=cursor)
