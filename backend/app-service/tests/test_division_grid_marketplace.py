from __future__ import annotations

import importlib
import os
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

marketplace = importlib.import_module("src.services.division_grid.marketplace")
division_grid_routes = importlib.import_module("src.routes.division_grid")
models = importlib.import_module("src.models")


class FakeSession:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.next_id = 1000

    def add(self, obj: object) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = self.next_id  # type: ignore[attr-defined]
            self.next_id += 1
        self.added.append(obj)

    async def flush(self) -> None:
        return None


def make_source_grid() -> object:
    source_grid = models.DivisionGrid(
        id=10,
        workspace_id=20,
        slug="ranked-grid",
        name="Ranked Grid",
        description="Source description",
    )
    version_1 = models.DivisionGridVersion(
        id=101,
        grid_id=10,
        version=1,
        label="Season 1",
        status="published",
        created_from_version_id=None,
    )
    version_2 = models.DivisionGridVersion(
        id=102,
        grid_id=10,
        version=2,
        label="Season 2",
        status="draft",
        created_from_version_id=101,
    )
    tier_1 = models.DivisionGridTier(
        id=1001,
        version_id=101,
        slug="bronze",
        number=20,
        name="Bronze",
        sort_order=0,
        rank_min=0,
        rank_max=999,
        icon_url="http://cdn/bucket/assets/divisions/source/bronze.webp",
    )
    tier_2 = models.DivisionGridTier(
        id=1002,
        version_id=102,
        slug="silver",
        number=19,
        name="Silver",
        sort_order=0,
        rank_min=1000,
        rank_max=1999,
        icon_url="http://cdn/bucket/assets/divisions/source/silver.webp",
    )
    version_1.tiers = [tier_1]
    version_2.tiers = [tier_2]
    source_grid.versions = [version_1, version_2]
    return source_grid


def make_mapping() -> object:
    mapping = models.DivisionGridMapping(
        id=500,
        source_version_id=101,
        target_version_id=102,
        name="v1 to v2",
        is_complete=True,
    )
    mapping.rules = [
        models.DivisionGridMappingRule(
            id=501,
            mapping_id=500,
            source_tier_id=1001,
            target_tier_id=1002,
            weight=1.0,
            is_primary=True,
        )
    ]
    return mapping


class UniqueSlugTests(IsolatedAsyncioTestCase):
    async def test_make_unique_grid_slug_creates_copy_suffixes_on_conflict(self) -> None:
        session = SimpleNamespace(results=[1, 2, None])

        async def scalar(_stmt: object) -> int | None:
            return session.results.pop(0)

        session.scalar = scalar

        slug = await marketplace.make_unique_grid_slug(session, 7, "ranked-grid")

        self.assertEqual("ranked-grid-copy-2", slug)


class CopyDivisionIconTests(IsolatedAsyncioTestCase):
    async def test_copy_division_icon_asset_rewrites_asset_into_target_workspace(self) -> None:
        s3 = SimpleNamespace(
            _public_url="http://cdn/bucket",
            list_objects=AsyncMock(return_value=[]),
            get_object=AsyncMock(return_value=b"image-bytes"),
            head_object=AsyncMock(return_value={"ContentType": "image/webp"}),
            put_object=AsyncMock(return_value=True),
            get_public_url=lambda key: f"http://cdn/bucket/{key}",
        )
        source_workspace = models.Workspace(id=20, slug="source", name="Source")
        target_workspace = models.Workspace(id=30, slug="target", name="Target")
        tier = models.DivisionGridTier(
            id=1001,
            slug="bronze",
            name="Bronze",
            number=20,
            sort_order=0,
            rank_min=0,
            rank_max=999,
            icon_url="http://cdn/bucket/assets/divisions/source/bronze.webp",
        )

        copied = await marketplace.copy_division_icon_asset(
            s3,
            source_workspace=source_workspace,
            target_workspace=target_workspace,
            source_tier=tier,
            target_grid_slug="ranked-grid-copy",
            target_version=1,
        )

        self.assertEqual(
            "assets/divisions/target/imports/ranked-grid-copy/v1/bronze-1001.webp",
            copied.key,
        )
        self.assertEqual(f"http://cdn/bucket/{copied.key}", copied.public_url)
        s3.get_object.assert_awaited_once_with("assets/divisions/source/bronze.webp")
        s3.put_object.assert_awaited_once_with(copied.key, b"image-bytes", "image/webp", public=True)


