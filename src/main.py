from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from src.core.settings import settings
from src.core.firebase import initialize_firebase
from src.core.database import engine
from src.app.api.v1.router import router
from src.core.security import authX

@asynccontextmanager
async def lifespan(app: FastAPI):
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