from fastapi import APIRouter

from stocklock.api.v1.handlers import confirmation, product, reservation

router = APIRouter(prefix="/api/v1")

router.include_router(product.router)
router.include_router(reservation.router)
router.include_router(confirmation.router)
