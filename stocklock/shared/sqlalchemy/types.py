from datetime import datetime
from enum import Enum
from typing import Annotated, Type
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import mapped_column
from sqlalchemy.types import TypeDecorator
from uuid6 import uuid7

type CreatedAt = Annotated[
  datetime,
  mapped_column(sa.DateTime(True), default=sa.func.now(), server_default=sa.func.now()),
]

type UpdatedAt = Annotated[
  datetime | None,
  mapped_column(
    sa.DateTime(True),
    onupdate=sa.func.now(),
    server_onupdate=sa.func.now(),
  ),
]

type IdInt = Annotated[
  int,
  mapped_column(sa.BigInteger, sa.Identity(), primary_key=True, autoincrement=True),
]

type IdUUID = Annotated[UUID, mapped_column(primary_key=True, default=uuid7)]


class IntEnumType[T: Enum](TypeDecorator[T]):
  """Store IntEnum values as integers in the database."""

  impl = sa.SmallInteger
  cache_ok = True

  def __init__(self, enum_class: Type[T]) -> None:
    self.enum_class = enum_class
    super().__init__()

  def process_bind_param(
    self,
    value: T | int | None,
    dialect: sa.engine.Dialect,
  ) -> int | None:
    if value is None:
      return None

    if isinstance(value, Enum):
      return value.value

    return value

  def process_result_value(
    self,
    value: int | None,
    dialect: sa.engine.Dialect,
  ) -> T | None:
    if value is None:
      return None

    return self.enum_class(value)
