"""Async S3 client with lifecycle management for MinIO/S3-compatible storage."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from aiobotocore.session import AioSession, get_session
from botocore.exceptions import ClientError
from loguru import logger


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
            raise ValueError(
                "S3 configuration is incomplete. "
                "Set S3_ACCESS_KEY, S3_SECRET_KEY, S3_ENDPOINT_URL."
            )
        self._config = {
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "endpoint_url": endpoint_url,
        }
        self.bucket_name = bucket_name
        self._public_url = public_url.rstrip("/") if public_url else None
        self._session: AioSession | None = None

    async def start(self) -> None:
        self._session = get_session()

    async def close(self) -> None:
        self._session = None

    @asynccontextmanager
    async def _client(self) -> AsyncIterator:
        if self._session is None:
            raise RuntimeError("S3Client not started. Call await client.start() first.")
        async with self._session.create_client("s3", **self._config) as client:
            yield client

    # ── Core operations ──────────────────────────────────────────────────

    async def get_object(self, key: str) -> bytes | None:
        try:
            async with self._client() as client:
                response = await client.get_object(Bucket=self.bucket_name, Key=key)
                return await response["Body"].read()
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                return None
            logger.exception(f"Error getting object '{key}'")
            return None

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
        keys: list[str] = []
        kwargs: dict[str, Any] = {"Bucket": self.bucket_name, "Prefix": prefix}
        try:
            async with self._client() as client:
                while True:
                    response = await client.list_objects_v2(**kwargs)
                    keys.extend(obj["Key"] for obj in response.get("Contents", []))
                    if not response.get("IsTruncated"):
                        break
                    kwargs["ContinuationToken"] = response["NextContinuationToken"]
        except ClientError:
            logger.exception(f"Error listing objects with prefix '{prefix}'")
        return keys

    async def head_object(self, key: str) -> dict | None:
        try:
            async with self._client() as client:
                return await client.head_object(Bucket=self.bucket_name, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] == "404":
                return None
            logger.exception(f"Error heading object '{key}'")
            return None

    async def object_exists(self, key: str) -> bool:
        return await self.head_object(key) is not None

    # ── Folder operations ────────────────────────────────────────────────

    async def check_folder(self, prefix: str) -> bool:
        """Check if a folder (prefix) exists by listing objects under it."""
        objects = await self.list_objects(prefix)
        return len(objects) > 0

    async def create_folder(self, prefix: str) -> bool:
        """Create a folder marker (zero-byte object with trailing slash)."""
        if not prefix.endswith("/"):
            prefix = f"{prefix}/"
        return await self.put_object(prefix, b"")

    async def ensure_folder(self, prefix: str) -> bool:
        """Create folder if it doesn't exist."""
        if not prefix.endswith("/"):
            prefix = f"{prefix}/"
        if await self.check_folder(prefix):
            return True
        return await self.create_folder(prefix)

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

    async def delete_prefix(self, prefix: str) -> int:
        """Delete all objects under a prefix. Returns count of deleted objects."""
        keys = await self.list_objects(prefix)
        deleted = 0
        for key in keys:
            if await self.delete_object(key):
                deleted += 1
        return deleted
