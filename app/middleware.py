"""Security middleware for Saksham.

Provides upload size protection and security headers.
"""

from __future__ import annotations

from starlette.exceptions import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class UploadSizeLimitMiddleware(BaseHTTPMiddleware):
    """Enforce maximum request body size before full allocation.

    Checks Content-Length header when present. For chunked transfers,
    wraps the receive callable to track cumulative bytes.
    """

    def __init__(self, app, max_size: int) -> None:
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")

        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                return Response(
                    content='{"error_code":"BAD_REQUEST","message":"Invalid Content-Length"}',
                    status_code=400,
                    media_type="application/json",
                )
            if size > self.max_size:
                return Response(
                    content='{"error_code":"REQUEST_TOO_LARGE",'
                    '"message":"Request body exceeds maximum size"}',
                    status_code=413,
                    media_type="application/json",
                )
            return await call_next(request)

        # Chunked / unknown size: wrap receive to track bytes
        total_bytes = 0
        body_complete = False
        original_receive = request._receive

        async def wrapped_receive():
            nonlocal total_bytes, body_complete
            message = await original_receive()
            if message.get("type") == "http.request":
                body = message.get("body", b"")
                total_bytes += len(body)
                if total_bytes > self.max_size:
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "error_code": "REQUEST_TOO_LARGE",
                            "message": "Request body exceeds maximum size",
                        },
                    )
                if not message.get("more_body", False):
                    body_complete = True
            return message

        request._receive = wrapped_receive

        try:
            return await call_next(request)
        except HTTPException:
            return Response(
                content='{"error_code":"REQUEST_TOO_LARGE",'
                '"message":"Request body exceeds maximum size"}',
                status_code=413,
                media_type="application/json",
            )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add minimal security headers to all responses."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response
