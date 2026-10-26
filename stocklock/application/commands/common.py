from dataclasses import dataclass
from uuid import UUID

from stocklock.domain.validation import validate_id, validate_quantity, validate_text
from stocklock.shared.constraints import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE

__all__ = ["PageCommand", "validate_id", "validate_quantity", "validate_text"]


@dataclass(frozen=True, slots=True, kw_only=True)
class PageCommand:
  start_id: UUID | None = None
  limit: int = DEFAULT_PAGE_SIZE

  def __post_init__(self) -> None:
    if self.start_id is not None:
      validate_id(self.start_id)

    validate_quantity(self.limit, minimum=1, maximum=MAX_PAGE_SIZE)
