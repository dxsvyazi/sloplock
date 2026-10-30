"""Shared administrative credential verification at the HTTP boundary."""

from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from stocklock.project.configs.admin import AdminSettings

bearer = HTTPBearer(auto_error=False, scheme_name="AdminBearer")

type AdminCredentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


def require_admin(credentials: HTTPAuthorizationCredentials | None, settings: AdminSettings) -> None:
  token = settings.ADMIN_API_TOKEN.get_secret_value() if settings.ADMIN_API_TOKEN is not None else ""

  if not token.strip():
    raise HTTPException(status_code=503, detail="Administrative access is not configured")

  if credentials is None or not compare_digest(credentials.credentials.encode(), token.encode()):
    raise HTTPException(
      status_code=401, detail="Invalid administrative credentials", headers={"WWW-Authenticate": "Bearer"}
    )
