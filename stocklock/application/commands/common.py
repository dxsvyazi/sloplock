from dataclasses import dataclass
from uuid import UUID

from stocklock.shared.constraints import DEFAULT_PAGE_SIZE


@dataclass(frozen=True, slots=True, kw_only=True)
class PageCommand:
  start_id: UUID | None = None
  limit: int = DEFAULT_PAGE_SIZE
