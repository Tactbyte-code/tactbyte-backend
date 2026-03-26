from fastapi import APIRouter
from src.app.admin.router import router as admin_router
from src.app.user.router import router as user_router
from src.app.onboarding.router import router as onboarding_router
from src.app.reddit.router import router as reddit_router
from src.app.reddit.admin_router import router as admin_reddit_router
from src.app.plan.router import router as user_plan_router

router = APIRouter(prefix="/v1")

# Admin Routes
router.include_router(admin_router, prefix="/admin")
router.include_router(admin_reddit_router, prefix="/admin")

# Public Routes
router.include_router(user_router)
router.include_router(onboarding_router)
router.include_router(reddit_router)
router.include_router(user_plan_router)