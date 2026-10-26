"""Higher-level upload helpers with validation on top of S3Client."""

import hashlib
from typing import Literal

from loguru import logger

from .client import S3Client
from .types import UploadResult

ALLOWED_IMAGE_TYPES = {"image/webp", "image/png", "image/jpeg", "image/gif"}
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5 MB (keep in sync with frontend MAX_AVATAR_BYTES)
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


#: Entities whose images live under ``avatars/``. Not a taxonomy — every member
#: is a table whose rows carry an uploaded image URL.
AvatarEntityType = Literal["users", "workspaces", "players", "teams", "registration_teams", "tournaments"]


def avatar_prefix(entity_type: AvatarEntityType, entity_id: int, variant: str | None = None) -> str:
    """S3 key prefix holding one entity's avatar files.

    ``variant`` carves out a sub-prefix for entities that carry MORE THAN ONE
    image (a tournament's cover and its logo). Without it both would share
    ``avatars/tournaments/{id}/``, and since the post-commit cleanup clears the
    whole prefix but the new key, uploading one would delete the other. ``None``
    keeps the historical single-image layout byte-for-byte, so existing keys are
    untouched.
    """
    base = f"avatars/{entity_type}/{entity_id}/"
    return f"{base}{variant}/" if variant else base


async def upload_avatar(
    s3: S3Client,
    *,
    entity_type: AvatarEntityType,
    entity_id: int,
    file_data: bytes,
    content_type: str,
    max_size: int = MAX_AVATAR_SIZE,
    variant: str | None = None,
) -> UploadResult:
    """Upload an avatar image, returning the UploadResult with the public URL.

    Leaves the entity's previous files in place: once the row pointing at the new
    URL has committed, the caller removes them with
    ``delete_old_avatar(..., keep=result.key)``. Deleting first would leave the row
    pointing at a deleted object whenever the upload or the commit failed.
    Key format: avatars/{entity_type}/{entity_id}/[{variant}/]{content_hash}.{ext}
    """
    error = _validate_image(file_data, content_type, max_size)
    if error:
        return UploadResult(success=False, key="", error=error)

    ext = _detect_extension(content_type)
    file_hash = _content_hash(file_data)
    key = f"{avatar_prefix(entity_type, entity_id, variant)}{file_hash}.{ext}"

    ok = await s3.put_object(key, file_data, content_type, public=True)
    if not ok:
        return UploadResult(success=False, key=key, error="Failed to upload to S3")

    public_url = s3.get_public_url(key)
    logger.info(f"Uploaded avatar: {key}")
    return UploadResult(success=True, key=key, public_url=public_url)


async def upload_asset(
    s3: S3Client,
    *,
    asset_type: Literal["achievements", "divisions", "catalog"],
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
    entity_type: AvatarEntityType,
    entity_id: int,
    variant: str | None = None,
    keep: str | None,
) -> None:
    """Delete an entity's avatar files (optionally one ``variant`` only) except ``keep``.

    Call it once the row pointing at ``keep`` (``None``: the cleared row) has
    committed. Best effort: a failure only leaves stale objects behind, so it is
    logged instead of failing a write that already succeeded.
    """
    prefix = avatar_prefix(entity_type, entity_id, variant)
    try:
        deleted = await s3.delete_prefix(prefix, keep=keep)
    except Exception:
        logger.exception(f"Failed to delete old avatar(s) under {prefix}")
        return
    if deleted > 0:
        logger.info(f"Deleted {deleted} old avatar(s) under {prefix}")
