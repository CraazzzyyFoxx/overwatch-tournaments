from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
import sqlalchemy as sa

from shared.division_grid import DivisionGrid, normalize_native_ranks_to_grid

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


models = importlib.import_module("shared.models")
schemas = importlib.import_module("src.schemas")
division_service = importlib.import_module("src.services.division_grid.service")
grid_service = division_service.division_grid_service


def _write_tier(
    tier_id, slug, rank_min, rank_max, *, name=None, number=1, sort_order=0, icon_url="/i.png", ow_min=None, ow_max=None
):
    return schemas.DivisionGridTierWrite(
        id=tier_id,
        slug=slug,
        number=number,
        name=name or slug,
        sort_order=sort_order,
        rank_min=rank_min,
        rank_max=rank_max,
        icon_url=icon_url,
        native_rank_min=ow_min,
        native_rank_max=ow_max,
    )


def _active_tier(tier_id, slug, rank_min, rank_max, *, name=None, number=1, sort_order=0):
    return SimpleNamespace(
        id=tier_id,
        slug=slug,
        name=name or slug,
        number=number,
        sort_order=sort_order,
        rank_min=rank_min,
        rank_max=rank_max,
        icon_url="/i.png",
        native_rank_min=None,
        native_rank_max=None,
    )


# ── classification ────────────────────────────────────────────────────────────


def test_classify_cosmetic_when_only_labels_change() -> None:
    active = [_active_tier(1, "bronze", 1000, 1099, name="Bronze")]
    payload = [_write_tier(1, "bronze", 1000, 1099, name="Bronze Renamed")]
    assert division_service._classify_tier_change(active, payload) == "cosmetic"


def test_classify_structural_when_rank_changes() -> None:
    active = [_active_tier(1, "bronze", 1000, 1099)]
    payload = [_write_tier(1, "bronze", 1000, 1150)]
    assert division_service._classify_tier_change(active, payload) == "structural"


def test_classify_structural_when_tier_added() -> None:
    active = [_active_tier(1, "bronze", 1000, 1099)]
    payload = [_write_tier(1, "bronze", 1000, 1099), _write_tier(None, "silver", 1100, 1199)]
    assert division_service._classify_tier_change(active, payload) == "structural"


def test_classify_structural_when_tier_removed() -> None:
    active = [_active_tier(1, "bronze", 1000, 1099), _active_tier(2, "silver", 1100, 1199)]
    payload = [_write_tier(1, "bronze", 1000, 1099)]
    assert division_service._classify_tier_change(active, payload) == "structural"


def test_classify_cosmetic_ignores_slug_and_order_changes() -> None:
    active = [_active_tier(1, "bronze", 1000, 1099, sort_order=0)]
    payload = [_write_tier(1, "bronze-renamed", 1000, 1099, sort_order=3)]
    assert division_service._classify_tier_change(active, payload) == "cosmetic"


# ── save orchestration ────────────────────────────────────────────────────────


def _grid_with_active():
    active = SimpleNamespace(
        id=100,
        version=1,
        label="v1",
        status="published",
        tiers=[_active_tier(1, "bronze", 1000, 1099)],
    )
    grid = SimpleNamespace(id=1, name="Ladder", discipline="overwatch", versions=[active])
    return grid, active


def _readiness(is_ready):
    return schemas.DivisionGridActivationReadiness(
        target_version_id=200,
        is_ready=is_ready,
        used_source_version_ids=[100, 200],
        missing_mapping_version_ids=[] if is_ready else [100],
    )


def test_save_cosmetic_updates_in_place_without_new_version() -> None:
    async def run():
        grid, active = _grid_with_active()
        workspace = SimpleNamespace(
            id=4, default_division_grid_versions={"overwatch": 100}, disciplines_enabled=["overwatch"]
        )
        session = SimpleNamespace(flush=AsyncMock())
        data = schemas.DivisionGridSaveRequest(
            name="Ladder", tiers=[_write_tier(1, "bronze", 1000, 1099, name="Bronze!")]
        )
        with (
            patch.object(grid_service, "_resolve_workspace_grid", AsyncMock(return_value=grid)),
            patch.object(grid_service, "_apply_cosmetic", AsyncMock()) as apply_cosmetic,
            patch.object(grid_service, "create_version", AsyncMock()) as create_version,
            patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)),
            patch.object(grid_service, "get_activation_readiness", AsyncMock(return_value=_readiness(True))),
        ):
            outcome = await grid_service.save_workspace_grid(session, workspace=workspace, data=data)
        assert outcome.mode == "in_place"
        assert outcome.saved_version_id == 100
        apply_cosmetic.assert_awaited_once()
        create_version.assert_not_called()

    asyncio.run(run())


