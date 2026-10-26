from typing import Any, Callable, ClassVar, Type, cast

from sqlalchemy import MetaData, inspect
from sqlalchemy.orm import DeclarativeBase
from typing_extensions import Sentinel

from stocklock.shared.descriptors import cached_classproperty
from stocklock.shared.utils.dumps import Dumpable

_unset: Any = Sentinel("_unset")

metadata = MetaData(
  naming_convention={
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
  }
)


def _create_dump[T: BaseORM](cls: Type[T]) -> Callable[[T], dict[str, Any]]:
  globals: dict[str, Any] = {"T": T, "Any": Any}
  namespace: dict[str, Any] = {}

  name = f"{cls.__name__}_dump"
  signature = f"def {name}(self: T) -> dict[str, Any]:"
  body = f"\n return {{{', '.join(f'"{column}":self.{column}' for column in cls.columns)}}}"

  exec(signature + body, globals=globals, locals=namespace)

  return cast(Callable[[T], dict[str, Any]], namespace[name])


class BaseORM(DeclarativeBase, Dumpable):
  id: ClassVar[Any]

  metadata = metadata
  dump_factory = _create_dump

  @cached_classproperty
  def columns(cls) -> tuple[str, ...]:
    return tuple(column.key for column in inspect(cls).attrs)

  def __repr__(self) -> str:
    return f"{type(self).__name__}<({', '.join(f'{column}={getattr(self, column)}' for column in self.columns)})>"
