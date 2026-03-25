from fastapi import APIRouter
from src.app.auth.user.router import router as user_auth_router

router = APIRouter()

router.include_router(user_auth_router)