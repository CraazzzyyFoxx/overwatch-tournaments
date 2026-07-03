"""Higher-level upload helpers with validation on top of S3Client."""

import hashlib
from typing import Literal

from loguru import logger

from .client import S3Client
from .types import UploadResult

ALLOWED_IMAGE_TYPES = {"image/webp", "image/png", "image/jpeg", "image/gif"}
MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2 MB
MAX_ASSET_SIZE = 5 * 1024 * 1024  # 5 MB

# Leading magic bytes per MIME type. The client-supplied ``content_type`` is
# untrusted, so the real file signature is verified against it before upload.
# WEBP is handled separately (RIFF container: "RIFF" at 0..4, "WEBP" at 8..12).
_MAGIC_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}


def _matches_signature(data: bytes, content_type: str) -> bool:
    """Check the file's leading bytes against the declared ``content_type``."""
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    signatures = _MAGIC_SIGNATURES.get(content_type, ())
    return any(data.startswith(sig) for sig in signatures)


def _content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def _detect_extension(content_type: str) -> str:
    mapping = {
        "image/webp": "webp",
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/gif": "gif",
    }
    return mapping.get(content_type, "bin")


def _validate_image(data: bytes, content_type: str, max_size: int) -> str | None:
    """Returns error message if validation fails, None if ok."""
    if content_type not in ALLOWED_IMAGE_TYPES:
        return f"Unsupported content type: {content_type}. Allowed: {', '.join(ALLOWED_IMAGE_TYPES)}"
    if len(data) > max_size:
        return f"File too large: {len(data)} bytes (max {max_size})"
    if not _matches_signature(data, content_type):
        return f"File content does not match declared content type: {content_type}"
    return None


async def upload_avatar(
    s3: S3Client,
    *,
    entity_type: Literal["users", "workspaces", "players"],
    entity_id: int,
    file_data: bytes,
    content_type: str,
    max_size: int = MAX_AVATAR_SIZE,
) -> UploadResult:
    """Upload an avatar image, returning the UploadResult with the public URL.

    Deletes any previously uploaded avatar for the same entity before uploading.
    Key format: avatars/{entity_type}/{entity_id}/{content_hash}.{ext}
    """
    error = _validate_image(file_data, content_type, max_size)
    if error:
        return UploadResult(success=False, key="", error=error)

    # Delete old avatar(s)
    await delete_old_avatar(s3, entity_type=entity_type, entity_id=entity_id)

    ext = _detect_extension(content_type)
    file_hash = _content_hash(file_data)
    key = f"avatars/{entity_type}/{entity_id}/{file_hash}.{ext}"

    ok = await s3.put_object(key, file_data, content_type, public=True)
    if not ok:
        return UploadResult(success=False, key=key, error="Failed to upload to S3")

    public_url = s3.get_public_url(key)
    logger.info(f"Uploaded avatar: {key}")
    return UploadResult(success=True, key=key, public_url=public_url)


async def upload_asset(
    s3: S3Client,
    *,
    asset_type: Literal["achievements", "divisions"],
    slug: str,
    file_data: bytes,
    content_type: str,
    max_size: int = MAX_ASSET_SIZE,
    workspace_slug: str | None = None,
) -> UploadResult:
    """Upload a static asset image by slug.

    Key format: assets/{asset_type}/{workspace_slug}/{slug}.{ext}
    Falls back to assets/{asset_type}/{slug}.{ext} if no workspace_slug.
    """
    error = _validate_image(file_data, content_type, max_size)
    if error:
        return UploadResult(success=False, key="", error=error)

    ext = _detect_extension(content_type)
    if workspace_slug:
        key = f"assets/{asset_type}/{workspace_slug}/{slug}.{ext}"
    else:
        key = f"assets/{asset_type}/{slug}.{ext}"

    ok = await s3.put_object(key, file_data, content_type, public=True)
    if not ok:
        return UploadResult(success=False, key=key, error="Failed to upload to S3")

    public_url = s3.get_public_url(key)
    logger.info(f"Uploaded asset: {key}")
    return UploadResult(success=True, key=key, public_url=public_url)


async def delete_old_avatar(
    s3: S3Client,
    *,
    entity_type: Literal["users", "workspaces", "players"],
    entity_id: int,
) -> None:
    """Delete existing avatar files for an entity."""
    prefix = f"avatars/{entity_type}/{entity_id}/"
    deleted = await s3.delete_prefix(prefix)
    if deleted > 0:
        logger.info(f"Deleted {deleted} old avatar(s) for {entity_type}/{entity_id}")
