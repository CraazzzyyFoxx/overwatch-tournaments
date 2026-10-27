"""Async S3 client with lifecycle management for MinIO/S3-compatible storage."""

import base64
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from aiobotocore.config import AioConfig
from aiobotocore.session import AioSession, get_session
from botocore.exceptions import ClientError, HTTPClientError
from botocore.exceptions import ConnectionError as BotoConnectionError
from loguru import logger

from shared.core.errors import ApiExc, ApiHTTPException

#: An unreachable endpoint fails in seconds. botocore's defaults (60 s connect and
#: read, five legacy-mode attempts) held an upload for ~50 s before a bare 500.
_CONFIG = AioConfig(connect_timeout=3, read_timeout=30, retries={"total_max_attempts": 2, "mode": "standard"})


class StorageUnavailableError(ApiHTTPException):
    """The object store could not be reached (DNS, refused, timeout): 503 ``storage_unavailable``."""

    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            detail=[ApiExc(msg="File storage is unavailable. Try again in a few minutes.", code="storage_unavailable")],
        )


def _add_content_md5(request: Any, **_kwargs: Any) -> None:
    """Attach the legacy ``Content-MD5`` header ``DeleteObjects`` needs.

    botocore >=1.36 marks ``DeleteObjects`` as ``requestChecksumRequired`` but
    always satisfies that with the *new* flexible-checksum scheme (an
    ``x-amz-checksum-crc32`` header/trailer) — ``Config(request_checksum_
    calculation=...)`` has no effect here, it only toggles checksums for
    operations where one is optional. MinIO/S3-compatible endpoints that
    still hard-require the old ``Content-MD5`` header (not the new one)
    reject the request with "MissingContentMD5" regardless. Computing and
    setting it ourselves on ``before-sign`` — so it lands in the SigV4
    signature — restores the legacy behavior for this one operation.
    """
    body = request.body
    if body is None:
        return
    if isinstance(body, str):
        body = body.encode("utf-8")
    digest = hashlib.md5(body, usedforsecurity=False).digest()
    request.headers["Content-MD5"] = base64.b64encode(digest).decode("ascii")


