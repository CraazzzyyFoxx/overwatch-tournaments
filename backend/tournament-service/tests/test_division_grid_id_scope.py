"""One 403/404 rule across the division-grid handlers: the permission on the workspace the request acts on is
checked first (403); an id the caller cannot see, or one outside the path's workspace, is 404 like a missing id.
A system grid is visible to everyone and writable by no workspace (403 ``division_grid_read_only``); a workspace's own
rows that point at it -- its default, a mapping from its own version onto it -- stay allowed."""

from __future__ import annotations

import asyncio
import sys
import uuid
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.services.division_grid import cache
from shared.services.ontology import project_disciplines
from shared.testing import create_test_async_engine
from shared.testing.cache import configure_test_cache
from shared.testing.db import ensure_test_postgres
from src import schemas
from src.rpc import _helpers as rpc_helpers
from src.rpc import integrations
from src.services.division_grid.service import DivisionGridService
from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

_TIER = {"slug": "top", "number": 1, "name": "Top", "sort_order": 0, "rank_min": 0, "rank_max": None, "icon_url": "/"}


class DivisionGridIdScopeTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self):
        ensure_test_postgres()
        configure_test_cache()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        self.session = AsyncSession(
            bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        await project_disciplines(self.session)
        tag = uuid.uuid4().hex
        own, other = (
            models.Workspace(
                slug=f"{tag}-{name}", name=name, disciplines_enabled=["overwatch"], division_grid_defaults=[]
            )
            for name in ("own", "other")
        )
        self.session.add_all([own, other])
        await self.session.flush()
        self.own, self.other, self.other_workspace = own.id, other.id, other
        grids = DivisionGridService()
        own_grid = await grids.create_grid(self.session, self.own, schemas.DivisionGridCreate(name="Own"))
        other_grid = await grids.create_grid(self.session, self.other, schemas.DivisionGridCreate(name="Other"))
        self.own_version, self.other_grid, self.other_version = (
            own_grid.versions[0].id,
            other_grid.id,
            other_grid.versions[0].id,
        )
        job = models.DivisionGridImportJob(
            workspace_id=self.other, status="pending", progress=0, request_json={}, idempotency_key=tag
        )
        self.session.add(job)
        await self.session.flush()
        self.other_job = job.id
        self.broker = CapturingBroker()
        integrations.register(self.broker, SimpleNamespace(exception=lambda *a, **k: None))

    async def asyncTearDown(self):
        for workspace_id in (self.own, self.other):
            await cache.invalidate_workspace(workspace_id)
        await self.session.close()
        await self.transaction.rollback()
        await self.connection.close()
        await self.engine.dispose()

    def caller(self, *actions: str) -> dict[str, Any]:
        """A member of the own workspace holding ``division_grid.<action>`` there, nothing in the other one."""
        permissions = [{"resource": "division_grid", "action": action} for action in actions]
        return make_identity(workspaces=[{"workspace_id": self.own, "rbac_roles": [], "rbac_permissions": permissions}])

    async def envelope(self, subject: str, identity: dict[str, Any], **data: Any) -> dict[str, Any]:
        with patch.object(rpc_helpers.db, "async_session_maker", FakeSessionMaker(self.session)):
            return await self.broker.handlers[f"rpc.tournament.{subject}"]({"identity": identity, **data}, None)

    async def error_code(self, subject: str, identity: dict[str, Any], **data: Any) -> str | None:
        envelope = await self.envelope(subject, identity, **data)
        return None if envelope["ok"] else envelope["error"]["code"]

    async def test_an_id_of_another_workspace_is_404_like_a_missing_one(self):
        admin = self.caller("read", "create", "update", "delete")
        self.other_workspace.is_hidden = True  # a hidden marketplace source the caller is no member of
        await self.session.flush()
        cases = [
            ("grid_version_get", {"id": self.other_version}),
            ("grid_version_update", {"id": self.other_version, "payload": {"label": "x"}}),
            ("grid_version_publish", {"id": self.other_version}),
            ("grid_version_delete", {"id": self.other_version}),
            ("grid_version_clone", {"id": self.other_version}),
            ("grid_update", {"id": self.other_grid, "payload": {"name": "x"}}),
            ("grid_delete", {"id": self.other_grid}),
            ("grid_versions_list", {"id": self.other_grid}),
            ("grid_version_create", {"id": self.other_grid, "payload": {"label": "x", "tiers": [_TIER]}}),
            ("grid_portable_export", {"id": self.other_grid}),
            ("grid_mapping_get", {"source_version_id": self.own_version, "target_version_id": self.other_version}),
            (
                "grid_mapping_put",
                {
                    "source_version_id": self.own_version,
                    "target_version_id": self.other_version,
                    "payload": {"name": "m", "rules": []},
                },
            ),
            ("grid_version_readiness", {"workspace_id": self.own, "version_id": self.other_version}),
            ("grid_version_activate", {"workspace_id": self.own, "version_id": self.other_version}),
            ("grid_save", {"workspace_id": self.own, "payload": {"grid_id": self.other_grid, "tiers": [_TIER]}}),
            (
                "grid_workspace_create",
                {"workspace_id": self.own, "payload": {"name": "Copy", "from_version_id": self.other_version}},
            ),
            ("grid_import_job_get", {"workspace_id": self.own, "job_id": self.other_job}),
            ("grid_marketplace_grids", {"workspace_id": self.own, "query": {"source_workspace_id": [str(self.other)]}}),
        ]
        for subject, data in cases:
            with self.subTest(subject):
                self.assertEqual(await self.error_code(subject, admin, **data), "not_found")

    async def test_the_permission_is_checked_first_and_a_visible_row_without_it_is_403(self):
        reader = self.caller("read")
        cases = [
            # A row of the caller's own workspace: visible, but no division_grid.update there.
            ("grid_version_update", {"id": self.own_version, "payload": {"label": "x"}}),
            # The path's workspace is checked before the ids it names.
            ("grid_version_activate", {"workspace_id": self.own, "version_id": self.other_version}),
            ("grid_version_readiness", {"workspace_id": self.other, "version_id": self.other_version}),
            ("grid_import_job_get", {"workspace_id": self.other, "job_id": self.other_job}),
        ]
        for subject, data in cases:
            with self.subTest(subject):
                self.assertEqual(await self.error_code(subject, reader, **data), "forbidden")

    async def test_a_system_grid_is_read_only_to_a_workspace_admin(self):
        tier = models.DivisionGridTier(**{**_TIER, "icon_url": "/top.png"})
        version = models.DivisionGridVersion(version=1, label="System", status="published", tiers=[tier])
        system = models.DivisionGrid(
            workspace_id=None, slug=uuid.uuid4().hex, name="System", discipline="overwatch", versions=[version]
        )
        self.session.add(system)
        await self.session.flush()
        renamed = {**_TIER, "id": tier.id, "name": "Renamed", "icon_url": "/top.png"}
        admin = self.caller("read", "create", "update", "delete")
        cases = [
            # Same ranks, new name: the in-place (cosmetic) save that used to rewrite the shared tiers.
            ("grid_save", {"workspace_id": self.own, "payload": {"grid_id": system.id, "tiers": [renamed]}}),
            ("grid_version_update", {"id": version.id, "payload": {"label": "Renamed", "tiers": [renamed]}}),
            ("grid_update", {"id": system.id, "payload": {"name": "Renamed"}}),
            # A mapping FROM a system version: its source row is shared, so no workspace owns it.
            (
                "grid_mapping_put",
                {"source_version_id": version.id, "target_version_id": self.own_version, "payload": {"name": "m"}},
            ),
        ]
        for subject, data in cases:
            with self.subTest(subject):
                envelope = await self.envelope(subject, admin, **data)
                self.assertEqual(envelope["error"]["code"], "forbidden", envelope)
                self.assertEqual(envelope["error"]["details"]["fields"][0]["code"], "division_grid_read_only")

        rows = (
            await self.session.execute(
                sa.select(models.DivisionGridVersion.label, models.DivisionGridTier.name)
                .join(models.DivisionGridTier, models.DivisionGridTier.version_id == models.DivisionGridVersion.id)
                .where(models.DivisionGridVersion.grid_id == system.id)
            )
        ).all()
        self.assertEqual([tuple(row) for row in rows], [("System", "Top")])
        self.assertEqual(
            await self.session.scalar(sa.select(models.DivisionGrid.name).where(models.DivisionGrid.id == system.id)),
            "System",
        )
        self.assertIsNone(
            await self.session.scalar(
                sa.select(models.DivisionGridMapping.id).where(
                    models.DivisionGridMapping.source_version_id == version.id
                )
            )
        )

    async def test_a_workspace_maps_its_own_version_onto_a_system_version_and_activates_it(self):
        """Both writes land on rows the workspace owns -- its default, and a mapping whose source is its own
        version -- never on the system grid, so neither is read-only (the base behaviour). A tournament pinned to
        the workspace's own version makes activation need that mapping first."""
        version = models.DivisionGridVersion(
            version=1, label="System", status="published", tiers=[models.DivisionGridTier(**_TIER)]
        )
        system = models.DivisionGrid(
            workspace_id=None, slug=uuid.uuid4().hex, name="System", discipline="overwatch", versions=[version]
        )
        self.session.add_all(
            [
                system,
                models.Tournament(
                    workspace_id=self.own,
                    name="Pinned",
                    slug=uuid.uuid4().hex,
                    discipline="overwatch",
                    division_grid_version_id=self.own_version,
                ),
            ]
        )
        await self.session.flush()
        system_tier_id = version.tiers[0].id
        own_tier_ids = (
            await self.session.scalars(
                sa.select(models.DivisionGridTier.id).where(models.DivisionGridTier.version_id == self.own_version)
            )
        ).all()
        admin = self.caller("read", "update")
        activate = {"workspace_id": self.own, "version_id": version.id}

        self.assertEqual(await self.error_code("grid_version_activate", admin, **activate), "conflict")

        mapped = await self.envelope(
            "grid_mapping_put",
            admin,
            source_version_id=self.own_version,
            target_version_id=version.id,
            payload={
                "name": "onto system",
                "rules": [
                    {"source_tier_id": tier_id, "target_tier_id": system_tier_id, "weight": 1.0}
                    for tier_id in own_tier_ids
                ],
            },
        )
        self.assertTrue(mapped["ok"], mapped)
        self.assertTrue(mapped["data"]["is_complete"])

        activated = await self.envelope("grid_version_activate", admin, **activate)

        self.assertTrue(activated["ok"], activated)
        self.assertEqual(
            await self.session.scalar(
                sa.select(models.WorkspaceDivisionGridDefault.version_id).where(
                    models.WorkspaceDivisionGridDefault.workspace_id == self.own,
                    models.WorkspaceDivisionGridDefault.discipline == "overwatch",
                )
            ),
            version.id,
        )
        self.assertIsNone(
            await self.session.scalar(
                sa.select(models.DivisionGrid.workspace_id).where(models.DivisionGrid.id == system.id)
            )
        )

    async def test_readiness_naming_a_vanished_pinned_version_is_404_not_500(self):
        """The pinned-version set is cached; an entry for a version deleted since (or by a racing delete) must
        answer like a missing version, not crash the readiness, save and activation that read it."""
        gone = 9_000_000_000_000 + uuid.uuid4().int % 10**9
        service_module = sys.modules[DivisionGridService.__module__]

        async def stale_source_ids(*_args: Any, **_kwargs: Any) -> set[int]:
            return {gone}

        with patch.object(service_module, "get_workspace_source_version_ids", stale_source_ids):
            code = await self.error_code(
                "grid_version_readiness",
                self.caller("read"),
                workspace_id=self.own,
                version_id=self.own_version,
            )

        self.assertEqual(code, "not_found")