def test_save_structural_clean_creates_version_and_activates() -> None:
    async def run():
        grid, active = _grid_with_active()
        new_version = SimpleNamespace(id=200, version=2, label="v2", tiers=[_active_tier(11, "bronze", 1000, 1099)])
        source_version = SimpleNamespace(id=100, label="v1", tiers=active.tiers)
        workspace = SimpleNamespace(
            id=4, default_division_grid_versions={"overwatch": 100}, disciplines_enabled=["overwatch"]
        )
        session = SimpleNamespace(flush=AsyncMock())
        gen = SimpleNamespace(rules=[], conflicts=[], is_complete=True)
        data = schemas.DivisionGridSaveRequest(
            tiers=[_write_tier(1, "bronze", 1000, 1099), _write_tier(None, "silver", 1100, 1199)]
        )
        with (
            patch.object(grid_service, "_resolve_workspace_grid", AsyncMock(return_value=grid)),
            patch.object(grid_service, "create_version", AsyncMock(return_value=new_version)),
            patch.object(grid_service, "publish_version", AsyncMock()),
            patch.object(division_service, "get_workspace_source_version_ids", AsyncMock(return_value={100})),
            patch.object(grid_service, "get_version", AsyncMock(return_value=source_version)),
            patch.object(division_service.automap, "generate_mapping_rules", Mock(return_value=gen)),
            patch.object(grid_service, "_persist_mapping", AsyncMock()) as persist,
            patch.object(grid_service, "get_activation_readiness", AsyncMock(return_value=_readiness(True))),
            patch.object(grid_service, "activate_version", AsyncMock()) as activate,
            patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)),
        ):
            outcome = await grid_service.save_workspace_grid(session, workspace=workspace, data=data)
        assert outcome.mode == "new_version_activated"
        assert outcome.saved_version_id == 200
        activate.assert_awaited_once()
        persist.assert_awaited()

    asyncio.run(run())


def test_save_structural_with_conflicts_stays_pending() -> None:
    async def run():
        grid, active = _grid_with_active()
        new_version = SimpleNamespace(id=200, version=2, label="v2", tiers=[_active_tier(11, "bronze", 1000, 1099)])
        source_version = SimpleNamespace(id=100, label="v1", tiers=active.tiers)
        workspace = SimpleNamespace(
            id=4, default_division_grid_versions={"overwatch": 100}, disciplines_enabled=["overwatch"]
        )
        session = SimpleNamespace(flush=AsyncMock())
        gen = SimpleNamespace(rules=[], conflicts=[SimpleNamespace(source_tier_id=1)], is_complete=False)
        data = schemas.DivisionGridSaveRequest(tiers=[_write_tier(None, "silver", 5000, 5099)])
        with (
            patch.object(grid_service, "_resolve_workspace_grid", AsyncMock(return_value=grid)),
            patch.object(grid_service, "create_version", AsyncMock(return_value=new_version)),
            patch.object(grid_service, "publish_version", AsyncMock()),
            patch.object(division_service, "get_workspace_source_version_ids", AsyncMock(return_value={100})),
            patch.object(grid_service, "get_version", AsyncMock(return_value=source_version)),
            patch.object(division_service.automap, "generate_mapping_rules", Mock(return_value=gen)),
            patch.object(grid_service, "_persist_mapping", AsyncMock()),
            patch.object(grid_service, "get_activation_readiness", AsyncMock(return_value=_readiness(False))),
            patch.object(grid_service, "activate_version", AsyncMock()) as activate,
            patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)),
        ):
            outcome = await grid_service.save_workspace_grid(session, workspace=workspace, data=data)
        assert outcome.mode == "new_version_pending"
        activate.assert_not_called()

    asyncio.run(run())


# ── delete_grid ───────────────────────────────────────────────────────────────


def _grid_for_delete(workspace_id=4, version_ids=(100,)):
    versions = [SimpleNamespace(id=vid) for vid in version_ids]
    return SimpleNamespace(id=7, workspace_id=workspace_id, discipline="overwatch", versions=versions)


