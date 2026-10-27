from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from shared.clients.s3 import S3Client

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


models = importlib.import_module("shared.models")
schemas = importlib.import_module("src.schemas")

division_service = importlib.import_module("src.services.division_grid.service")
import_jobs = importlib.import_module("src.services.division_grid.import_jobs")
portable = importlib.import_module("src.services.division_grid.portable")
marketplace = importlib.import_module("src.services.division_grid.marketplace")

grid_service = division_service.division_grid_service
marketplace_service = marketplace.marketplace_service
import_jobs_service = import_jobs.import_jobs_service


def _one_result(value):
    """A ``session.execute`` result whose ``.unique().scalars().first()`` is ``value``.

    BaseRepository.get/get_by go through ``session.execute``, not ``session.scalar``.
    """
    scalars = SimpleNamespace(first=Mock(return_value=value))
    return SimpleNamespace(unique=Mock(return_value=SimpleNamespace(scalars=Mock(return_value=scalars))))


def _list_result(values):
    """A ``session.execute`` result whose ``.scalars().all()`` is ``values``."""
    return SimpleNamespace(scalars=Mock(return_value=SimpleNamespace(all=Mock(return_value=list(values)))))


def test_division_grid_tracks_import_provenance_and_archival() -> None:
    columns = models.DivisionGrid.__table__.c

    assert {
        "source_workspace_id",
        "source_grid_id",
        "source_fingerprint",
        "imported_at",
        "archived_at",
    } <= set(columns.keys())


def test_division_grid_import_job_has_durable_progress_contract() -> None:
    columns = models.DivisionGridImportJob.__table__.c

    assert {
        "workspace_id",
        "source_workspace_id",
        "requested_by_user_id",
        "status",
        "progress",
        "request_json",
        "result_json",
        "error",
        "idempotency_key",
        "started_at",
        "finished_at",
    } <= set(columns.keys())


def test_marketplace_import_requires_one_explicit_grid_and_version() -> None:
    request = schemas.DivisionGridMarketplaceImportRequest(
        source_workspace_id=10,
        source_grid_id=22,
        source_version_id=33,
    )

    assert request.source_grid_id == 22
    assert request.source_version_id == 33
    assert request.include_icons is True
    assert request.include_native_rank_mappings is True


def test_marketplace_import_rejects_legacy_set_default_switch() -> None:
    with pytest.raises(ValidationError):
        schemas.DivisionGridMarketplaceImportRequest.model_validate(
            {
                "source_workspace_id": 10,
                "source_grid_id": 22,
                "source_version_id": 33,
                "set_default": True,
            }
        )


def test_marketplace_preflight_reports_assets_conflicts_and_fingerprint() -> None:
    result = schemas.DivisionGridMarketplacePreflightResult(
        source_workspace_id=10,
        grids_count=1,
        versions_count=2,
        tiers_count=40,
        mappings_count=1,
        assets_to_copy=3,
        assets_to_reuse=36,
        external_assets=1,
        conflicts=["ow2 already exists"],
        warnings=[schemas.DivisionGridMarketplaceImportWarning(message="External icon retained")],
        source_fingerprint="a" * 64,
    )

    assert result.external_assets == 1
    assert result.source_fingerprint == "a" * 64


def test_tier_write_can_preserve_existing_tier_identity() -> None:
    tier = schemas.DivisionGridTierWrite(
        id=91,
        slug="champion-1",
        number=1,
        name="Champion 1",
        sort_order=0,
        rank_min=4900,
        rank_max=None,
        icon_url="https://cdn.example/champion-1.png",
    )

    assert tier.id == 91


def test_import_job_read_exposes_pollable_progress() -> None:
    job = schemas.DivisionGridImportJobRead(
        id=7,
        workspace_id=2,
        source_workspace_id=1,
        status="running",
        progress=45,
        result=None,
        error=None,
        created_at="2026-07-24T12:00:00Z",
        started_at="2026-07-24T12:00:01Z",
        finished_at=None,
    )

    assert job.progress == 45
    assert job.status == "running"


