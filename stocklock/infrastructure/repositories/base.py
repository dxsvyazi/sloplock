from dataclasses import dataclass
from typing import Type
from uuid import UUID

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from stocklock.domain.validation import validate_id, validate_page
from stocklock.infrastructure.models.base import BaseORM
from stocklock.infrastructure.session_manager import SessionManager


@dataclass(slots=True)
class SessionRepository:
  session_manager: SessionManager

  @property
  def session(self) -> AsyncSession:
    return self.session_manager.get_session()


def paginate[T: BaseORM](stmt: Select[T], model: Type[T], start_id: UUID | None, limit: int) -> Select[T]:
  validate_page(limit)

  assert hasattr(model, "id")

  if start_id is not None:
    validate_id(start_id)

    stmt = stmt.where(model.id > start_id)  # type: ignore

  return stmt.order_by(model.id).limit(limit)  # type: ignore
