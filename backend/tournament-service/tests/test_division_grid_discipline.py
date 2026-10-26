"""Grid creation, ownership and portable files exercised through real service consumers."""

from __future__ import annotations

import asyncio
import copy
import sys
import uuid
from datetime import date
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import pytest
import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException
from shared.repository.workspace import WorkspaceRepository
from shared.services.division_grid import cache
from shared.services.division_grid.access import (
    get_effective_division_grid,
    get_effective_division_grid_version,
    get_effective_division_grid_version_ids,
    get_workspace_division_grid_version_id,
    tournament_effective_version_id_expr,
)
from shared.services.ontology import project_disciplines
from shared.testing import create_test_async_engine
from shared.testing.cache import configure_test_cache
from shared.testing.db import ensure_test_postgres
from src import schemas
from src.rpc import _helpers as rpc_helpers
from src.rpc import integrations
from src.services.admin.tournament import AdminTournamentService
from src.services.division_grid.marketplace import MarketplaceService
from src.services.division_grid.portable import PortableService
from src.services.division_grid.service import DivisionGridService
from src.services.registration._common import RegistrationCommonService
from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

_TIER = {
    "slug": "one",
    "number": 9,
    "name": "Organiser rank",
    "sort_order": 0,
    "rank_min": 0,
    "rank_max": None,
    "icon_url": "/tier.png",
}


def document(*, version="division-grid/v1", discipline=None, **bounds):
    result = {
        "schema_version": version,
        "slug": "portable",
        "name": "Portable",
        "versions": [{"version": 1, "label": "v1", "status": "published", "tiers": [{**_TIER, **bounds}]}],
    }
    if discipline is not None:
        result["discipline"] = discipline
    return result


@pytest.mark.parametrize(
    "versions",
    [
        None,
        7,
        "bad",
        {},
        [None],
        [7],
        [{"version": 1, "label": "v1", "status": "published", "tiers": None}],
        [{"version": 1, "label": "v1", "status": "published", "tiers": 7}],
        [{"version": 1, "label": "v1", "status": "published", "tiers": [None]}],
    ],
)
def test_malformed_legacy_containers_are_validation_errors(versions):
    raw = document()
    raw["versions"] = versions
    with pytest.raises(ValidationError):
        schemas.DivisionGridPortableDocument.model_validate(raw)


@pytest.mark.parametrize(
    "bounds",
    [
        {"ow_rank_min": 123, "native_rank_min": 456},
        {"ow_rank_max": None, "native_rank_max": 456},
        {"ow_rank_max": 456, "native_rank_max": 123},
    ],
)
def test_conflicting_legacy_and_native_bounds_are_not_discarded(bounds):
    with pytest.raises(ValidationError, match="conflicting v1 tier bounds"):
        schemas.DivisionGridPortableDocument.model_validate(document(**bounds))


def test_legacy_translation_preserves_input_and_equal_bounds():
    raw = document(ow_rank_min=123, native_rank_min=123, ow_rank_max=456)
    before = copy.deepcopy(raw)
    parsed = schemas.DivisionGridPortableDocument.model_validate(raw)
    assert raw == before
    assert (parsed.schema_version, parsed.discipline) == ("division-grid/v2", "overwatch")
    assert (parsed.versions[0].tiers[0].native_rank_min, parsed.versions[0].tiers[0].native_rank_max) == (123, 456)
    assert "ow_rank" not in parsed.model_dump_json()
    with pytest.raises(ValidationError):
        schemas.DivisionGridPortableDocument.model_validate(document(discipline="lol"))


class GridOwnerServiceTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop

    async def asyncSetUp(self):
        ensure_test_postgres()
        configure_test_cache()
        self.engine = create_test_async_engine()
        self.connection = await self.engine.connect()
        self.transaction = await self.connection.begin()
        # Owner creation commits internally; keep it inside this rollback-only PostgreSQL transaction.
        self.session = AsyncSession(
            bind=self.connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        await project_disciplines(self.session)
        self.tag = uuid.uuid4().hex
        self.workspace = models.Workspace(
            slug=self.tag, name=self.tag, disciplines_enabled=["overwatch", "lol"], division_grid_defaults=[]
        )
        self.session.add(self.workspace)
        await self.session.flush()
        self.workspace_id = self.workspace.id
        self.grids = DivisionGridService()
        self.portable = PortableService()
        self.admin = AdminTournamentService()

    async def asyncTearDown(self):
        await cache.invalidate_workspace(self.workspace_id)
        await self.session.close()
        await self.transaction.rollback()
        remaining = await self.connection.scalar(
            sa.select(sa.func.count()).select_from(models.Workspace).where(models.Workspace.id == self.workspace_id)
        )
        self.assertEqual(remaining, 0)
        await self.connection.close()
        await self.engine.dispose()

    async def grid(self, discipline, *, tiered=True):
        grid = await self.grids.create_grid(
            self.session,
            self.workspace.id,
            schemas.DivisionGridCreate(slug=uuid.uuid4().hex, name=discipline, discipline=discipline),
        )
        if discipline == "lol" and tiered:
            # The organiser's own tier replaces the seeded League ladder: a grid apart from both games' ladders.
            seeded = grid.versions[0].id
            version = await self.grids.create_version(
                self.session,
                self.workspace.id,
                grid.id,
                schemas.DivisionGridVersionCreate(
                    label="LoL",
                    tiers=[schemas.DivisionGridTierWrite(**_TIER, native_rank_min=123, native_rank_max=456)],
                ),
            )
            version.status = "published"
            await self.grids.delete_version(self.session, seeded)
            await self.session.flush()
            await self.session.refresh(grid)
        return grid

    def tournament_data(self, **kwargs):
        return schemas.TournamentCreate(
            workspace_id=self.workspace.id,
            name=uuid.uuid4().hex,
            start_date=date.today(),
            end_date=date.today(),
            discipline="lol",
            **kwargs,
        )

    async def test_create_seeds_lols_ladder_and_disabled_creation_writes_nothing(self):
        grid = await self.grid("lol", tiered=False)
        self.assertEqual((grid.discipline, grid.versions[0].tiers[0].slug), ("lol", "challenger"))
        self.workspace.disciplines_enabled = ["overwatch"]
        await self.session.flush()
        with self.assertRaises(BaseAPIException) as caught:
            await self.grid("lol")
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(
            await self.session.scalar(
                sa.select(sa.func.count())
                .select_from(models.DivisionGrid)
                .where(models.DivisionGrid.workspace_id == self.workspace.id)
            ),
            1,
        )

    async def test_tournament_refusal_leaves_no_owner_and_accepts_only_tiered_own_grid(self):
        ow = await self.grid("overwatch")
        await self.grids.activate_version(self.session, workspace=self.workspace, version_id=ow.versions[0].id)
        with self.assertRaises(BaseAPIException) as caught:
            await self.admin.create_tournament(
                self.session, self.tournament_data(division_grid_version_id=ow.versions[0].id)
            )
        self.assertEqual(caught.exception.status_code, 422)
        self.assertIn("division_grid_discipline_mismatch", str(caught.exception.detail))
        self.assertEqual(
            await self.session.scalar(
                sa.select(sa.func.count())
                .select_from(models.Tournament)
                .where(models.Tournament.workspace_id == self.workspace.id)
            ),
            0,
        )
        lol = await self.grid("lol")
        tournament = await self.admin.create_tournament(
            self.session, self.tournament_data(division_grid_version_id=lol.versions[0].id)
        )
        self.assertEqual(tournament.division_grid_version_id, lol.versions[0].id)
        with self.assertRaises(BaseAPIException):
            await self.admin.update_tournament(
                self.session, tournament.id, schemas.TournamentUpdate(division_grid_version_id=ow.versions[0].id)
            )
        self.assertEqual(tournament.division_grid_version_id, lol.versions[0].id)
        runtime = await RegistrationCommonService().get_tournament_grid(self.session, tournament.id)
        self.assertEqual(runtime.resolve_division(200).number, 9)
        self.assertEqual(runtime.resolve_division_from_native_rank(123).number, 9)

    async def test_registration_model_read_uses_scoped_default_after_cache_warming(self):
        ow = await self.grid("overwatch")
        lol = await self.grid("lol")
        await self.grids.activate_version(self.session, workspace=self.workspace, version_id=ow.versions[0].id)
        await self.session.commit()  # the activation request's commit runs its cache invalidation
        tournament = models.Tournament(
            workspace_id=self.workspace.id, name="Historical LoL", slug=self.tag, discipline="lol"
        )
        self.session.add(tournament)
        await self.session.flush()
        await get_effective_division_grid(self.session, self.workspace.id, discipline="overwatch")
        runtime = await RegistrationCommonService().get_tournament_grid(self.session, tournament.id)
        self.assertEqual(runtime.tiers[0].slug, "challenger")
        await self.grids.activate_version(self.session, workspace=self.workspace, version_id=lol.versions[0].id)
        await self.session.commit()
        runtime = await RegistrationCommonService().get_tournament_grid(self.session, tournament.id)
        self.assertEqual(runtime.resolve_division_from_native_rank(456).number, 9)

    async def test_activation_refuses_disabled_game_and_ignores_other_games_mapping_sources(self):
        ow = await self.grid("overwatch")
        lol = await self.grid("lol")
        self.session.add(
            models.Tournament(
                workspace_id=self.workspace.id, name="OW", slug=self.tag, division_grid_version_id=ow.versions[0].id
            )
        )
        await self.session.flush()
        self.workspace.disciplines_enabled = ["overwatch"]
        with self.assertRaises(BaseAPIException) as caught:
            await self.grids.activate_version(self.session, workspace=self.workspace, version_id=lol.versions[0].id)
        self.assertEqual(caught.exception.status_code, 422)
        self.assertEqual(self.workspace.default_division_grid_versions, {})
        self.workspace.disciplines_enabled = ["overwatch", "lol"]
        await self.grids.activate_version(self.session, workspace=self.workspace, version_id=lol.versions[0].id)
        self.assertEqual(self.workspace.default_division_grid_versions, {"lol": lol.versions[0].id})

    async def test_postgres_create_use_clone_resolve_and_portable_import_smoke(self):
        lol = await self.grid("lol")
        cloned = await self.grids.clone_version(self.session, lol.versions[0].id)
        self.assertEqual((cloned.grid.discipline, cloned.tiers[0].native_rank_max), ("lol", 456))
        await self.grids.activate_version(self.session, workspace=self.workspace, version_id=lol.versions[0].id)
        runtime = await get_effective_division_grid(self.session, self.workspace.id, discipline="lol")
        self.assertEqual(runtime.resolve_division(200).number, 9)
        # Export is a separate request in production: reload the versions after cloning in this shared transaction.
        await self.session.refresh(lol, ["versions"])
        exported = await self.portable.export_portable_document(self.session, grid_id=lol.id)
        self.assertEqual((exported.schema_version, exported.discipline), ("division-grid/v2", "lol"))
        imported = await self.portable.import_portable_document(
            self.session,
            workspace_id=self.workspace.id,
            request=schemas.DivisionGridPortableImportRequest(document=exported, mode="copy"),
        )
        self.assertEqual((imported.discipline, len(imported.versions)), ("lol", 2))
        legacy = await self.portable.import_portable_document(
            self.session,
            workspace_id=self.workspace.id,
            request=schemas.DivisionGridPortableImportRequest(document=document(ow_rank_min=123, ow_rank_max=456)),
        )
        self.assertEqual((legacy.discipline, legacy.versions[0].tiers[0].native_rank_min), ("overwatch", 123))
        print(
            "PostgreSQL create/use/clone/resolve/import: LoL rank200=division9; native bounds123..456 retained; v1 imported as OW, exports v2; rollback asserted in teardown"
        )

    async def test_portable_and_marketplace_refuse_disabled_discipline_before_writes(self):
        lol = await self.grid("lol")
        target = models.Workspace(slug=self.tag + "-target", name="OW only", disciplines_enabled=["overwatch"])
        self.session.add(target)
        await self.session.flush()
        with self.assertRaises(BaseAPIException):
            await self.portable.import_portable_document(
                self.session,
                workspace_id=target.id,
                request=schemas.DivisionGridPortableImportRequest(
                    document=document(version="division-grid/v2", discipline="lol")
                ),
            )
        with self.assertRaises(BaseAPIException):
            await MarketplaceService().import_division_grids(
                self.session,
                None,
                target_workspace=target,
                source_workspace=self.workspace,
                source_grids=[lol],
                include_icons=False,
            )
        self.assertEqual(
            await self.session.scalar(
                sa.select(sa.func.count())
                .select_from(models.DivisionGrid)
                .where(models.DivisionGrid.workspace_id == target.id)
            ),
            0,
        )
        target.disciplines_enabled = ["overwatch", "lol"]
        result = await MarketplaceService().import_division_grids(
            self.session,
            None,
            target_workspace=target,
            source_workspace=self.workspace,
            source_grids=[lol],
            include_icons=False,
        )
        copied = await self.grids.get_grid_by_id(self.session, result.imported_grids[0].target_grid_id)
        self.assertEqual((copied.discipline, copied.versions[0].tiers[0].native_rank_max), ("lol", 456))

    async def test_custom_defaults_survive_activation_cycles_across_every_resolver(self):
        ow = await self.grid("overwatch")
        ow_version = await self.grids.create_version(
            self.session,
            self.workspace.id,
            ow.id,
            schemas.DivisionGridVersionCreate(
                label="Custom OW", tiers=[schemas.DivisionGridTierWrite(**{**_TIER, "number": 4, "name": "Custom OW"})]
            ),
        )
        await self.grids.publish_version(self.session, ow_version.id)
        lol = await self.grid("lol")
        lol_version = lol.versions[0]
        events = [
            models.Tournament(workspace_id=self.workspace.id, name=code, slug=self.tag + code, discipline=code)
            for code in ("overwatch", "lol")
        ]
        pin = models.Tournament(
            workspace_id=self.workspace.id,
            name="Pinned",
            slug=self.tag + "-pin",
            division_grid_version_id=ow_version.id,
        )
        self.session.add_all([*events, pin])
        await self.session.flush()
        # Warm both keys before each activation, including absent LoL's None cache entry.
        for code in ("overwatch", "lol"):
            await get_workspace_division_grid_version_id(self.session, self.workspace.id, code)
        await self.grids.activate_version(self.session, workspace=self.workspace, version_id=ow_version.id)
        await self.session.commit()  # the activation request's commit runs its cache invalidation
        for code in ("overwatch", "lol"):
            await get_workspace_division_grid_version_id(self.session, self.workspace.id, code)
        await self.grids.activate_version(self.session, workspace=self.workspace, version_id=lol_version.id)
        await self.session.commit()
        new_ow = await self.grids.clone_version(self.session, ow_version.id)
        await self.grids.publish_version(self.session, new_ow.id)
        await self.grids.upsert_mapping(
            self.session,
            ow_version.id,
            new_ow.id,
            schemas.DivisionGridMappingWrite(
                name="Unchanged bands",
                rules=[
                    schemas.DivisionGridMappingRuleWrite(
                        source_tier_id=ow_version.tiers[0].id,
                        target_tier_id=new_ow.tiers[0].id,
                        weight=1.0,
                        is_primary=True,
                    )
                ],
            ),
        )
        for expected_ow in (ow_version, new_ow):
            if expected_ow is new_ow:
                await self.grids.activate_version(self.session, workspace=self.workspace, version_id=new_ow.id)
                await self.session.commit()
            expected = {events[0].id: expected_ow.id, events[1].id: lol_version.id, pin.id: ow_version.id}
            for _ in range(2):
                self.assertEqual(await get_effective_division_grid_version_ids(self.session, expected), expected)
                rows = (
                    await self.session.execute(
                        sa.select(
                            models.Tournament.id, tournament_effective_version_id_expr(models.Tournament.id)
                        ).where(models.Tournament.id.in_(expected))
                    )
                ).all()
                self.assertEqual(dict(rows), expected)
                for event in [*events, pin]:
                    runtime = await get_effective_division_grid(self.session, self.workspace.id, event.id)
                    full = await get_effective_division_grid_version(self.session, self.workspace.id, event.id)
                    registration = await RegistrationCommonService().get_tournament_grid(self.session, event.id)
                    self.assertEqual((runtime.version_id, full.id, registration.version_id), (expected[event.id],) * 3)
                    self.assertEqual(runtime.resolve_division(200).number, 9 if event.discipline == "lol" else 4)
            self.assertEqual(
                self.workspace.default_division_grid_versions, {"overwatch": expected_ow.id, "lol": lol_version.id}
            )
        payload = schemas.WorkspaceRead.model_validate(self.workspace, from_attributes=True).model_dump()
        self.assertEqual(payload["default_division_grid_versions"], {"overwatch": new_ow.id, "lol": lol_version.id})
        self.assertEqual(set(payload["effective_division_grid_versions"]), {"overwatch", "lol"})
        print(
            "PostgreSQL defaults smoke: custom OW→LoL→new OW; warm SQL/batch/full-model/runtime/registration agree; pin retained"
        )

    async def test_activation_refusal_rollback_and_delete_guards_preserve_the_other_game(self):
        ow, lol = await self.grid("overwatch"), await self.grid("lol")
        for grid in (ow, lol):
            await self.grids.activate_version(self.session, workspace=self.workspace, version_id=grid.versions[0].id)
        expected = dict(self.workspace.default_division_grid_versions)
        other = models.Workspace(slug=self.tag + "-other", name="Other", disciplines_enabled=["overwatch", "lol"])
        self.session.add(other)
        await self.session.flush()
        foreign = await self.grids.create_grid(
            self.session, other.id, schemas.DivisionGridCreate(slug="foreign", name="Foreign", discipline="overwatch")
        )
        with self.assertRaises(BaseAPIException):
            await self.grids.activate_version(self.session, workspace=self.workspace, version_id=foreign.versions[0].id)
        self.assertEqual(self.workspace.default_division_grid_versions, expected)
        draft = await self.grids.clone_version(self.session, ow.versions[0].id)
        with self.assertRaises(BaseAPIException):
            await self.grids.activate_version(self.session, workspace=self.workspace, version_id=draft.id)
        self.assertEqual(self.workspace.default_division_grid_versions, expected)
        await self.grids.publish_version(self.session, draft.id)
        savepoint = await self.session.begin_nested()
        await self.grids.activate_version(self.session, workspace=self.workspace, version_id=draft.id)
        await savepoint.rollback()
        await self.session.refresh(self.workspace)
        await cache.invalidate_workspace(self.workspace.id)
        self.assertEqual(self.workspace.default_division_grid_versions, expected)
        with self.assertRaises(BaseAPIException):
            await self.grids.delete_version(self.session, lol.versions[0].id)
        with self.assertRaises(BaseAPIException):
            await self.grids.update_grid(self.session, grid_id=lol.id, data=schemas.DivisionGridUpdate(archived=True))
        with self.assertRaises(BaseAPIException):
            await self.grids.delete_grid(self.session, lol.id)
        await self.grids.delete_grid(self.session, lol.id, force=True)
        await self.session.refresh(self.workspace, ["division_grid_defaults"])
        self.assertEqual(self.workspace.default_division_grid_versions, {"overwatch": expected["overwatch"]})
        self.assertEqual(
            await get_workspace_division_grid_version_id(self.session, self.workspace.id, "overwatch"),
            expected["overwatch"],
        )
        await WorkspaceRepository().clear_default_grid_version(
            self.session, workspace_id=self.workspace.id, version_ids=[draft.id]
        )
        await self.session.refresh(self.workspace, ["division_grid_defaults"])
        self.assertEqual(self.workspace.default_division_grid_versions, {"overwatch": expected["overwatch"]})

    async def test_create_from_a_version_copies_its_published_tiers_and_activates_nothing(self):
        source = (await self.grid("lol")).versions[0]
        copy = await self.grids.create_grid(
            self.session,
            self.workspace.id,
            schemas.DivisionGridCreate(name="Copy", discipline="lol", from_version_id=source.id),
        )
        ladder = await self.grids.create_grid(
            self.session, self.workspace.id, schemas.DivisionGridCreate(name="Ladder", discipline="lol")
        )
        self.assertEqual((copy.slug, ladder.slug), ("lol-grid", "lol-grid-2"))
        (v1,) = copy.versions
        self.assertEqual((v1.version, v1.status, v1.label), (1, "published", "LoL"))
        self.assertIsNotNone(v1.published_at)
        fields = ("slug", "number", "name", "sort_order", "rank_min", "rank_max", "icon_url")
        fields += ("native_rank_min", "native_rank_max")
        self.assertEqual(
            [[getattr(tier, field) for field in fields] for tier in v1.tiers],
            [[getattr(tier, field) for field in fields] for tier in source.tiers],
        )
        self.assertEqual((v1.tiers[0].native_rank_min, v1.tiers[0].native_rank_max), (123, 456))
        self.assertEqual(
            (ladder.versions[0].label, ladder.versions[0].tiers[0].slug),
            ("Default League of Legends grid", "challenger"),
        )
        await self.session.refresh(self.workspace, ["division_grid_defaults"])
        self.assertEqual(self.workspace.default_division_grid_versions, {})

    async def test_create_from_a_version_refuses_another_game_a_draft_and_another_workspace(self):
        ow = await self.grid("overwatch")
        draft = await self.grids.clone_version(self.session, ow.versions[0].id)
        other = models.Workspace(slug=self.tag + "-other", name="Other", disciplines_enabled=["overwatch"])
        self.session.add(other)
        await self.session.flush()
        foreign = await self.grids.create_grid(self.session, other.id, schemas.DivisionGridCreate(name="Foreign"))
        for version_id, discipline, status in (
            (ow.versions[0].id, "lol", 422),
            (draft.id, "overwatch", 409),
            (foreign.versions[0].id, "overwatch", 404),
        ):
            with self.subTest(status=status), self.assertRaises(BaseAPIException) as caught:
                await self.grids.create_grid(
                    self.session,
                    self.workspace.id,
                    schemas.DivisionGridCreate(name="Copy", discipline=discipline, from_version_id=version_id),
                )
            self.assertEqual(caught.exception.status_code, status)
            if status == 422:
                self.assertIn("division_grid_discipline_mismatch", str(caught.exception.detail))
        self.assertEqual(
            await self.session.scalar(
                sa.select(sa.func.count())
                .select_from(models.DivisionGrid)
                .where(models.DivisionGrid.workspace_id == self.workspace.id)
            ),
            1,
        )

    async def test_workspace_grid_list_counts_the_tournaments_pinned_to_each_grid(self):
        ow, lol = await self.grid("overwatch"), await self.grid("lol")
        clone = await self.grids.clone_version(self.session, ow.versions[0].id)
        self.session.add_all(
            [
                models.Tournament(
                    workspace_id=self.workspace.id, name=f"Pinned {index}", slug=f"{self.tag}-{index}", **pin
                )
                for index, pin in enumerate(
                    [{"division_grid_version_id": ow.versions[0].id}, {"division_grid_version_id": clone.id}, {}]
                )
            ]
        )
        await self.session.flush()
        broker = CapturingBroker()
        integrations.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        identity = make_identity(
            workspaces=[
                {
                    "workspace_id": self.workspace.id,
                    "rbac_roles": [],
                    "rbac_permissions": [{"resource": "division_grid", "action": "read"}],
                }
            ]
        )
        with patch.object(rpc_helpers.db, "async_session_maker", FakeSessionMaker(self.session)):
            envelope = await broker.handlers["rpc.tournament.grid_workspace_list"](
                {"identity": identity, "workspace_id": self.workspace.id}, None
            )
        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual({grid["id"]: grid["tournament_count"] for grid in envelope["data"]}, {ow.id: 2, lol.id: 0})
