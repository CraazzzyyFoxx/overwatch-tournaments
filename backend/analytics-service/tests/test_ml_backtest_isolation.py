"""A backtest trains, activates and infers for real, yet leaves the registry, model files and analytics rows as they were.

Real database (P4's transferred statistics fixture): the claim is about committed rows and files on disk, which a mock
session cannot falsify. The trainers return the frozen fixture estimators so every fold really registers, activates and
saves artifacts without fitting anything.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared import models
from src.core import config
from src.core.analytics_exports import analytics_exports
from src.domain.ratings import LINEAR, OPENSKILL, POINTS
from src.services.analytics.flows import flows_service
from src.services.ml.inference.runner import run_for_tournament
from src.services.ml.training import orchestrator
from src.services.ml.training.backtest import backtest_service
from src.services.ml.training.registry import registry_service
from src.services.ml.training.splits import tournament_ids_up_to
from tests.test_ml_prediction_parity import load_fixture_models

OW = "overwatch"
PREDICTORS = {"shift_v2", "zero", "points", "linear", "openskill"}
ANALYTICS_TABLES = [table for table in models.MLModelArtifact.metadata.tables.values() if table.schema == "analytics"]


async def _analytics_rows(session: AsyncSession) -> dict[str, list[tuple]]:
    return {
        table.fullname: [
            tuple(row) for row in (await session.execute(sa.select(table).order_by(*table.primary_key.columns))).all()
        ]
        for table in ANALYTICS_TABLES
    }


def _files(root: Path) -> dict[str, tuple[bytes, int]]:
    return {
        path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def test_backtest_leaves_registry_model_files_and_analytics_rows_untouched(stats_parity_database, tmp_path) -> None:
    url, ids = stats_parity_database
    tid, workspace = ids["tournament"], ids["workspace"]
    exports = analytics_exports(OW)
    fixtures = load_fixture_models()
    production_dir = tmp_path / "models"
    saved: list[Path] = []
    save_artifact = orchestrator.save_artifact

    def record_save(obj, path: Path) -> str:
        saved.append(path)
        return save_artifact(obj, path)

    def trained(model):
        return SimpleNamespace(model=model, metrics={"rows": 1.0}, feature_importance={})

    async def check() -> None:
        engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
        try:
            with (
                patch.object(config.settings, "analytics_models_dir", str(production_dir)),
                patch.object(config.settings, "analytics_feature_cache_enabled", False),
                patch.object(orchestrator, "save_artifact", record_save),
                patch.object(
                    exports,
                    "train_performance_v2",
                    lambda df, *, role, val_df=None, devices: trained(fixtures[f"performance_{role}"]),
                ),
                patch.object(exports, "train_shift_v2", lambda df, **kwargs: trained(fixtures["shift_default"])),
                patch.object(exports, "train_standings_v2", lambda df, **kwargs: trained(fixtures["standings"])),
            ):
                # Production state: artifacts trained and active, analytics rows written for the folds, all committed.
                async with AsyncSession(engine, expire_on_commit=False) as session:
                    for name in (POINTS, LINEAR, OPENSKILL):  # seeded in a deployed database, absent from the fixture
                        await registry_service.ensure_algorithm(session, name)
                    await orchestrator.train_all_models(session, tid, workspace_id=workspace)
                    await session.commit()
                    all_ids = await tournament_ids_up_to(session, tid, discipline=OW, workspace_id=workspace)
                    for fold in all_ids[-2:]:
                        await run_for_tournament(session, fold, workspace_id=workspace)
                        await flows_service.recalculate_analytics(session, fold, workspace_id=workspace)
                    before = await _analytics_rows(session)
                production_files = _files(production_dir)
                assert production_files and saved
                saved.clear()

                async with engine.connect() as connection:
                    report = await backtest_service.run_rolling_backtest(
                        connection, window=2, cutoff_tournament_id=tid, workspace_id=workspace
                    )

                async with AsyncSession(engine) as session:
                    after = await _analytics_rows(session)
        finally:
            await engine.dispose()

        # Every fold saved artifacts, outside the production directory and into one that no longer exists.
        assert saved
        assert not any(production_dir in path.parents for path in saved)
        assert not any(path.exists() for path in saved)
        assert _files(production_dir) == production_files
        # Registry rows, active flags, algorithms and every analytics row are exactly as committed before.
        assert after == before

        assert list(report["folds"]) == all_ids[-2:]
        for fold in report["folds"].values():
            assert set(fold["agreement_with_organizer_moves"]) == PREDICTORS
        summary = report["summary"]["agreement_with_organizer_moves"]
        assert set(summary) == PREDICTORS
        # Each baseline really predicted a player whose organizer move is observed: the Points/Linear recalculation ran
        # inside the rolled-back transaction and the OpenSkill map was computed.
        assert all(scores["mean_shift_mae"] is not None for scores in summary.values())

    asyncio.run(check())
