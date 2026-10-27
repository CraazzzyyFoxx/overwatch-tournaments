"""Division-grid imports and activation readiness against PostgreSQL: the stale-job lease, portable validation,
import errors as HTTP codes, and readiness computed in one pass."""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException
from shared.services.division_grid import cache
from shared.services.ontology import project_disciplines
from shared.testing import create_test_async_engine
from shared.testing.cache import configure_test_cache
from shared.testing.db import ensure_test_postgres
from src import schemas
from src.services.division_grid import import_jobs
from src.services.division_grid.marketplace import MarketplaceService, build_source_fingerprint
from src.services.division_grid.portable import PortableService
from src.services.division_grid.service import DivisionGridService
from tests._rpc_fakes import FakeSessionMaker


def _tier(slug: str, rank_min: int, rank_max: int | None, *, sort_order: int) -> schemas.DivisionGridTierWrite:
    return schemas.DivisionGridTierWrite(
        slug=slug,
        number=sort_order + 1,
        name=slug.title(),
        sort_order=sort_order,
        rank_min=rank_min,
        rank_max=rank_max,
        icon_url=f"/{slug}.png",
    )


_TWO_TIERS = [_tier("top", 1000, None, sort_order=0), _tier("low", 0, 999, sort_order=1)]


def test_a_reused_import_whose_versions_drifted_is_a_conflict() -> None:
    """Library mode reuses an unchanged import; one whose versions no longer match its source is 409, not a 500."""

    async def run() -> None:
        drifted = SimpleNamespace(
            id=5,
            discipline="overwatch",
            slug="ow2",
            name="OW2",
            description=None,
            versions=[SimpleNamespace(id=10, version=1, label="S1", status="published", tiers=[])],
        )
        changed = SimpleNamespace(id=6, discipline="overwatch", slug="new", name="New", description=None, versions=[])
        # Imported unchanged (same fingerprint), but its version 1 is gone.
        reused = SimpleNamespace(
            id=50, source_fingerprint=build_source_fingerprint([drifted], [], include_icons=False), versions=[]
        )
        service = MarketplaceService()
        with (
            patch.object(service, "load_mappings_for_versions", AsyncMock(return_value=[])),
            patch.object(service, "_load_current_imported_grids", AsyncMock(return_value={5: reused})),
            pytest.raises(BaseAPIException) as caught,
        ):
            await service.import_division_grids(
                SimpleNamespace(scalar=AsyncMock(return_value=9)),
                SimpleNamespace(),
                target_workspace=SimpleNamespace(id=9, disciplines_enabled=["overwatch"]),
                source_workspace=SimpleNamespace(id=3),
                source_grids=[drifted, changed],
                mode="library",
                include_icons=False,
            )
        assert caught.value.status_code == 409

    asyncio.run(run())


class DivisionGridImportRulesTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self):
        ensure_test_postgres()
        configure_test_cache()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        # The code under test commits; keep it inside this rollback-only PostgreSQL transaction.
        self.session = AsyncSession(
            bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        await project_disciplines(self.session)
        self.tag = uuid.uuid4().hex
        workspace = models.Workspace(
            slug=self.tag, name=self.tag, disciplines_enabled=["overwatch"], division_grid_defaults=[]
        )
        self.session.add(workspace)
        await self.session.flush()
        self.workspace_id = workspace.id
        self.grids = DivisionGridService()

    async def asyncTearDown(self):
        await cache.invalidate_workspace(self.workspace_id)
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    async def job(self, *, status: str, started_minutes_ago: int | None = None) -> int:
        job = models.DivisionGridImportJob(
            workspace_id=self.workspace_id,
            status=status,
            progress=10,
            request_json={},
            idempotency_key=uuid.uuid4().hex,
            started_at=None
            if started_minutes_ago is None
            else datetime.now(UTC) - timedelta(minutes=started_minutes_ago),
        )
        self.session.add(job)
        await self.session.flush()
        return job.id

    async def job_status(self, job_id: int) -> str | None:
        return await self.session.scalar(
            sa.select(models.DivisionGridImportJob.status).where(models.DivisionGridImportJob.id == job_id)
        )

    async def test_a_job_running_past_the_15_minute_lease_is_requeued(self):
        stale = await self.job(status="running", started_minutes_ago=16)
        live = await self.job(status="running", started_minutes_ago=14)
        with patch.object(import_jobs.db, "async_session_maker", FakeSessionMaker(self.session)):
            await import_jobs.recover_stale_import_jobs()
        self.assertEqual((await self.job_status(stale), await self.job_status(live)), ("pending", "running"))

    async def test_an_import_whose_source_workspace_is_gone_fails_as_404(self):
        job_id = await self.job(status="pending")  # source_workspace_id NULL: the source was deleted
        s3 = SimpleNamespace(start=AsyncMock(), close=AsyncMock())
        with (
            patch.object(import_jobs, "_new_s3_client", lambda: s3),
            self.assertRaises(BaseAPIException) as caught,
        ):
            await import_jobs.import_jobs_service.process(self.session, job_id)
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(await self.job_status(job_id), "failed")

    async def test_portable_import_validates_every_version_before_writing(self):
        document = schemas.DivisionGridPortableDocument(
            discipline="overwatch",
            slug="portable",
            name="Portable",
            versions=[
                schemas.DivisionGridPortableVersion(version=1, label="v1", status="published", tiers=_TWO_TIERS),
                schemas.DivisionGridPortableVersion(
                    version=2,
                    label="v2",
                    status="draft",
                    tiers=[_tier("top", 1000, None, sort_order=0), _tier("low", 999, 0, sort_order=1)],
                ),
            ],
        )
        with self.assertRaises(BaseAPIException) as caught:
            await PortableService().import_portable_document(
                self.session,
                workspace_id=self.workspace_id,
                request=schemas.DivisionGridPortableImportRequest(document=document),
            )
        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(caught.exception.detail, "Invalid rank range for tier low")
        self.assertEqual(
            await self.session.scalar(
                sa.select(sa.func.count())
                .select_from(models.DivisionGrid)
                .where(models.DivisionGrid.workspace_id == self.workspace_id)
            ),
            0,
        )

    async def readiness(self, target_id: int) -> tuple[schemas.DivisionGridActivationReadiness, int]:
        """The readiness of ``target_id`` from an empty identity map, and how many statements it took."""
        self.session.expunge_all()
        statements: list[str] = []

        def count(_conn, _cursor, statement, *_args) -> None:
            statements.append(statement)

        event.listen(self.engine.sync_engine, "before_cursor_execute", count)
        try:
            result = await self.grids.get_activation_readiness(
                self.session, workspace_id=self.workspace_id, target_version_id=target_id
            )
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", count)
        return result, len(statements)

    async def test_readiness_reports_every_source_in_a_constant_number_of_statements(self):
        grid = models.DivisionGrid(workspace_id=self.workspace_id, slug=self.tag, name="Ladder", versions=[])
        self.session.add(grid)
        await self.session.flush()
        s1, s2, s3, target = [
            await self.grids.create_version(
                self.session,
                self.workspace_id,
                grid.id,
                schemas.DivisionGridVersionCreate(label=label, tiers=_TWO_TIERS),
            )
            for label in ("v1", "v2", "v3", "target")
        ]
        (s1_top, s1_low), (s2_top, s2_low), (s3_top, s3_low), (t_top, t_low) = (
            version.tiers for version in (s1, s2, s3, target)
        )
        self.session.add_all(
            [
                models.DivisionGridMapping(
                    source_version_id=s1.id,
                    target_version_id=target.id,
                    name="complete",
                    is_complete=True,
                    rules=[
                        models.DivisionGridMappingRule(
                            source_tier_id=s1_top.id, target_tier_id=t_top.id, weight=1.0, is_primary=True
                        ),
                        models.DivisionGridMappingRule(
                            source_tier_id=s1_low.id, target_tier_id=t_low.id, weight=1.0, is_primary=True
                        ),
                    ],
                ),
                models.DivisionGridMapping(
                    source_version_id=s2.id,
                    target_version_id=target.id,
                    name="partial",
                    is_complete=False,
                    rules=[
                        models.DivisionGridMappingRule(
                            source_tier_id=s2_top.id, target_tier_id=t_top.id, weight=1.0, is_primary=True
                        )
                    ],
                ),
            ]
        )
        ids = {"s1": s1.id, "s2": s2.id, "s3": s3.id, "target": target.id}
        conflict = {
            tier.id: schemas.DivisionGridReadinessConflictTier(source_tier_id=tier.id, slug=tier.slug, name=tier.name)
            for tier in (s2_low, s3_top, s3_low)
        }

        async def pin(version: str, *names: str) -> None:
            for name in names:  # one flush each: the ids rise in this order
                self.session.add(
                    models.Tournament(
                        workspace_id=self.workspace_id,
                        name=name,
                        slug=f"{self.tag}-{name}",
                        discipline="overwatch",
                        division_grid_version_id=ids[version],
                    )
                )
                await self.session.flush()

        await pin("s1", "t1", "t2", "t3", "t4", "t5", "t6")
        await pin("target", "x1")
        one_source, one_source_statements = await self.readiness(ids["target"])
        self.assertTrue(one_source.is_ready)
        self.assertEqual([source.version_id for source in one_source.sources], [ids["s1"]])

        await pin("s2", "u1")
        await pin("s3", "w1")
        await cache.invalidate_workspace(self.workspace_id)  # pinned here, not through a committed request
        three_sources, three_sources_statements = await self.readiness(ids["target"])

        self.assertEqual(three_sources_statements, one_source_statements)
        self.assertEqual(
            three_sources,
            schemas.DivisionGridActivationReadiness(
                target_version_id=ids["target"],
                is_ready=False,
                used_source_version_ids=sorted(ids.values()),
                missing_mapping_version_ids=[ids["s3"]],
                incomplete_mapping_version_ids=[ids["s2"]],
                sources=[
                    schemas.DivisionGridReadinessSource(
                        version_id=ids["s1"],
                        version_label="v1",
                        grid_name="Ladder",
                        tournament_count=6,
                        tournament_names=["t6", "t5", "t4", "t3", "t2"],
                        status="ok",
                    ),
                    schemas.DivisionGridReadinessSource(
                        version_id=ids["s2"],
                        version_label="v2",
                        grid_name="Ladder",
                        tournament_count=1,
                        tournament_names=["u1"],
                        status="incomplete",
                        conflict_tiers=[conflict[s2_low.id]],
                    ),
                    schemas.DivisionGridReadinessSource(
                        version_id=ids["s3"],
                        version_label="v3",
                        grid_name="Ladder",
                        tournament_count=1,
                        tournament_names=["w1"],
                        status="missing",
                        conflict_tiers=[conflict[s3_top.id], conflict[s3_low.id]],
                    ),
                ],
            ),
        )
