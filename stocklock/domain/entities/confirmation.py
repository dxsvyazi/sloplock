from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from uuid6 import uuid7

from stocklock.shared.utils import utc_now


@dataclass(slots=True, kw_only=True)
class Confirmation:
  id: UUID = field(default_factory=uuid7)
  reservation_id: UUID

  created_at: datetime = field(default_factory=utc_now)
