from contextlib import AbstractAsyncContextManager
from typing import Protocol


class IUnitOfWork(Protocol):
  def begin(self) -> AbstractAsyncContextManager[None]:
    """Commit all changes together, or roll back every change on failure."""
    ...
