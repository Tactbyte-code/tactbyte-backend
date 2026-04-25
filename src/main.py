from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.core.settings import settings
from src.core.firebase import initialize_firebase
from src.core.database import engine, Base
from src.app.api.v1.router import router
from src.core.security import authX

# ── Import ALL models so Base.metadata knows about every table ───────────────
from src.app.user.model import User, OTPRecord          # noqa: F401
from src.app.activity.model import UserActivity, UserActivityLog  # noqa: F401


@asynccontextmanager
async def lifespan(app: FastAPI):

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    initialize_firebase()
    yield
    await engine.dispose()


app = FastAPI(
    root_path='/api',
    lifespan=lifespan
)

authX.handle_errors(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def read_root():
    return {"message": "Server is running!"}