class ImportDivisionGridsTests(IsolatedAsyncioTestCase):
    async def test_import_division_grids_copies_versions_tiers_mappings_and_default(self) -> None:
        session = FakeSession()
        source_workspace = models.Workspace(
            id=20,
            slug="source",
            name="Source",
            default_division_grid_version_id=101,
        )
        target_workspace = models.Workspace(id=30, slug="target", name="Target")
        source_grid = make_source_grid()

        async def copy_icon(_s3: object, **kwargs: object) -> object:
            source_tier = kwargs["source_tier"]
            return marketplace.DivisionImageCopy(
                public_url=f"http://cdn/bucket/assets/divisions/target/imports/ranked-grid/{source_tier.slug}.webp",
                key=f"assets/divisions/target/imports/ranked-grid/{source_tier.slug}.webp",
            )

        with (
            patch.object(marketplace, "make_unique_grid_slug", AsyncMock(return_value="ranked-grid")),
            patch.object(marketplace, "copy_division_icon_asset", AsyncMock(side_effect=copy_icon)),
            patch.object(marketplace, "load_mappings_for_versions", AsyncMock(return_value=[make_mapping()])),
            patch.object(marketplace.division_grid_cache, "invalidate_workspace", AsyncMock()),
            patch.object(marketplace.division_grid_cache, "invalidate_grid_version", AsyncMock()),
            patch.object(marketplace.division_grid_cache, "invalidate_mapping", AsyncMock()),
        ):
            result = await marketplace.import_division_grids(
                session,
                SimpleNamespace(delete_object=AsyncMock()),
                target_workspace=target_workspace,
                source_workspace=source_workspace,
                source_grids=[source_grid],
                set_default=True,
            )

        created_versions = [obj for obj in session.added if isinstance(obj, models.DivisionGridVersion)]
        created_tiers = [obj for obj in session.added if isinstance(obj, models.DivisionGridTier)]
        created_mappings = [obj for obj in session.added if isinstance(obj, models.DivisionGridMapping)]
        created_rules = [obj for obj in session.added if isinstance(obj, models.DivisionGridMappingRule)]

        self.assertEqual(1, result.created_grids)
        self.assertEqual(2, result.created_versions)
        self.assertEqual(2, result.created_tiers)
        self.assertEqual(2, result.copied_images)
        self.assertEqual(1, result.copied_mappings)
        self.assertEqual(created_versions[0].id, target_workspace.default_division_grid_version_id)
        self.assertEqual(created_versions[0].id, created_versions[1].created_from_version_id)
        self.assertEqual(created_versions[0].id, created_mappings[0].source_version_id)
        self.assertEqual(created_versions[1].id, created_mappings[0].target_version_id)
        self.assertEqual(created_tiers[0].id, created_rules[0].source_tier_id)
        self.assertEqual(created_tiers[1].id, created_rules[0].target_tier_id)
        self.assertEqual(
            "http://cdn/bucket/assets/divisions/target/imports/ranked-grid/bronze.webp",
            created_tiers[0].icon_url,
        )

    async def test_import_division_grids_cleans_copied_images_when_later_copy_fails(self) -> None:
        session = FakeSession()
        source_workspace = models.Workspace(id=20, slug="source", name="Source")
        target_workspace = models.Workspace(id=30, slug="target", name="Target")
        source_grid = make_source_grid()
        s3 = SimpleNamespace(delete_object=AsyncMock(return_value=True))

        copy_calls = 0

        async def copy_icon(_s3: object, **_kwargs: object) -> object:
            nonlocal copy_calls
            copy_calls += 1
            if copy_calls == 1:
                return marketplace.DivisionImageCopy(
                    public_url="http://cdn/bucket/assets/divisions/target/imports/ranked-grid/bronze.webp",
                    key="assets/divisions/target/imports/ranked-grid/bronze.webp",
                )
            raise HTTPException(status_code=409, detail="copy failed")

        with (
            patch.object(marketplace, "make_unique_grid_slug", AsyncMock(return_value="ranked-grid")),
            patch.object(marketplace, "copy_division_icon_asset", AsyncMock(side_effect=copy_icon)),
            patch.object(marketplace, "load_mappings_for_versions", AsyncMock(return_value=[])),
        ):
            with self.assertRaises(HTTPException):
                await marketplace.import_division_grids(
                    session,
                    s3,
                    target_workspace=target_workspace,
                    source_workspace=source_workspace,
                    source_grids=[source_grid],
                    set_default=False,
                )

        s3.delete_object.assert_awaited_once_with(
            "assets/divisions/target/imports/ranked-grid/bronze.webp"
        )