def test_activation_readiness_lists_missing_and_incomplete_mappings() -> None:
    readiness = schemas.DivisionGridActivationReadiness(
        target_version_id=30,
        is_ready=False,
        used_source_version_ids=[10, 20, 30],
        missing_mapping_version_ids=[10],
        incomplete_mapping_version_ids=[20],
    )

    assert readiness.missing_mapping_version_ids == [10]
    assert readiness.incomplete_mapping_version_ids == [20]


def test_portable_document_has_versioned_round_trip_contract() -> None:
    document = schemas.DivisionGridPortableDocument(
        schema_version="division-grid/v1",
        slug="ow2",
        name="OW2",
        description=None,
        versions=[
            schemas.DivisionGridPortableVersion(
                version=1,
                label="Season 1",
                status="published",
                tiers=[
                    schemas.DivisionGridTierWrite(
                        slug="champion-1",
                        number=1,
                        name="Champion 1",
                        sort_order=0,
                        rank_min=4900,
                        rank_max=None,
                        icon_url="https://cdn.example/champion-1.png",
                    )
                ],
            )
        ],
        mappings=[],
    )

    assert document.schema_version == "division-grid/v2"
    assert document.discipline == "overwatch"
    assert document.versions[0].tiers[0].slug == "champion-1"


def test_published_version_cannot_be_updated_in_place() -> None:
    async def run() -> None:
        version = SimpleNamespace(id=11, status="published", tiers=[], grid=SimpleNamespace(workspace_id=4))
        with (
            patch.object(grid_service, "get_version", AsyncMock(return_value=version)),
            pytest.raises(Exception) as caught,
        ):
            await grid_service.update_version(
                AsyncMock(),
                11,
                schemas.DivisionGridVersionUpdate(label="Changed"),
            )

        assert getattr(caught.value, "status_code", None) == 409

    asyncio.run(run())


def test_draft_minor_edit_preserves_tier_ids_and_mapping_rules() -> None:
    async def run() -> None:
        tier = models.DivisionGridTier(
            version_id=11,
            slug="champion-1",
            number=1,
            name="Champion 1",
            sort_order=0,
            rank_min=4900,
            rank_max=None,
            icon_url="https://cdn.example/champion-1.png",
        )
        tier.id = 91
        version = SimpleNamespace(
            id=11, status="draft", tiers=[tier], grid=SimpleNamespace(workspace_id=4, discipline="overwatch")
        )
        session = SimpleNamespace(
            add=Mock(),
            delete=AsyncMock(),
            execute=AsyncMock(),
            flush=AsyncMock(),
            expire=Mock(),
            info={},
        )
        payload = schemas.DivisionGridVersionUpdate(
            tiers=[
                schemas.DivisionGridTierWrite(
                    id=91,
                    slug="champion-1",
                    number=1,
                    name="Champion One",
                    sort_order=0,
                    rank_min=4900,
                    rank_max=None,
                    icon_url="https://cdn.example/champion-1.png",
                )
            ]
        )

        with patch.object(
            grid_service,
            "get_version",
            AsyncMock(side_effect=[version, version]),
        ):
            await grid_service.update_version(session, 11, payload)

        assert tier.id == 91
        assert tier.name == "Champion One"
        session.delete.assert_not_awaited()
        session.add.assert_not_called()
        session.execute.assert_not_awaited()

    asyncio.run(run())


def test_activate_version_rejects_incomplete_mapping_readiness() -> None:
    async def run() -> None:
        target = SimpleNamespace(
            id=30,
            status="published",
            grid=SimpleNamespace(workspace_id=4, discipline="overwatch"),
        )
        readiness = schemas.DivisionGridActivationReadiness(
            target_version_id=30,
            is_ready=False,
            used_source_version_ids=[10, 30],
            missing_mapping_version_ids=[10],
            incomplete_mapping_version_ids=[],
        )
        workspace = SimpleNamespace(
            id=4, default_division_grid_versions={"overwatch": 12}, disciplines_enabled=["overwatch"]
        )
        with (
            patch.object(grid_service, "get_version", AsyncMock(return_value=target)),
            patch.object(
                grid_service,
                "get_activation_readiness",
                AsyncMock(return_value=readiness),
            ),
            pytest.raises(Exception) as caught,
        ):
            await grid_service.activate_version(
                AsyncMock(),
                workspace=workspace,
                version_id=30,
            )

        assert getattr(caught.value, "status_code", None) == 409
        assert workspace.default_division_grid_versions == {"overwatch": 12}

    asyncio.run(run())


