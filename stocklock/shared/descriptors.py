from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Type

from typing_extensions import Sentinel

_unset: Any = Sentinel("_unset")


@dataclass(slots=True)
class cached_classproperty[VAL: Any, INSTANCE: Any]:
  cls_property: Callable[[Type[INSTANCE]], VAL]
  attr_name: str = _unset

  def __set_name__(self, _: Type[INSTANCE], name: str) -> None:
    if self.attr_name is _unset:
      self.attr_name = f"__{name}"

  def __get__(self, _: INSTANCE, type: Type[INSTANCE]) -> VAL:
    if (val := vars(type).get(self.attr_name, _unset)) is _unset:
      setattr(type, self.attr_name, val := self.cls_property(type))

    return val
