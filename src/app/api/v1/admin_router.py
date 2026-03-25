from fastapi import APIRouter
from src.app.auth.admin.router import router as admin_auth_router

router = APIRouter()

router.include_router(admin_auth_router)