def test_asset_policy_reuses_global_and_preserves_external_icons() -> None:
    assert (
        marketplace.classify_division_icon_asset(
            public_url="https://minio.example/aqt",
            source_workspace_slug="source",
            image_url="https://minio.example/aqt/assets/divisions/champion-1.png",
        ).action
        == "reuse"
    )
    external = marketplace.classify_division_icon_asset(
        public_url="https://minio.example/aqt",
        source_workspace_slug="source",
        image_url="https://cdn.example/champion-1.png",
    )
    assert external.action == "external"
    assert external.source_key is None


def test_asset_policy_only_copies_objects_owned_by_source_workspace() -> None:
    owned = marketplace.classify_division_icon_asset(
        public_url="https://minio.example/aqt",
        source_workspace_slug="source",
        image_url="https://minio.example/aqt/assets/divisions/source/champion-1-a1b2.png",
    )
    foreign = marketplace.classify_division_icon_asset(
        public_url="https://minio.example/aqt",
        source_workspace_slug="source",
        image_url="https://minio.example/aqt/assets/divisions/victim/champion-1.png",
    )

    assert owned.action == "copy"
    assert owned.source_key == "assets/divisions/source/champion-1-a1b2.png"
    assert foreign.action == "external"


def test_external_icon_is_retained_without_s3_round_trips() -> None:
    async def run() -> None:
        s3 = SimpleNamespace(
            _public_url="https://minio.example/aqt",
            copy_object=AsyncMock(),
            get_public_url=Mock(),
        )
        copied = await marketplace.copy_division_icon_asset(
            s3,
            source_workspace=SimpleNamespace(slug="source"),
            target_workspace=SimpleNamespace(slug="target"),
            source_tier=SimpleNamespace(
                id=7,
                slug="champion-1",
                icon_url="https://cdn.example/champion-1.png",
            ),
            target_grid_slug="ow2",
            target_version=1,
        )

        assert copied.public_url == "https://cdn.example/champion-1.png"
        assert copied.key is None
        assert copied.warning is not None
        s3.copy_object.assert_not_awaited()

    asyncio.run(run())


def test_source_fingerprint_is_deterministic_and_content_sensitive() -> None:
    tier = SimpleNamespace(
        slug="champion-1",
        number=1,
        name="Champion 1",
        sort_order=0,
        rank_min=4900,
        rank_max=None,
        icon_url="https://cdn.example/champion-1.png",
        native_rank_min=4900,
        native_rank_max=5000,
    )
    version = SimpleNamespace(version=1, label="Season 1", status="published", tiers=[tier])
    grid = SimpleNamespace(slug="ow2", name="OW2", description=None, versions=[version])

    first = marketplace.build_source_fingerprint([grid], [])
    second = marketplace.build_source_fingerprint([grid], [])
    tier.rank_min = 4800
    changed = marketplace.build_source_fingerprint([grid], [])

    assert first == second
    # Historical marketplace payload: field renaming must not re-import an unchanged grid.
    assert first == "cbe3808b54bac98d78ff9c17e518b349d5d954a2dfde7da362d4d694e011a255"
    assert changed != first
    tier.rank_min = 4900
    tier.native_rank_max = 5100
    assert marketplace.build_source_fingerprint([grid], []) != first


def test_s3_copy_object_uses_server_side_copy() -> None:
    class ClientContext:
        async def __aenter__(self):
            return api

        async def __aexit__(self, *_args):
            return None

    async def run() -> None:
        nonlocal_client = S3Client(
            access_key="access",
            secret_key="secret",
            endpoint_url="https://minio.example",
            bucket_name="aqt",
            public_url="https://minio.example/aqt",
        )
        nonlocal_client._client = Mock(return_value=ClientContext())

        assert await nonlocal_client.copy_object("source.png", "target.png", public=True)
        api.copy_object.assert_awaited_once_with(
            Bucket="aqt",
            Key="target.png",
            CopySource={"Bucket": "aqt", "Key": "source.png"},
            ACL="public-read",
        )

    api = SimpleNamespace(copy_object=AsyncMock())
    asyncio.run(run())


