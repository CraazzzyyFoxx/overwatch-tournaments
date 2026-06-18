"""RPC reply envelope shared by every headless service reached over RabbitMQ.

Every RPC handler returns this envelope; the gateway maps ``error.code`` to an
HTTP status. A single shape keeps the Go side simple and preserves each domain's
HTTP contract status codes.
"""

from __future__ import annotations

from typing import Any

# Error codes -> HTTP status are mapped on the gateway side:
#   unauthorized->401, forbidden->403, bad_request->400,
#   not_found->404, conflict->409, unprocessable->422, internal->500
ERROR_CODES = frozenset(
    {"unauthorized", "forbidden", "bad_request", "not_found", "conflict", "unprocessable", "internal"}
)


def rpc_ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def rpc_error(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


def status_to_code(http_status: int) -> str:
    """Map a FastAPI HTTPException status to an envelope error code."""
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "unprocessable",
    }.get(http_status, "internal")
