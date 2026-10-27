"""The single S3 client shared by every tournament-service RPC subscriber.

The worker has no app state, so the client is constructed once from the shared
S3 settings and started lazily. ``start()`` only allocates an aiobotocore
session (no network I/O), so the first request that needs S3 can start it
without a serve.py startup hook.

Module-level on purpose — one client per process. Import ``get_s3`` here rather
than building a second ``S3Client`` in a new subscriber module.

``decode_image_b64`` is the image subscribers' shared reading of the gateway's
base64 file body.
"""

from __future__ import annotations

import base64
import math
from typing import Any

from shared.clients.s3 import MAX_AVATAR_SIZE, S3Client
from shared.core.errors import BaseAPIException as HTTPException
from src.core import config

_s3_client: S3Client | None = None
_s3_started = False

#: The longest base64 text that can decode to at most ``MAX_AVATAR_SIZE`` bytes.
_MAX_IMAGE_B64 = 4 * math.ceil(MAX_AVATAR_SIZE / 3)


async def get_s3() -> S3Client:
    global _s3_client, _s3_started
    if _s3_client is None:
        _s3_client = S3Client.from_settings(config.settings)
    if not _s3_started:
        await _s3_client.start()
        _s3_started = True
    return _s3_client


def decode_image_b64(data: dict[str, Any]) -> bytes:
    """``data["content_b64"]`` as bytes: oversized or malformed base64 ⇒ 422.

    The length check runs before decoding, so an oversized body never costs its
    decoded copy.
    """
    content_b64 = data.get("content_b64") or ""
    if len(content_b64) > _MAX_IMAGE_B64:
        raise HTTPException(status_code=422, detail=f"File too large (max {MAX_AVATAR_SIZE} bytes)")
    try:
        return base64.b64decode(content_b64, validate=True)
    except ValueError as exc:  # binascii.Error, or non-ASCII text
        raise HTTPException(status_code=422, detail="content_b64 is not valid base64") from exc
