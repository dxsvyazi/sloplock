from fastapi import APIRouter, HTTPException, Response, status
from wireup import Injected

from stocklock.application.usecases.healthcheck import HealthCheck

router = APIRouter(prefix="/healthcheck", tags=["healthcheck"])


@router.get("")
async def healthcheck(usecase: Injected[HealthCheck], response: Response) -> bool:
  response.headers["Cache-Control"] = "no-store"

  if await usecase.execute():
    return True

  raise HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    headers={"Cache-Control": "no-store"},
  )
