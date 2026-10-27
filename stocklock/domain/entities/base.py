from dataclasses import dataclass, field
from typing import Any, cast
from uuid import UUID

from uuid6 import uuid7


@dataclass(frozen=True)
class BaseEntity[T = UUID]:
  id: T = field(default_factory=cast(Any, uuid7))

  def _set(self, key: str, value: Any) -> None:
    object.__setattr__(self, key, value)
