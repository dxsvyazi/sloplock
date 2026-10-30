from abc import ABC, abstractmethod
from contextlib import AbstractAsyncContextManager


class IUnitOfWork(ABC):
  @abstractmethod
  def begin(self) -> AbstractAsyncContextManager[None]:
    """Commit all changes together, or roll back every change on failure."""
    ...
