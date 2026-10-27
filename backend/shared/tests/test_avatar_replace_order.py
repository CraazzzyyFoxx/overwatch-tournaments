"""Replacing an avatar never leaves the row pointing at a deleted object.

``upload_avatar`` used to clear the entity's prefix before writing the new file,
so a failed upload (or a failed row write after it) left the stored URL pointing
at nothing. Now the upload only writes, and the caller removes the previous files
with ``delete_old_avatar(..., keep=new_key)`` once the row has committed.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from shared.clients.s3 import S3Client, StorageUnavailableError
from shared.clients.s3.upload import delete_old_avatar, upload_avatar

# `upload_avatar` checks the real file signature, so this must look like a PNG.
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


class UploadLeavesOldFiles(IsolatedAsyncioTestCase):
    async def test_failed_upload_deletes_nothing(self):
        s3 = MagicMock(put_object=AsyncMock(return_value=False), delete_prefix=AsyncMock(return_value=1))

        result = await upload_avatar(s3, entity_type="teams", entity_id=5, file_data=PNG, content_type="image/png")

        self.assertFalse(result.success)
        s3.delete_prefix.assert_not_awaited()

    async def test_successful_upload_deletes_nothing_either(self):
        s3 = MagicMock(
            put_object=AsyncMock(return_value=True),
            delete_prefix=AsyncMock(return_value=1),
            get_public_url=MagicMock(side_effect=lambda key: f"https://cdn.test/{key}"),
        )

        result = await upload_avatar(s3, entity_type="teams", entity_id=5, file_data=PNG, content_type="image/png")

        self.assertTrue(result.success)
        # The row does not point at the new key yet; the caller cleans up after its commit.
        s3.delete_prefix.assert_not_awaited()


class CleanupKeepsTheNewKey(IsolatedAsyncioTestCase):
    async def test_delete_prefix_spares_keep(self):
        s3 = S3Client(access_key="k", secret_key="s", endpoint_url="http://minio", bucket_name="aqt")
        deleted: list[str] = []

        async def list_objects_v2(**_kwargs):
            return {"Contents": [{"Key": "avatars/teams/5/old.png"}, {"Key": "avatars/teams/5/new.png"}]}

        async def delete_objects(**kwargs):
            deleted.extend(obj["Key"] for obj in kwargs["Delete"]["Objects"])
            return {}

        fake = MagicMock(list_objects_v2=list_objects_v2, delete_objects=delete_objects)

        @asynccontextmanager
        async def _fake_client():
            yield fake

        s3._client = _fake_client  # type: ignore[method-assign]

        count = await s3.delete_prefix("avatars/teams/5/", keep="avatars/teams/5/new.png")

        self.assertEqual(1, count)
        self.assertEqual(["avatars/teams/5/old.png"], deleted)

    async def test_failed_cleanup_does_not_fail_the_committed_write(self):
        s3 = MagicMock(delete_prefix=AsyncMock(side_effect=StorageUnavailableError()))

        # Stale objects are swept by the next upload's cleanup; raising here would
        # report an error for an image that is already in place.
        await delete_old_avatar(s3, entity_type="teams", entity_id=5, keep="avatars/teams/5/new.png")

        s3.delete_prefix.assert_awaited_once_with("avatars/teams/5/", keep="avatars/teams/5/new.png")