def test_icon_copy_batch_has_bounded_concurrency() -> None:
    async def run() -> None:
        active = 0
        maximum_active = 0
        saturated = asyncio.Event()
        release = asyncio.Event()

        async def copy_one(*_args, **_kwargs):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            if active == marketplace.S3_COPY_CONCURRENCY:
                saturated.set()
            await release.wait()
            active -= 1
            return marketplace.DivisionImageCopy(public_url="/icon.png", key=None)

        source_tiers = [SimpleNamespace(id=index, slug=f"tier-{index}") for index in range(20)]
        with patch.object(marketplace, "copy_division_icon_asset", copy_one):
            task = asyncio.create_task(
                marketplace.copy_division_icon_assets(
                    SimpleNamespace(),
                    source_workspace=SimpleNamespace(),
                    target_workspace=SimpleNamespace(),
                    source_tiers=source_tiers,
                    target_grid_slug="ow2",
                    target_version=1,
                )
            )
            await asyncio.wait_for(saturated.wait(), timeout=1)
            assert maximum_active == marketplace.S3_COPY_CONCURRENCY
            release.set()
            results = await task

        assert len(results) == len(source_tiers)
        assert all(isinstance(result, marketplace.DivisionImageCopy) for result in results)

    asyncio.run(run())


def test_marketplace_preflight_reports_conflicts_asset_policy_and_fingerprint() -> None:
    async def run() -> None:
        global_tier = SimpleNamespace(
            id=1,
            slug="champion-1",
            number=1,
            name="Champion 1",
            sort_order=0,
            rank_min=4900,
            rank_max=None,
            icon_url="https://minio.example/aqt/assets/divisions/champion-1.png",
            native_rank_min=4900,
            native_rank_max=5000,
        )
        external_tier = SimpleNamespace(
            id=2,
            slug="master-1",
            number=1,
            name="Master 1",
            sort_order=1,
            rank_min=4500,
            rank_max=4899,
            icon_url="https://cdn.example/master-1.png",
            native_rank_min=4500,
            native_rank_max=4899,
        )
        version = SimpleNamespace(
            id=10,
            version=1,
            label="Season 1",
            status="published",
            tiers=[global_tier, external_tier],
        )
        grid = SimpleNamespace(id=5, slug="ow2", name="OW2", description=None, versions=[version])
        session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=Mock(return_value=["ow2"]))))

        with patch.object(marketplace_service, "load_mappings_for_versions", AsyncMock(return_value=[])):
            result = await marketplace_service.preflight_division_grid_import(
                session,
                public_url="https://minio.example/aqt",
                target_workspace_id=9,
                source_workspace=SimpleNamespace(id=3, slug="source"),
                source_grids=[grid],
            )

        assert result.grids_count == 1
        assert result.versions_count == 1
        assert result.tiers_count == 2
        assert result.assets_to_reuse == 1
        assert result.external_assets == 1
        assert result.conflicts == ["ow2"]
        assert len(result.source_fingerprint) == 64

    asyncio.run(run())


def test_single_version_import_preflight_honors_selected_version_and_options() -> None:
    async def run() -> None:
        first_tier = SimpleNamespace(
            id=1,
            slug="master-1",
            number=1,
            name="Master 1",
            sort_order=0,
            rank_min=4500,
            rank_max=4899,
            icon_url="https://minio.example/aqt/assets/divisions/master-1.png",
            native_rank_min=4500,
            native_rank_max=4899,
        )
        second_tier = SimpleNamespace(
            id=2,
            slug="champion-1",
            number=1,
            name="Champion 1",
            sort_order=0,
            rank_min=4900,
            rank_max=None,
            icon_url="https://minio.example/aqt/assets/divisions/champion-1.png",
            native_rank_min=4900,
            native_rank_max=5000,
        )
        grid = SimpleNamespace(
            id=5,
            slug="ow2",
            name="OW2",
            description=None,
            versions=[
                SimpleNamespace(id=10, version=1, label="Season 1", status="published", tiers=[first_tier]),
                SimpleNamespace(id=20, version=2, label="Season 2", status="published", tiers=[second_tier]),
            ],
        )
        session = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=Mock(return_value=[]))))

        with patch.object(marketplace_service, "load_mappings_for_versions", AsyncMock(return_value=[])):
            result = await marketplace_service.preflight_division_grid_import(
                session,
                public_url="https://minio.example/aqt",
                target_workspace_id=9,
                source_workspace=SimpleNamespace(id=3, slug="source"),
                source_grids=[grid],
                source_version_id=20,
                include_icons=False,
                include_native_rank_mappings=True,
            )

        assert result.grids_count == 1
        assert result.versions_count == 1
        assert result.tiers_count == 1
        assert result.assets_to_copy == 0
        assert result.assets_to_reuse == 0

    asyncio.run(run())


