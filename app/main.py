from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.api.routes import router
from app.config.settings import get_settings
from app.mcp import create_mcp_server
from app.memory.database import close_database, init_database
from app.middleware import SecurityHeadersMiddleware, UploadSizeLimitMiddleware

logger = logging.getLogger(__name__)


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


class MCPAuthMiddleware:
    """ASGI middleware that gates access to the MCP endpoint behind API key auth."""

    def __init__(self, app, mount_path: str = "/mcp") -> None:
        self.app = app
        self.mount_path = mount_path

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"].startswith(self.mount_path):
            from app.auth import _get_api_keys, _hash_key

            api_keys = _get_api_keys()
            if not api_keys:
                error_msg = (
                    '{"error_code":"AUTH_NOT_CONFIGURED","message":"No API keys configured"}'
                )
                response = Response(
                    content=error_msg,
                    status_code=503,
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return

            headers = dict(scope.get("headers", []))
            auth_header = None
            for key, value in headers:
                if key == b"x-api-key":
                    auth_header = value.decode()
                    break

            if auth_header is None:
                error_msg = '{"error_code":"MISSING_API_KEY","message":"X-API-Key header required"}'
                response = Response(
                    content=error_msg,
                    status_code=401,
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return

            import hmac as _hmac

            provided_hash = _hash_key(auth_header)
            authorized = any(_hmac.compare_digest(provided_hash, kh) for kh in api_keys)
            if not authorized:
                response = Response(
                    content='{"error_code":"INVALID_API_KEY","message":"Invalid API key"}',
                    status_code=401,
                    media_type="application/json",
                )
                await response(scope, receive, send)
                return

        return await self.app(scope, receive, send)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description="Autonomous Partner Onboarding and Verification AI Worker",
        version="0.1.0",
        lifespan=lifespan,
        debug=settings.debug,
    )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={
                "error_code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred",
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        detail = (
            exc.detail
            if isinstance(exc.detail, dict)
            else {
                "error_code": "HTTP_ERROR",
                "message": str(exc.detail),
            }
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=detail,
        )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=settings.cors_methods,
        allow_headers=settings.cors_headers,
    )

    app.add_middleware(SecurityHeadersMiddleware)

    if settings.max_file_size:
        app.add_middleware(UploadSizeLimitMiddleware, max_size=settings.max_file_size)

    app.include_router(router, prefix="/api/v1")

    mcp_server = create_mcp_server()
    app.state.mcp_server = mcp_server
    mcp_app = MCPAuthMiddleware(mcp_server.streamable_http_app(), mount_path="/mcp")
    app.mount("/mcp", mcp_app)

    return app


app = create_app()