class S3Client:
    """Async S3 client following the start/close lifecycle pattern.

    Usage::

        client = S3Client(
            access_key="...",
            secret_key="...",
            endpoint_url="https://minio.example.com",
            bucket_name="aqt",
            public_url="https://minio.example.com/aqt",
        )
        await client.start()
        try:
            await client.put_object("avatars/users/1/abc.webp", data, "image/webp")
            url = client.get_public_url("avatars/users/1/abc.webp")
        finally:
            await client.close()
    """

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        endpoint_url: str,
        bucket_name: str = "aqt",
        public_url: str | None = None,
    ) -> None:
        if not access_key or not secret_key or not endpoint_url:
            raise ValueError("S3 configuration is incomplete. Set S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT_URL.")
        self._config = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "endpoint_url": endpoint_url,
        }
        self.bucket_name = bucket_name
        self._public_url = public_url.rstrip("/") if public_url else None
        self._session: AioSession | None = None

    @classmethod
    def from_settings(cls, settings: Any) -> S3Client:
        """Build an ``S3Client`` from any settings object exposing the five
        ``s3_*`` fields ``BaseServiceSettings`` declares."""
        return cls(
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            endpoint_url=settings.s3_endpoint_url,
            bucket_name=settings.s3_bucket_name,
            public_url=settings.s3_public_url,
        )

    async def start(self) -> None:
        self._session = get_session()

    async def close(self) -> None:
        self._session = None

    @asynccontextmanager
    async def _client(self) -> AsyncIterator:
        if self._session is None:
            raise RuntimeError("S3Client not started. Call await client.start() first.")
        async with self._session.create_client("s3", config=_CONFIG, **self._config) as client:
            client.meta.events.register_first("before-sign.s3.DeleteObjects", _add_content_md5)
            try:
                yield client
            except (BotoConnectionError, HTTPClientError) as exc:
                raise StorageUnavailableError() from exc

    # ── Core operations ──────────────────────────────────────────────────

    async def get_object(self, key: str) -> bytes | None:
        """Fetch an object's bytes, or ``None`` if it does not exist.

        Only a genuine "not found" (``NoSuchKey``/404) maps to ``None``; any other
        ``ClientError`` (access denied, network/config failure) is re-raised so it
        is never mistaken for a missing object.
        """
        try:
            async with self._client() as client:
                response = await client.get_object(Bucket=self.bucket_name, Key=key)
                return await response["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                return None
            logger.exception(f"Error getting object '{key}'")
            raise

    async def put_object(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        public: bool = False,
    ) -> bool:
        try:
            async with self._client() as client:
                kwargs: dict[str, Any] = {
                    "Bucket": self.bucket_name,
                    "Key": key,
                    "Body": data,
                    "ContentType": content_type,
                }
                if public:
                    kwargs["ACL"] = "public-read"
                await client.put_object(**kwargs)
                logger.info(f"Uploaded object '{key}'")
                return True
        except ClientError:
            logger.exception(f"Error uploading object '{key}'")
            return False

    async def copy_object(self, source_key: str, target_key: str, *, public: bool = False) -> bool:
        """Copy an object inside the configured bucket without downloading it."""
        try:
            async with self._client() as client:
                kwargs: dict[str, Any] = {
                    "Bucket": self.bucket_name,
                    "Key": target_key,
                    "CopySource": {"Bucket": self.bucket_name, "Key": source_key},
                }
                if public:
                    kwargs["ACL"] = "public-read"
                await client.copy_object(**kwargs)
                logger.info(f"Copied object '{source_key}' to '{target_key}'")
                return True
        except ClientError:
            logger.exception(f"Error copying object '{source_key}' to '{target_key}'")
            return False

    async def delete_object(self, key: str) -> bool:
        try:
            async with self._client() as client:
                await client.delete_object(Bucket=self.bucket_name, Key=key)
                logger.info(f"Deleted object '{key}'")
                return True
        except ClientError:
            logger.exception(f"Error deleting object '{key}'")
            return False

    async def list_objects(self, prefix: str) -> list[str]:
        """List every key under ``prefix``.

        A ``ClientError`` propagates — same rule as ``get_object``/``head_object``.
        Swallowing it returned an empty list indistinguishable from an empty
        prefix, so an endpoint outage (e.g. a 502 from the gateway in front of
        MinIO) made ``delete_prefix`` report 0 deletions while its callers went
        on to null the owning DB column, and made ``get_logs_by_tournament``
        report that a tournament has no logs.
        """
        keys: list[str] = []
        kwargs: dict[str, Any] = {"Bucket": self.bucket_name, "Prefix": prefix}
        async with self._client() as client:
            while True:
                response = await client.list_objects_v2(**kwargs)
                # Skip legacy zero-byte "folder marker" keys ("logs/90/"): they
                # are not objects any caller wants, and the tournament sweep
                # (stats-service/serve_worker.py) fans every listed key out as a log.
                keys.extend(obj["Key"] for obj in response.get("Contents", []) if not obj["Key"].endswith("/"))
                if not response.get("IsTruncated"):
                    break
                kwargs["ContinuationToken"] = response["NextContinuationToken"]
        return keys

    async def head_object(self, key: str) -> dict | None:
        """Return object metadata, or ``None`` if it does not exist.

        Only a genuine "not found" (404/``NoSuchKey``) maps to ``None``; any other
        ``ClientError`` (access denied, network/config failure) is re-raised so it
        is never mistaken for a missing object.
        """
        try:
            async with self._client() as client:
                return await client.head_object(Bucket=self.bucket_name, Key=key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            logger.exception(f"Error heading object '{key}'")
            raise

    # ── URL generation ───────────────────────────────────────────────────

    def get_public_url(self, key: str) -> str:
        """Construct a deterministic public URL for an object."""
        if self._public_url is None:
            raise ValueError("S3Client.public_url is not configured")
        return f"{self._public_url}/{key}"

    async def generate_presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """Generate a presigned URL for private objects."""
        try:
            async with self._client() as client:
                return await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket_name, "Key": key},
                    ExpiresIn=expires_in,
                )
        except ClientError:
            logger.exception(f"Error generating presigned URL for '{key}'")
            raise

    # ── Batch operations ─────────────────────────────────────────────────

    async def delete_prefix(self, prefix: str, *, keep: str | None = None) -> int:
        """Delete all objects under a prefix except ``keep``. Returns count of deleted objects.

        Uses the batch ``delete_objects`` API (up to 1000 keys per call) instead
        of one request per key.
        """
        keys = [key for key in await self.list_objects(prefix) if key != keep]
        if not keys:
            return 0
        deleted = 0
        try:
            async with self._client() as client:
                for start in range(0, len(keys), 1000):
                    chunk = keys[start : start + 1000]
                    response = await client.delete_objects(
                        Bucket=self.bucket_name,
                        Delete={"Objects": [{"Key": key} for key in chunk], "Quiet": True},
                    )
                    errors = response.get("Errors", [])
                    deleted += len(chunk) - len(errors)
                    for err in errors:
                        logger.warning(f"Failed to delete object '{err.get('Key')}': {err.get('Message')}")
        except ClientError:
            logger.exception(f"Error deleting objects with prefix '{prefix}'")
        return deleted
