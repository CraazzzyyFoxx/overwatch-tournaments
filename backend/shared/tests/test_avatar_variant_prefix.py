"""Pin the ``variant`` sub-prefix in the avatar key layout.

The cleanup after an upload clears an entity's whole prefix except the new key,
so an entity carrying MORE THAN ONE image (a tournament's cover and its logo)
needs the two images in separate sub-prefixes -- otherwise uploading one
deletes the other. That is the bug ``variant`` exists to prevent, and the reason
the cleanup and a delete must be scoped to their own variant.

The ``variant=None`` cases are just as load-bearing: every pre-existing caller
(user, workspace, player, team, registration-team avatars) passes no variant,
and their keys must stay byte-for-byte what they were, or already-stored
``avatar_url`` values would point at nothing.
"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

from shared.clients.s3.upload import avatar_prefix, delete_old_avatar, upload_avatar

# A 1x1 PNG: `upload_avatar` verifies the real file signature against the
# declared content type, so a placeholder byte string would be rejected.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00"
    b"\x00\x00IEND\xaeB`\x82"
)


def _s3() -> MagicMock:
    return MagicMock(
        put_object=AsyncMock(return_value=True),
        delete_prefix=AsyncMock(return_value=0),
        get_public_url=MagicMock(side_effect=lambda key: f"https://cdn.test/{key}"),
    )


class TestAvatarPrefix(IsolatedAsyncioTestCase):
    def test_variant_nests_under_the_entity_prefix(self):
        self.assertEqual("avatars/tournaments/7/cover/", avatar_prefix("tournaments", 7, "cover"))
        self.assertEqual("avatars/tournaments/7/logo/", avatar_prefix("tournaments", 7, "logo"))

    def test_no_variant_keeps_the_historical_layout(self):
        self.assertEqual("avatars/teams/5/", avatar_prefix("teams", 5))
        self.assertEqual("avatars/teams/5/", avatar_prefix("teams", 5, None))

    async def test_upload_writes_only_under_its_own_variant(self):
        s3 = _s3()

        result = await upload_avatar(
            s3,
            entity_type="tournaments",
            entity_id=7,
            file_data=PNG,
            content_type="image/png",
            variant="cover",
        )

        self.assertTrue(result.success)
        self.assertTrue(result.key.startswith("avatars/tournaments/7/cover/"))
        self.assertTrue(result.key.endswith(".png"))

    async def test_upload_without_variant_keeps_the_flat_key(self):
        s3 = _s3()

        result = await upload_avatar(s3, entity_type="teams", entity_id=5, file_data=PNG, content_type="image/png")

        self.assertTrue(result.key.startswith("avatars/teams/5/"))
        self.assertNotIn("None", result.key)
        self.assertEqual("avatars/teams/5/", result.key.rsplit("/", 1)[0] + "/")

    async def test_cleanup_is_scoped_to_the_variant(self):
        s3 = _s3()

        await delete_old_avatar(s3, entity_type="tournaments", entity_id=7, variant="logo", keep="k")

        # The sibling variant's prefix is NOT touched -- this is the whole point.
        s3.delete_prefix.assert_awaited_once_with("avatars/tournaments/7/logo/", keep="k")