def test_single_version_import_request_has_only_explicit_options() -> None:
    request = schemas.DivisionGridMarketplaceImportRequest(
        source_workspace_id=3,
        source_grid_id=5,
        source_version_id=20,
        include_icons=True,
        include_native_rank_mappings=False,
    )

    assert request.source_grid_id == 5
    assert request.source_version_id == 20
    assert request.include_icons is True
    assert request.include_native_rank_mappings is False


def test_single_version_copy_import_creates_an_editable_draft() -> None:
    published_at = object()

    assert marketplace.target_imported_version_state(
        mode="copy",
        source_status="published",
        source_published_at=published_at,
    ) == ("draft", None)
    assert marketplace.target_imported_version_state(
        mode="sync",
        source_status="published",
        source_published_at=published_at,
    ) == ("published", published_at)


def test_library_import_reuses_unchanged_import_without_writes() -> None:
    async def run() -> None:
        tier = SimpleNamespace(
            id=2,
            slug="champion-1",
            number=1,
            name="Champion 1",
            sort_order=0,
            rank_min=4900,
            rank_max=None,
            icon_url="https://cdn.example/champion-1.png",
            native_rank_min=4900,
            native_rank_max=5000,
        )
        version = SimpleNamespace(
            id=10,
            version=1,
            label="Season 1",
            status="published",
            tiers=[tier],
        )
        source_grid = SimpleNamespace(
            id=5,
            discipline="overwatch",
            slug="ow2",
            name="OW2",
            description=None,
            versions=[version],
        )
        fingerprint = marketplace.build_source_fingerprint([source_grid], [])
        existing = SimpleNamespace(
            id=50,
            slug="ow2",
            name="OW2",
            source_fingerprint=fingerprint,
            versions=[SimpleNamespace(tiers=[SimpleNamespace()])],
        )
        session = SimpleNamespace(add=Mock(), scalar=AsyncMock(return_value=9))

        with (
            patch.object(marketplace_service, "load_mappings_for_versions", AsyncMock(return_value=[])),
            patch.object(
                marketplace_service,
                "_load_current_imported_grids",
                AsyncMock(return_value={5: existing}),
            ),
        ):
            result = await marketplace_service.import_division_grids(
                session,
                SimpleNamespace(),
                target_workspace=SimpleNamespace(id=9, disciplines_enabled=["overwatch"]),
                source_workspace=SimpleNamespace(id=3),
                source_grids=[source_grid],
                mode="library",
            )

        assert result.created_grids == 0
        assert result.imported_grids[0].target_grid_id == 50
        session.add.assert_not_called()

    asyncio.run(run())


def test_import_job_creation_is_idempotent_and_durable() -> None:
    async def run() -> None:
        existing = SimpleNamespace(id=91)
        session = SimpleNamespace(
            execute=AsyncMock(side_effect=[_one_result(None), _one_result(existing)]),
            add=Mock(),
            flush=AsyncMock(),
        )
        with patch.object(import_jobs_service, "dispatch_import_job", AsyncMock()) as dispatch:
            created = await import_jobs_service.create_import_job(
                session,
                workspace_id=9,
                source_workspace_id=3,
                requested_by_user_id=42,
                source_grid_id=5,
                source_version_id=20,
                include_icons=True,
                include_native_rank_mappings=False,
                source_fingerprint="a" * 64,
            )
            reused = await import_jobs_service.create_import_job(
                session,
                workspace_id=9,
                source_workspace_id=3,
                requested_by_user_id=42,
                source_grid_id=5,
                source_version_id=20,
                include_icons=True,
                include_native_rank_mappings=False,
                source_fingerprint="a" * 64,
            )

        assert created.status == "pending"
        assert created.request_json == {
            "source_grid_id": 5,
            "source_version_id": 20,
            "include_icons": True,
            "include_native_rank_mappings": False,
            "source_fingerprint": "a" * 64,
        }
        assert created.requested_by_user_id == 42
        assert reused is existing
        session.add.assert_called_once_with(created)
        dispatch.assert_awaited_once_with(session, created)

    asyncio.run(run())


