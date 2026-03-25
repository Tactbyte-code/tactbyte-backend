from fastapi import APIRouter
from src.app.api.v1 import admin_router
from src.app.api.v1 import public_router

router = APIRouter(prefix="/v1")

router.include_router(admin_router.router, prefix="/admin")
router.include_router(public_router.router)