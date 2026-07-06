"""Process-global clients for the headless parser worker.

The HTTP service kept its S3 client on ``app.state.s3``; the typed-RPC handlers
have no request state, so the worker owns a module-level singleton instead.
``serve.py`` starts/stops it in the FastStream lifespan; match-log binary
handlers import ``s3_client`` directly.
"""

from __future__ import annotations

from redis.asyncio import Redis

from shared.clients import S3Client
from src.core import config

s3_client = S3Client(
    access_key=config.settings.s3_access_key,
    secret_key=config.settings.s3_secret_key,
    endpoint_url=config.settings.s3_endpoint_url,
    bucket_name=config.settings.s3_bucket_name,
    public_url=config.settings.s3_public_url,
)

# Realtime fan-in bus client (Redis pub/sub) shared by the match-log signal and
# any other worker-originated realtime publishes. Lazy-connects on first command;
# closed in the serve.py shutdown hook.
realtime_redis = Redis.from_url(str(config.settings.redis_url), decode_responses=True)