def test_delete_grid_removes_unused_grid() -> None:
    async def run():
        grid = _grid_for_delete()
        session = SimpleNamespace(
            delete=AsyncMock(),
            flush=AsyncMock(),
            scalar=AsyncMock(side_effect=[999]),  # default version id (not in grid)
            # TournamentRepository.count -> session.execute(...).scalar_one()
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one=Mock(return_value=0))),
            info={},
        )
        with patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)):
            await grid_service.delete_grid(session, 7)
        session.delete.assert_awaited_once_with(grid)

    asyncio.run(run())


def test_delete_grid_rejects_workspace_default() -> None:
    async def run():
        grid = _grid_for_delete(version_ids=(100, 101))
        session = SimpleNamespace(
            delete=AsyncMock(),
            flush=AsyncMock(),
            scalar=AsyncMock(side_effect=[100]),  # default points at a version in this grid
        )
        with (
            patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)),
            pytest.raises(Exception) as caught,
        ):
            await grid_service.delete_grid(session, 7)
        assert getattr(caught.value, "status_code", None) == 409
        session.delete.assert_not_called()

    asyncio.run(run())


def test_delete_grid_rejects_when_used_by_tournaments() -> None:
    async def run():
        grid = _grid_for_delete()
        session = SimpleNamespace(
            delete=AsyncMock(),
            flush=AsyncMock(),
            scalar=AsyncMock(side_effect=[None]),  # no default
            # 3 tournaments use it, via TournamentRepository.count
            execute=AsyncMock(return_value=SimpleNamespace(scalar_one=Mock(return_value=3))),
        )
        with (
            patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)),
            pytest.raises(Exception) as caught,
        ):
            await grid_service.delete_grid(session, 7)
        assert getattr(caught.value, "status_code", None) == 409
        session.delete.assert_not_called()

    asyncio.run(run())


def test_delete_grid_rejects_system_grid() -> None:
    async def run():
        grid = _grid_for_delete(workspace_id=None)
        session = SimpleNamespace(delete=AsyncMock(), flush=AsyncMock(), scalar=AsyncMock())
        with (
            patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)),
            pytest.raises(Exception) as caught,
        ):
            await grid_service.delete_grid(session, 7)
        assert getattr(caught.value, "status_code", None) == 403
        assert caught.value.detail[0]["code"] == "division_grid_read_only"
        session.delete.assert_not_called()

    asyncio.run(run())


def test_delete_grid_force_bypasses_guards_and_clears_default() -> None:
    async def run():
        grid = _grid_for_delete(version_ids=(100, 101))
        session = SimpleNamespace(
            delete=AsyncMock(),
            flush=AsyncMock(),
            execute=AsyncMock(),
            scalar=AsyncMock(),
            info={},
        )
        with patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)):
            await grid_service.delete_grid(session, 7, force=True)
        session.delete.assert_awaited_once_with(grid)
        session.execute.assert_awaited()  # workspace default cleared
        session.scalar.assert_not_called()  # guards skipped

    asyncio.run(run())


def test_delete_grid_force_still_rejects_system_grid() -> None:
    async def run():
        grid = _grid_for_delete(workspace_id=None)
        session = SimpleNamespace(delete=AsyncMock(), flush=AsyncMock(), execute=AsyncMock())
        with (
            patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)),
            pytest.raises(Exception) as caught,
        ):
            await grid_service.delete_grid(session, 7, force=True)
        assert getattr(caught.value, "status_code", None) == 403
        session.delete.assert_not_called()

    asyncio.run(run())


def test_save_uses_explicit_grid_id_over_workspace_resolution() -> None:
    async def run():
        active = SimpleNamespace(
            id=100,
            version=1,
            label="v1",
            status="published",
            tiers=[_active_tier(1, "bronze", 1000, 1099)],
        )
        grid = SimpleNamespace(id=7, name="Imported", workspace_id=4, discipline="overwatch", versions=[active])
        workspace = SimpleNamespace(
            id=4, default_division_grid_versions={"overwatch": 100}, disciplines_enabled=["overwatch"]
        )
        session = SimpleNamespace(flush=AsyncMock())
        data = schemas.DivisionGridSaveRequest(
            grid_id=7, name="Imported", tiers=[_write_tier(1, "bronze", 1000, 1099, name="B!")]
        )
        with (
            patch.object(grid_service, "get_grid_by_id", AsyncMock(return_value=grid)),
            patch.object(grid_service, "_resolve_workspace_grid", AsyncMock()) as resolve,
            patch.object(grid_service, "_apply_cosmetic", AsyncMock()),
            patch.object(grid_service, "get_activation_readiness", AsyncMock(return_value=_readiness(True))),
        ):
            outcome = await grid_service.save_workspace_grid(session, workspace=workspace, data=data)
        resolve.assert_not_called()
        assert outcome.mode == "in_place"
        assert outcome.saved_version_id == 100

    asyncio.run(run())


