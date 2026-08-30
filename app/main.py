from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config.settings import get_settings
from app.mcp import create_mcp_server
from app.memory.database import close_database, init_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize database and MCP session manager on startup."""
    settings = get_settings()
    await init_database(settings.database_url)

    mcp_server = app.state.mcp_server
    session_manager = mcp_server._lowlevel_server._session_manager
    async with session_manager.run():
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/api/v1")

    mcp_server = create_mcp_server()
    app.state.mcp_server = mcp_server
    app.mount("/mcp", mcp_server.streamable_http_app())

    return app


app = create_app()
