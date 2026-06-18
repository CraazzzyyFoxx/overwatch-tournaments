"""In-process ASGI app for the generic HTTP-over-RPC tunnel.

The gateway forwards the long tail of /api/auth/* requests (rbac, player,
me/avatar, ...) to identity-svc over RabbitMQ; this module runs the full FastAPI
router in-process (via httpx ASGITransport in serve.py) so those endpoints reuse
the exact, already-tested auth-service code without per-endpoint porting.

identity-svc stays headless: this app is NEVER bound to a port. Routes are
root-relative (no /api/auth root_path) — the gateway strips the /api/auth prefix
before forwarding, so paths arrive as /rbac/..., /player/..., /me/avatar, etc.
"""

from __future__ import annotations

from fastapi import FastAPI
from shared.clients import S3Client

from src.core.config import settings
from src.routes import router

s3_client = S3Client(
    access_key=settings.s3_access_key,
    secret_key=settings.s3_secret_key,
    endpoint_url=settings.s3_endpoint_url,
    bucket_name=settings.s3_bucket_name,
    public_url=settings.s3_public_url,
)

tunnel_app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
tunnel_app.state.s3 = s3_client
tunnel_app.include_router(router)
