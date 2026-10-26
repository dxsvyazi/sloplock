from collections.abc import Callable
from functools import lru_cache
from typing import Any, ClassVar, Protocol, Type

type DumpFn[T] = Callable[[Type[T]], Callable[[T], dict[str, Any]]]


class IDumpable(Protocol):
  def dump(self) -> dict[str, Any]: ...


class Dumpable:
  dump_factory: ClassVar[DumpFn[Any]]

  def dump(self) -> dict[str, Any]:
    return self._dump()(self)

  @classmethod
  @lru_cache(1)
  def _dump[T: Dumpable](cls: Type[T]) -> Callable[[Any], dict[str, Any]]:
    return cls.dump_factory(cls)
