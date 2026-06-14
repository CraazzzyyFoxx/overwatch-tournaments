"""Shared time middleware for request processing time tracking.

Replaces duplicate implementations across services with a single shared version.
Measures request processing time and adds X-Process-Time header to responses.
"""

import time

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class TimeMiddleware(BaseHTTPMiddleware):
    """Middleware to track and log request processing time.

    - Measures request duration in milliseconds
    - Adds X-Process-Time header to responses
    - Logs request details with correlation ID

    Example:
        ```python
        from shared.observability import TimeMiddleware

        app.add_middleware(TimeMiddleware)
        ```
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Process request with timing."""
        start_time = time.perf_counter()

        # Process request
        response = await call_next(request)

        # Calculate processing time
        process_time = time.perf_counter() - start_time
        process_time_ms = int(process_time * 1000)

        # Add header to response
        response.headers["X-Process-Time"] = str(process_time)

        # Structured log — use logger.bind() to attach fields to the Loguru record.
        # Note: correlation_id is already injected globally via the patcher in setup_logging(),
        # so it will appear in JSON file logs automatically.
        logger.bind(
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            status_code=response.status_code,
            duration_ms=process_time_ms,
        ).info("HTTP request processed")

        return response
