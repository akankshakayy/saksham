from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config.settings import get_settings
from app.memory.database import close_database, init_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database on startup, close on shutdown."""
    settings = get_settings()
    await init_database(settings.database_url)
    yield
    await close_database()


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="Autonomous Partner Onboarding and Verification AI Worker",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.include_router(router, prefix="/api/v1")

    return app


app = create_app()
