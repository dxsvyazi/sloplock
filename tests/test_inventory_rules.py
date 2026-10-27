import pytest

from stocklock.domain.errors import StockCapacityExceeded
from stocklock.domain.entities.product import Product
from stocklock.shared.constraints import MAX_STOCK_QUANTITY


@pytest.mark.parametrize("available,held", [(0, 0), (MAX_STOCK_QUANTITY, 0), (MAX_STOCK_QUANTITY - 2, 2)])
def test_stock_capacity_allows_exact_return_headroom(available, held):
  Product.validate_return_capacity(available, held)


@pytest.mark.parametrize("available,held", [(MAX_STOCK_QUANTITY, 1), (0, MAX_STOCK_QUANTITY + 1)])
def test_stock_capacity_rejects_unreturnable_holds(available, held):
  with pytest.raises(StockCapacityExceeded):
    Product.validate_return_capacity(available, held)
