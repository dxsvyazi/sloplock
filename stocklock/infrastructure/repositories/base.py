from dataclasses import dataclass
from typing import Type
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from stocklock.infrastructure.models.base import BaseORM
from stocklock.infrastructure.session_manager import SessionManager
from stocklock.shared.constraints import MAX_PAGE_SIZE
from stocklock.shared.exceptions import ValidationException


@dataclass(slots=True)
class SessionRepository:
  session_manager: SessionManager

  @property
  def session(self) -> AsyncSession:
    return self.session_manager.get_session()


def paginate[T: BaseORM](stmt: Select[T], model: Type[T], start_id: UUID | None, limit: int) -> Select[T]:
  if type(limit) is not int or not 1 <= limit <= MAX_PAGE_SIZE:
    raise ValidationException(f"Page size must be between 1 and {MAX_PAGE_SIZE}")

  assert hasattr(model, "id")

  if start_id is not None:
    if not isinstance(start_id, UUID):
      raise ValidationException("Cursor must be a UUID")

    stmt = stmt.where(model.id > start_id)  # type: ignore

  return stmt.order_by(model.id).limit(limit)  # type: ignore
