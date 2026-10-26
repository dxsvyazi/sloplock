from uuid import UUID

from stocklock.api.v1.schemas.common import APISchema, UTCDateTime


class ConfirmationResponse(APISchema):
  id: UUID
  reservation_id: UUID
  created_at: UTCDateTime