def test_native_ranges_survive_service_writes_serialization_and_resolution(db_session) -> None:
    async def run() -> None:
        workspace = models.Workspace(slug="p3-native-range-smoke", name="Native range smoke")
        db_session.add(workspace)
        await db_session.flush()
        workspace_id = workspace.id
        grid = models.DivisionGrid(workspace_id=workspace_id, slug="native", name="Native", versions=[])
        db_session.add(grid)
        await db_session.flush()
        try:
            version = await grid_service.create_version(
                db_session,
                workspace_id,
                grid.id,
                schemas.DivisionGridVersionCreate(
                    label="Native bounds",
                    tiers=[
                        _write_tier(None, "top", 2000, None, ow_min=4900, ow_max=4700),
                        _write_tier(None, "base", 1000, 1999, number=2, sort_order=1, ow_min=4000, ow_max=4699),
                    ],
                ),
            )
            payload = schemas.DivisionGridVersionRead.model_validate(version, from_attributes=True).model_dump(
                mode="json"
            )
            assert [(t["native_rank_min"], t["native_rank_max"]) for t in payload["tiers"]] == [
                (4900, 4700),
                (4000, 4699),
            ]
            assert all(not any(key.startswith("ow_rank_") for key in tier) for tier in payload["tiers"])
            runtime = DivisionGrid.from_version(version)
            assert normalize_native_ranks_to_grid({7: {"tank": 4700, "support": 4699}}, runtime) == {
                7: {"tank": 2000, "support": 1000}
            }
            writes = [schemas.DivisionGridTierWrite.model_validate(tier) for tier in payload["tiers"]]
            writes[0].native_rank_max = 4800
            updated = await grid_service.update_version(
                db_session, version.id, schemas.DivisionGridVersionUpdate(tiers=writes)
            )
            cloned = await grid_service.clone_version(db_session, updated.id)
            cloned_payload = schemas.DivisionGridVersionRead.model_validate(cloned, from_attributes=True).model_dump(
                mode="json"
            )
            assert cloned_payload["tiers"][0]["native_rank_max"] == 4800
            runtime = DivisionGrid.from_version(cloned)
            assert runtime.resolve_division_from_native_rank(4700) is None
            assert runtime.resolve_division_from_native_rank(4800).rank_min == 2000
            print("PostgreSQL native bounds: create/read 4900..4700 -> 2000; update/clone 4900..4800; 4700 excluded")
        finally:
            await db_session.rollback()
        try:
            assert (
                await db_session.scalar(
                    sa.select(sa.func.count()).select_from(models.Workspace).where(models.Workspace.id == workspace_id)
                )
                == 0
            )
            print("ROLLBACK confirmed: smoke workspace rows=0")
        finally:
            await db_session.close()

    asyncio.run(run())


_REWRITES = {
    "replace-all": lambda kept: [
        _write_tier(None, "top", 1500, None),
        _write_tier(None, "rest", 0, 1499, number=2, sort_order=1),
    ],
    "swap-last": lambda kept: [*kept[:-1], _write_tier(None, "rookie", 0, 999, number=3, sort_order=2)],
    "append": lambda kept: [*kept, _write_tier(None, "unranked", -500, -1, number=99, sort_order=3)],
    "swap-slugs": lambda kept: [
        kept[0].model_copy(update={"slug": kept[1].slug}),
        kept[1].model_copy(update={"slug": kept[0].slug}),
        kept[2],
    ],
}


