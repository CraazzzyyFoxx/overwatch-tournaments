"""Correlation ID helpers for HTTP requests and async worker flows."""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CORRELATION_ID_HEADER = "X-Correlation-ID"
REQUEST_ID_HEADER = "X-Request-ID"

correlation_id_ctx: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def generate_correlation_id() -> str:
    return str(uuid.uuid4())


def get_correlation_id() -> str | None:
    """Get the correlation ID for the current context."""
    return correlation_id_ctx.get()


def set_correlation_id(correlation_id: str | None) -> Token[str | None]:
    """Set correlation ID for the current context."""
    return correlation_id_ctx.set(correlation_id)


def reset_correlation_id(token: Token[str | None]) -> None:
    """Reset correlation ID for the current context."""
    correlation_id_ctx.reset(token)


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """Middleware to extract or generate correlation IDs for request tracing."""

    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = (
            request.headers.get(CORRELATION_ID_HEADER)
            or request.headers.get(REQUEST_ID_HEADER)
            or generate_correlation_id()
        )

        token = set_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)

        response.headers[CORRELATION_ID_HEADER] = correlation_id
        response.headers[REQUEST_ID_HEADER] = correlation_id
        return response