def test_import_job_creation_requeues_a_failed_job() -> None:
    async def run() -> None:
        failed = SimpleNamespace(
            id=91,
            status="failed",
            progress=35,
            result_json={"created_grids": 0},
            error="temporary S3 failure",
            started_at=object(),
            finished_at=object(),
        )
        session = SimpleNamespace(execute=AsyncMock(return_value=_one_result(failed)), flush=AsyncMock())

        with patch.object(import_jobs_service, "dispatch_import_job", AsyncMock()) as dispatch:
            retried = await import_jobs_service.create_import_job(
                session,
                workspace_id=9,
                source_workspace_id=3,
                requested_by_user_id=42,
                source_grid_id=5,
                source_version_id=20,
                include_icons=True,
                include_native_rank_mappings=True,
                source_fingerprint="a" * 64,
            )

        assert retried is failed
        assert failed.status == "pending"
        assert failed.progress == 0
        assert failed.result_json is None
        assert failed.error is None
        assert failed.started_at is None
        assert failed.finished_at is None
        dispatch.assert_awaited_once_with(session, failed)

    asyncio.run(run())


def test_marketplace_import_rejects_source_changes_after_preflight() -> None:
    async def run() -> None:
        source_grid = SimpleNamespace(
            id=5,
            discipline="overwatch",
            slug="ow2",
            name="OW2",
            description=None,
            versions=[],
        )
        reviewed_fingerprint = marketplace.build_source_fingerprint([source_grid], [])
        source_grid.name = "Changed after review"

        with (
            patch.object(marketplace_service, "load_mappings_for_versions", AsyncMock(return_value=[])),
            pytest.raises(Exception) as caught,
        ):
            await marketplace_service.import_division_grids(
                SimpleNamespace(),
                SimpleNamespace(),
                target_workspace=SimpleNamespace(id=9, disciplines_enabled=["overwatch"]),
                source_workspace=SimpleNamespace(id=3),
                source_grids=[source_grid],
                expected_source_fingerprint=reviewed_fingerprint,
            )

        assert getattr(caught.value, "status_code", None) == 409

    asyncio.run(run())


def test_import_worker_ignores_a_job_that_was_already_claimed() -> None:
    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return None

    async def run() -> None:
        with (
            patch.object(import_jobs.db, "async_session_maker", Mock(return_value=SessionContext())),
            patch.object(import_jobs, "_new_s3_client", Mock()) as new_s3_client,
        ):
            await import_jobs.process_import_job(91)

        session.execute.assert_awaited_once()
        session.commit.assert_not_awaited()
        new_s3_client.assert_not_called()

    # rowcount 0: another poller already claimed this job.
    session = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=0)),
        commit=AsyncMock(),
    )
    asyncio.run(run())


def test_stale_import_jobs_are_requeued() -> None:
    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *_args):
            return None

    async def run() -> None:
        with (
            patch.object(import_jobs.db, "async_session_maker", Mock(return_value=SessionContext())),
            patch.object(import_jobs_service, "dispatch_import_job", AsyncMock()) as dispatch,
        ):
            recovered = await import_jobs.recover_stale_import_jobs()

        assert recovered == 1
        assert stale.status == "pending"
        assert stale.progress == 0
        assert stale.started_at is None
        dispatch.assert_awaited_once_with(session, stale)
        session.commit.assert_awaited_once()

    stale = SimpleNamespace(
        status="running",
        progress=35,
        started_at=object(),
        finished_at=None,
        error=None,
    )
    session = SimpleNamespace(
        execute=AsyncMock(return_value=_list_result([stale])),
        flush=AsyncMock(),
        commit=AsyncMock(),
    )
    asyncio.run(run())