@pytest.mark.parametrize("rewrite", list(_REWRITES))
def test_draft_tier_rewrite_is_stored_and_echoed(db_session, rewrite) -> None:
    """PATCH with id-less tiers reusing freed sort_orders/slugs saves, and the response is what a re-read returns."""

    async def run() -> None:
        try:
            workspace = models.Workspace(slug=f"grid-rewrite-{rewrite}", name="Grid rewrite")
            db_session.add(workspace)
            await db_session.flush()
            grid = models.DivisionGrid(workspace_id=workspace.id, slug="rewrite", name="Rewrite", versions=[])
            db_session.add(grid)
            await db_session.flush()
            draft = await grid_service.create_version(
                db_session,
                workspace.id,
                grid.id,
                schemas.DivisionGridVersionCreate(
                    label="Draft",
                    tiers=[
                        _write_tier(None, "top", 2000, None),
                        _write_tier(None, "mid", 1000, 1999, number=2, sort_order=1),
                        _write_tier(None, "low", 0, 999, number=3, sort_order=2),
                    ],
                ),
            )
            payload = schemas.DivisionGridVersionRead.model_validate(draft, from_attributes=True).model_dump(
                mode="json"
            )
            tiers = _REWRITES[rewrite]([schemas.DivisionGridTierWrite.model_validate(t) for t in payload["tiers"]])

            updated = await grid_service.update_version(
                db_session, draft.id, schemas.DivisionGridVersionUpdate(tiers=tiers)
            )

            stored = await db_session.scalars(
                sa.select(models.DivisionGridTier.slug)
                .where(models.DivisionGridTier.version_id == draft.id)
                .order_by(models.DivisionGridTier.sort_order)
            )
            assert list(stored) == [t.slug for t in tiers]
            assert [t.slug for t in updated.tiers] == [t.slug for t in tiers]
        finally:
            await db_session.rollback()

    asyncio.run(run())


def _three_tiers():
    return [
        _write_tier(None, "top", 2000, None),
        _write_tier(None, "mid", 1000, 1999, number=2, sort_order=1),
        _write_tier(None, "low", 0, 999, number=3, sort_order=2),
    ]


async def _published_grid(session, workspace, slug):
    grid = models.DivisionGrid(workspace_id=workspace.id, slug=slug, name=slug, versions=[])
    session.add(grid)
    await session.flush()
    version = await grid_service.create_version(
        session, workspace.id, grid.id, schemas.DivisionGridVersionCreate(label="v1", tiers=_three_tiers())
    )
    published = await grid_service.publish_version(session, version.id)
    session.expire(grid, ["versions"])  # one session stands in for several requests: drop the empty collection
    return grid, published


def test_saving_a_grid_that_is_not_active_leaves_the_active_one_alone(db_session) -> None:
    """Switching grids is the explicit activate; a save that passes readiness only activates the active grid."""

    async def run() -> None:
        try:
            workspace = models.Workspace(slug="grid-save-inactive", name="Grid save inactive")
            db_session.add(workspace)
            await db_session.flush()
            live, live_v1 = await _published_grid(db_session, workspace, "live")
            spare, _ = await _published_grid(db_session, workspace, "spare")
            await grid_service.activate_version(db_session, workspace=workspace, version_id=live_v1.id)
            reshaped = [_write_tier(None, "top", 1000, None), _write_tier(None, "rest", 0, 999, number=2, sort_order=1)]

            spare_save = await grid_service.save_workspace_grid(
                db_session, workspace=workspace, data=schemas.DivisionGridSaveRequest(grid_id=spare.id, tiers=reshaped)
            )
            assert spare_save.readiness.is_ready
            assert spare_save.mode == "new_version_pending"
            assert spare_save.active_version_id == live_v1.id

            live_save = await grid_service.save_workspace_grid(
                db_session, workspace=workspace, data=schemas.DivisionGridSaveRequest(grid_id=live.id, tiers=reshaped)
            )
            assert live_save.mode == "new_version_activated"
            assert live_save.active_version_id == live_save.saved_version_id
        finally:
            await db_session.rollback()

    asyncio.run(run())


def test_in_place_save_can_swap_two_tiers_slugs(db_session) -> None:
    async def run() -> None:
        try:
            workspace = models.Workspace(slug="grid-save-slug-swap", name="Grid slug swap")
            db_session.add(workspace)
            await db_session.flush()
            grid, version = await _published_grid(db_session, workspace, "swap")
            await grid_service.activate_version(db_session, workspace=workspace, version_id=version.id)
            top, mid, low = (
                schemas.DivisionGridTierWrite.model_validate(t, from_attributes=True) for t in version.tiers
            )
            tiers = [top.model_copy(update={"slug": "mid"}), mid.model_copy(update={"slug": "top"}), low]

            saved = await grid_service.save_workspace_grid(
                db_session, workspace=workspace, data=schemas.DivisionGridSaveRequest(grid_id=grid.id, tiers=tiers)
            )

            assert saved.mode == "in_place"
            stored = await db_session.scalars(
                sa.select(models.DivisionGridTier.slug)
                .where(models.DivisionGridTier.version_id == version.id)
                .order_by(models.DivisionGridTier.sort_order)
            )
            assert list(stored) == ["mid", "top", "low"]
        finally:
            await db_session.rollback()

    asyncio.run(run())
