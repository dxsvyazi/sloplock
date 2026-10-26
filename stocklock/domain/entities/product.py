from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from typing_extensions import Sentinel
from uuid6 import uuid7

from stocklock.shared.utils import utc_now

_unset = Sentinel("_unset")


@dataclass(slots=True, kw_only=True)
class Product:
  id: UUID = field(default_factory=uuid7)
  name: str
  sku: str
  stock_quantity: int

  created_at: datetime = field(default_factory=utc_now)
  updated_at: datetime | None = None

  def __setattr__(self, name: str, value: Any, /) -> None:
    if getattr(self, name, _unset) != value:
      super(Product, self).__setattr__("updated_at", utc_now())

    return super(Product, self).__setattr__(name, value)
