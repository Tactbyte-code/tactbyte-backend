from fastapi import APIRouter
from src.app.admin.router import router as admin_router
from src.app.user.router import router as user_router
from src.app.onboarding.router import router as onboarding_router
from src.app.reddit.router import router as reddit_router
from src.app.reddit.admin_router import router as admin_reddit_router
from src.app.plan.router import router as user_plan_router
from src.app.playstore.router import router as playstore_router
from src.app.playstore.admin_router import router as playstore_admin_router
from src.app.feedback.router import router as feedback_router
from src.app.activity.router import router as activity_routers
from src.app.teams.router import router as teams_router
from src.app.tickets.router import router as ticket_router
from src.app.masters.prices.router import router as price_router
from src.app.masters.packages.router import router as packages_router
from src.app.tickets.user_tickets import router as user_tickets_router
router = APIRouter(prefix="/v1")

# Admin Routes
router.include_router(admin_router, prefix="/admin")
router.include_router(admin_reddit_router, prefix="/admin")
router.include_router(playstore_admin_router, prefix="/admin")
router.include_router(activity_routers)
router.include_router(teams_router)
router.include_router(ticket_router)
router.include_router(price_router)
router.include_router(packages_router)
router.include_router(user_tickets_router)
# Public Routes
router.include_router(user_router)
router.include_router(onboarding_router)
router.include_router(reddit_router)
router.include_router(user_plan_router)
router.include_router(playstore_router)
router.include_router(feedback_router)