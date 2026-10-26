from stocklock.domain.errors import StockCapacityExceeded
from stocklock.shared.constraints import MAX_STOCK_QUANTITY


def validate_stock_return_capacity(available_quantity: int, held_quantity: int) -> None:
  """Available stock must leave room for every outstanding hold to be returned."""
  if available_quantity + held_quantity > MAX_STOCK_QUANTITY:
    raise StockCapacityExceeded