def test_portable_export_uses_version_and_tier_slugs_instead_of_database_ids() -> None:
    tier_one = SimpleNamespace(
        id=101,
        slug="champion-1",
        number=1,
        name="Champion 1",
        sort_order=0,
        rank_min=4900,
        rank_max=None,
        icon_url="https://cdn.example/champion-1.png",
        native_rank_min=4900,
        native_rank_max=5000,
    )
    tier_two = SimpleNamespace(
        id=202,
        slug="master-1",
        number=1,
        name="Master 1",
        sort_order=0,
        rank_min=4500,
        rank_max=4899,
        icon_url="https://cdn.example/master-1.png",
        native_rank_min=4500,
        native_rank_max=4899,
    )
    versions = [
        SimpleNamespace(id=11, version=1, label="S1", status="published", tiers=[tier_one]),
        SimpleNamespace(id=22, version=2, label="S2", status="published", tiers=[tier_two]),
    ]
    grid = SimpleNamespace(slug="ow2", name="OW2", description=None, discipline="overwatch", versions=versions)
    mapping = SimpleNamespace(
        source_version_id=11,
        target_version_id=22,
        name="S1 to S2",
        rules=[
            SimpleNamespace(
                source_tier_id=101,
                target_tier_id=202,
                weight=1.0,
                is_primary=True,
            )
        ],
    )

    document = portable.build_portable_document(grid, [mapping])

    assert document.schema_version == "division-grid/v2"
    assert document.discipline == "overwatch"
    assert document.mappings[0].source_version == 1
    assert document.mappings[0].rules[0].source_tier_slug == "champion-1"
    assert document.mappings[0].rules[0].target_tier_slug == "master-1"


def test_archiving_workspace_default_grid_is_rejected() -> None:
    async def run() -> None:
        grid = SimpleNamespace(
            id=4,
            workspace_id=9,
            discipline="overwatch",
            archived_at=None,
            versions=[SimpleNamespace(id=11), SimpleNamespace(id=12)],
        )
        session = SimpleNamespace(scalar=AsyncMock(return_value=12))
        with patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)):
            with pytest.raises(Exception) as caught:
                await grid_service.update_grid(
                    session,
                    grid_id=4,
                    data=schemas.DivisionGridUpdate(archived=True),
                )

        assert getattr(caught.value, "status_code", None) == 409

    asyncio.run(run())


def test_marketplace_workspace_list_is_visible_to_any_admin_not_just_members() -> None:
    """A non-superuser admin who is not a member of the source workspace must
    still see it in the marketplace -- the marketplace is cross-tenant by
    design, gated on `division_grid.read` for the TARGET workspace only
    (checked by the RPC handler before this runs), not on membership
    everywhere else."""

    async def run() -> None:
        rows = [SimpleNamespace(id=3, slug="other", name="Other WS", grids_count=2, versions_count=4)]

        class _CapturingSession:
            def __init__(self) -> None:
                self.statement = None

            async def execute(self, statement):
                self.statement = statement
                return rows

        session = _CapturingSession()
        # Only a member of the target workspace, not of workspace 3.
        user = SimpleNamespace(is_superuser=False, get_workspace_ids=lambda: [9])

        result = await marketplace_service.list_marketplace_workspaces(session, target_workspace_id=9, user=user)

        assert [w.id for w in result] == [3]
        # Visibility comes from `Workspace.is_hidden`, not source-workspace membership.
        assert "is_hidden" in str(session.statement)

    asyncio.run(run())


def test_marketplace_workspace_list_has_no_extra_filter_for_superusers() -> None:
    async def run() -> None:
        class _CapturingSession:
            def __init__(self) -> None:
                self.statement = None

            async def execute(self, statement):
                self.statement = statement
                return []

        session = _CapturingSession()
        user = SimpleNamespace(is_superuser=True, get_workspace_ids=lambda: [])

        await marketplace_service.list_marketplace_workspaces(session, target_workspace_id=9, user=user)

        assert "is_hidden" not in str(session.statement)

    asyncio.run(run())