class DivisionGridMarketplaceRouteHelperTests(IsolatedAsyncioTestCase):
    async def test_target_workspace_requires_division_grid_permission(self) -> None:
        user = models.AuthUser(id=1, email="u@example.com", username="u", is_superuser=False)
        user.set_rbac_cache(role_names=[], permissions=[], workspaces=[{"workspace_id": 7, "role": "member"}])

        with self.assertRaises(HTTPException) as ctx:
            await division_grid_routes._require_workspace_permission(
                7,
                session=object(),
                user=user,
                action="import",
            )

        self.assertEqual(403, ctx.exception.status_code)

    async def test_source_workspace_cannot_equal_target_workspace(self) -> None:
        user = models.AuthUser(id=1, email="u@example.com", username="u")

        with self.assertRaises(HTTPException) as ctx:
            await division_grid_routes._get_source_workspace_or_404(
                session=object(),
                target_workspace_id=7,
                source_workspace_id=7,
                user=user,
            )

        self.assertEqual(400, ctx.exception.status_code)

    async def test_missing_source_workspace_returns_404(self) -> None:
        user = models.AuthUser(id=1, email="u@example.com", username="u", is_superuser=True)

        with patch.object(division_grid_routes.workspace_service, "get_by_id", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as ctx:
                await division_grid_routes._get_source_workspace_or_404(
                    session=object(),
                    target_workspace_id=7,
                    source_workspace_id=8,
                    user=user,
                )

        self.assertEqual(404, ctx.exception.status_code)

    async def test_inaccessible_source_workspace_returns_403(self) -> None:
        user = models.AuthUser(id=1, email="u@example.com", username="u", is_superuser=False)
        user.set_rbac_cache(role_names=[], permissions=[], workspaces=[{"workspace_id": 7, "role": "admin"}])

        with patch.object(
            division_grid_routes.workspace_service,
            "get_by_id",
            AsyncMock(return_value=models.Workspace(id=8, slug="source", name="Source")),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await division_grid_routes._get_source_workspace_or_404(
                    session=object(),
                    target_workspace_id=7,
                    source_workspace_id=8,
                    user=user,
                )

        self.assertEqual(403, ctx.exception.status_code)

    async def test_source_workspace_member_can_access_source(self) -> None:
        user = models.AuthUser(id=1, email="u@example.com", username="u", is_superuser=False)
        user.set_rbac_cache(
            role_names=[],
            permissions=[],
            workspaces=[
                {"workspace_id": 7, "role": "admin"},
                {"workspace_id": 8, "role": "member"},
            ],
        )
        source_workspace = models.Workspace(id=8, slug="source", name="Source")

        with patch.object(
            division_grid_routes.workspace_service,
            "get_by_id",
            AsyncMock(return_value=source_workspace),
        ):
            result = await division_grid_routes._get_source_workspace_or_404(
                session=object(),
                target_workspace_id=7,
                source_workspace_id=8,
                user=user,
            )

        self.assertIs(source_workspace, result)
