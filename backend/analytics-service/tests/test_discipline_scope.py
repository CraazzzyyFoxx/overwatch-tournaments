"""Training, inference and history are scoped to the owning tournament's discipline, role and declared algorithm.

Real databases throughout (P4's transferred statistics fixture plus a same-workspace LoL tournament): the claims are
about SQL predicates, registry rows and files, which a mock session cannot falsify.
"""

from __future__ import annotations

import asyncio
import contextlib
import pickle
import typing
from datetime import date
from unittest.mock import patch

import joblib
import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared import models
from shared.core.chrono import tournament_chrono_key
from shared.disciplines import discipline
from shared.repository import CatalogRoleRepository
from src.core import config
from src.core.analytics_exports import (
    ContradictoryDiscipline,
    UnsupportedAnalytics,
    analytics_exports,
    tournament_discipline,
    tournament_module,
)
from src.services.analytics.flows import flows_service
from src.services.ml.features.standings_features import build_standings_training_frame
from src.services.ml.inference.backfill import backfill_range
from src.services.ml.inference.match_quality_runner import _match_scores, run_match_quality_for_tournament
from src.services.ml.inference.player_anomaly_runner import run_player_anomalies_for_tournament
from src.services.ml.inference.runner import run_for_tournament, run_performance_for_tournament
from src.services.ml.models.base import artifact_path, load_artifact, load_artifact_or_none, save_artifact
from src.services.ml.training.orchestrator import train_all_models
from src.services.ml.training.registry import registry_service
from src.services.ml.training.splits import tournaments_up_to
from tests.test_ml_prediction_parity import load_fixture_models

OW = "overwatch"


class _ForeignStandings:
    """A standings model of some other algorithm: wildly different from the real fixture, and never to be loaded."""

    def predict_proba(self, df: pd.DataFrame):
        return [0.123] * len(df)


@contextlib.asynccontextmanager
async def _session(url: str, ids: dict[str, int], *, lol: bool = False) -> typing.AsyncIterator[AsyncSession]:
    if lol:
        from shared.testing.stats_parity import seed_native_sentinel

        sync_engine = sa.create_engine(url)
        try:
            with sync_engine.begin() as conn:
                seed_native_sentinel(conn, ids)
        finally:
            sync_engine.dispose()
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            with patch.object(config.settings, "analytics_feature_cache_enabled", False):
                yield session
    finally:
        await engine.dispose()


def _statements(session: AsyncSession) -> tuple[list[str], typing.Callable[[], None]]:
    seen: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        seen.append(statement)

    engine = session.bind.sync_engine  # type: ignore[union-attr]
    sa.event.listen(engine, "before_cursor_execute", record)
    return seen, lambda: sa.event.remove(engine, "before_cursor_execute", record)


def _only_reads(statements: list[str]) -> bool:
    return bool(statements) and all(s.lstrip().upper().startswith(("SELECT", "WITH")) for s in statements)


async def _day(session: AsyncSession, tournament_id: int) -> date:
    started, _, _ = (
        await session.execute(sa.select(*tournament_chrono_key()).where(models.Tournament.id == tournament_id))
    ).one()
    return started.date()


def test_history_is_cut_by_cutoff_discipline_workspace_and_real_chronology(stats_parity_database) -> None:
    url, ids = stats_parity_database

    async def check() -> None:
        async with _session(url, ids, lol=True) as session:
            # Make numeric id and start date disagree: the lowest-id career tournament now starts after the cutoff, and
            # the next one before everything else.
            await session.execute(
                sa.text(
                    "UPDATE tournament.tournament SET start_date = start_date + interval '400 days' WHERE id = :id"
                ),
                {"id": ids["tournament_career_1"]},
            )
            await session.execute(
                sa.text(
                    "UPDATE tournament.tournament SET start_date = start_date - interval '400 days' WHERE id = :id"
                ),
                {"id": ids["tournament_career_3"]},
            )
            ow = [
                t.id
                for t in await tournaments_up_to(
                    session, ids["tournament"], discipline=OW, workspace_id=ids["workspace"]
                )
            ]
            # The same-workspace LoL tournament, another workspace's tournament with the same identity-shaped data,
            # and the hidden container never enter the Overwatch history.
            assert ids["tournament_lol"] not in ow
            assert ids["tournament_other"] not in ow and ids["tournament_hidden"] not in ow
            assert ids["tournament"] in ow
            # Order is the actual start date, never the numeric id.
            expected = (
                await session.scalars(
                    sa.text(
                        "SELECT id FROM tournament.tournament WHERE id = ANY(:ids) "
                        "ORDER BY coalesce(start_date, created_at), coalesce(end_date, start_date, created_at), id"
                    ).bindparams(sa.bindparam("ids", ow, type_=sa.ARRAY(sa.BigInteger)))
                )
            ).all()
            assert ow == list(expected)
            assert ids["tournament_career_1"] not in ow and ow[0] == ids["tournament_career_3"]

            # The cross-workspace allowlist is honoured, intersected with the discipline, and an unrestricted read
            # still sees only Overwatch.
            both = [
                t.id
                for t in await tournaments_up_to(
                    session,
                    ids["tournament_other"],
                    discipline=OW,
                    workspace_ids=[ids["workspace"], ids["workspace_other"]],
                )
            ]
            assert ids["tournament_other"] in both and ids["tournament_lol"] not in both
            everyone = [t.id for t in await tournaments_up_to(session, ids["tournament_other"], discipline=OW)]
            assert ids["tournament_lol"] not in everyone and ids["tournament_other"] in everyone

            # Contradictory inputs are rejected, never reinterpreted: another game's cutoff, another tenant's cutoff.
            with pytest.raises(ValueError, match="belongs to 'lol'"):
                await tournaments_up_to(session, ids["tournament_lol"], discipline=OW)
            with pytest.raises(ValueError, match="outside the requested workspace scope"):
                await tournaments_up_to(
                    session, ids["tournament"], discipline=OW, workspace_ids=[ids["workspace_other"]]
                )
            with pytest.raises(ValueError, match="outside the requested workspace scope"):
                await tournaments_up_to(session, ids["tournament"], discipline=OW, workspace_id=ids["workspace_other"])
            assert await tournaments_up_to(session, 10**9, discipline=OW) == []

            # The tournament names its game; an explicit value cannot override it.
            assert await tournament_discipline(session, ids["tournament"]) == OW
            assert await tournament_discipline(session, ids["tournament_lol"], explicit="lol") == "lol"
            assert await tournament_discipline(session, 10**9) is None
            with pytest.raises(ContradictoryDiscipline):
                await tournament_discipline(session, ids["tournament_lol"], explicit=OW)
            assert await tournament_module(session, ids["tournament_lol"]) is None
            assert (await tournament_module(session, ids["tournament"]))[0] == OW

    asyncio.run(check())


def test_a_discipline_without_analytics_reads_only_and_writes_nothing(stats_parity_database, tmp_path) -> None:
    url, ids = stats_parity_database

    async def check() -> None:
        async with _session(url, ids, lol=True) as session:
            lol = ids["tournament_lol"]
            algorithms = await session.scalar(sa.select(sa.func.count()).select_from(models.AnalyticsAlgorithm))
            lol_day = await _day(session, lol)
            seen, stop = _statements(session)
            try:
                with (
                    patch.object(config.settings, "analytics_models_dir", str(tmp_path)),
                    patch("src.services.ml.training.orchestrator.save_artifact") as saved,
                ):
                    # Training is explicit: unsupported before anything is read for it, ensured, written or saved.
                    with pytest.raises(UnsupportedAnalytics):
                        await train_all_models(session, lol)
                    saved.assert_not_called()
                    # Automatic enrichment is an empty summary, and no existing prediction row is cleared.
                    assert await run_for_tournament(session, lol) == {}
                    assert await run_for_tournament(session, lol, model_kinds=["shift", "standings"]) == {}
                    assert await run_performance_for_tournament(session, lol) == 0
                    assert await run_player_anomalies_for_tournament(session, lol) == 0
                    assert await run_match_quality_for_tournament(session, lol) == 0
                    assert await flows_service.recalculate_analytics(session, lol) == []
                    assert await backfill_range(session, from_date=lol_day, to_date=lol_day, discipline="lol") == {}
            finally:
                stop()
            assert _only_reads(seen), [s for s in seen if not s.lstrip().upper().startswith(("SELECT", "WITH"))]
            assert list(tmp_path.iterdir()) == []
            assert await session.scalar(sa.select(sa.func.count()).select_from(models.AnalyticsAlgorithm)) == algorithms
            # A backfill over the real range visits Overwatch tournaments only and serves each from its own module.
            first, last = sorted([await _day(session, ids["tournament"]), await _day(session, lol)])
            visited = await backfill_range(session, from_date=first, to_date=last, model_kinds=["performance"])
            assert lol not in visited and ids["tournament"] in visited and ids["tournament_hidden"] not in visited
            with pytest.raises(UnsupportedAnalytics):
                analytics_exports("lol")

    asyncio.run(check())


async def _register_fixture_artifact(session: AsyncSession, tmp_path, kind: str, name: str, model, role_id) -> int:
    exports = analytics_exports(OW)
    declaration = exports.MODELS[kind]
    algorithm = await registry_service.ensure_algorithm(session, declaration.algorithm_name)
    path = artifact_path(algorithm.id, declaration.model_version, f"{name}.joblib", root=str(tmp_path))
    artifact = await registry_service.register_artifact(
        session,
        discipline=OW,
        algorithm_id=algorithm.id,
        model_kind=kind,
        role_id=role_id,
        version=declaration.model_version,
        storage_uri=save_artifact(model, path),
        feature_version="test",
        training_cutoff_tournament_id=None,
        metrics=None,
        feature_importance=None,
    )
    return artifact.id


def test_match_quality_runs_on_the_real_declared_standings_artifact(stats_parity_database, tmp_path) -> None:
    url, ids = stats_parity_database
    fixtures = load_fixture_models()

    async def check() -> None:
        async with _session(url, ids, lol=True) as session:
            exports = analytics_exports(OW)
            tid, workspace = ids["tournament"], ids["workspace"]
            real = fixtures["standings"]
            await _register_fixture_artifact(session, tmp_path, "standings", "real_standings", real, None)

            # Another algorithm that shares the kind, active, whose model would give 0.123 everywhere.
            foreign = await registry_service.ensure_algorithm(session, "Someone else's standings model")
            foreign_path = tmp_path / "foreign.joblib"
            joblib.dump(_ForeignStandings(), foreign_path)
            await registry_service.artifacts.create(
                session,
                models.MLModelArtifact(
                    algorithm_id=foreign.id,
                    model_kind="standings",
                    version="9.9.9",
                    storage_uri=str(foreign_path),
                    feature_version="test",
                    is_active=True,
                ),
            )
            await session.commit()

            encounters = await build_standings_training_frame(session, [tid], discipline=OW, workspace_id=workspace)
            assert not encounters.empty
            expected_p = real.predict_proba(encounters)
            expected = exports.compute_match_quality(
                encounters.assign(p_home_wins=expected_p), await _match_scores(session, tid, discipline=OW)
            )
            written = await run_match_quality_for_tournament(session, tid, workspace_id=workspace)
            assert written == len(expected) > 0

            algorithm_id = await session.scalar(
                sa.select(models.AnalyticsAlgorithm.id).where(
                    models.AnalyticsAlgorithm.name == exports.MODELS["match_quality"].algorithm_name
                )
            )
            rows = (
                await session.execute(
                    sa.select(models.AnalyticsMatchQuality.encounter_id, models.AnalyticsMatchQuality.predictability)
                    .where(models.AnalyticsMatchQuality.algorithm_id == algorithm_id)
                    .order_by(models.AnalyticsMatchQuality.encounter_id)
                )
            ).all()
            by_encounter = {int(r.encounter_id): float(r.predictability) for r in rows}
            for row in expected.itertuples(index=False):
                assert by_encounter[int(row.encounter_id)] == pytest.approx(float(row.predictability), abs=1e-9)
            # The foreign model's constant would have produced different predictabilities: the stored ones are the
            # real artifact's, not that.
            wrong = exports.compute_match_quality(
                encounters.assign(p_home_wins=0.123), await _match_scores(session, tid, discipline=OW)
            )
            assert not wrong["predictability"].round(6).equals(expected["predictability"].round(6))

    asyncio.run(check())


def test_load_artifact_or_none_distinguishes_unconverted_artifacts_from_a_broken_environment(tmp_path, caplog) -> None:
    gone = tmp_path / "gone.joblib"
    stale = tmp_path / "stale.joblib"
    stale.write_bytes(b"csrc.services.ml.models.performance_v2\nPerformanceModelV2\n)\x81.")
    no_library = (
        tmp_path / "no_library.joblib"
    )  # an estimator package missing from the image is NOT an artifact problem
    no_library.write_bytes(b"cnot_an_installed_estimator_lib\nBooster\n)\x81.")
    damaged = tmp_path / "damaged.joblib"

    assert load_artifact_or_none(f"file://{gone.as_posix()}") is None  # missing file: quiet neutral fallback
    assert not caplog.records
    with caplog.at_level("ERROR"):
        assert load_artifact_or_none(f"file://{stale.as_posix()}") is None
        with patch("src.services.ml.models.base.load_artifact", side_effect=pickle.UnpicklingError("bad opcode")):
            assert load_artifact_or_none(f"file://{damaged.as_posix()}") is None
    assert [r.levelname for r in caplog.records] == ["ERROR", "ERROR"] and all(r.exc_info for r in caplog.records)
    with pytest.raises(ModuleNotFoundError, match="not_an_installed_estimator_lib"):
        load_artifact_or_none(f"file://{no_library.as_posix()}")


def test_runners_fall_back_when_an_artifact_names_a_class_path_that_no_longer_exists(
    stats_parity_database, tmp_path
) -> None:
    """A pre-conversion pickle (module moved) is as unusable as a missing file: logged, neutral result, no failure."""
    url, ids = stats_parity_database
    stale = tmp_path / "stale.joblib"
    stale.write_bytes(b"csrc.services.ml.models.performance_v2\nPerformanceModelV2\n)\x81.")
    with pytest.raises(ModuleNotFoundError):
        load_artifact(f"file://{stale.as_posix()}")

    async def check() -> None:
        async with _session(url, ids, lol=True) as session:
            exports = analytics_exports(OW)
            tid, workspace = ids["tournament"], ids["workspace"]
            tank = (await CatalogRoleRepository().rated_rows(session, discipline=OW, workspace_id=None))["tank"]
            for kind, role_id in (("standings", None), ("performance", tank.id)):
                declaration = exports.MODELS[kind]
                algorithm = await registry_service.ensure_algorithm(session, declaration.algorithm_name)
                await registry_service.register_artifact(
                    session,
                    discipline=OW,
                    algorithm_id=algorithm.id,
                    model_kind=kind,
                    role_id=role_id,
                    version=declaration.model_version,
                    storage_uri=f"file://{stale.as_posix()}",
                    feature_version="test",
                    training_cutoff_tournament_id=None,
                    metrics=None,
                    feature_importance=None,
                )
            encounters = await build_standings_training_frame(session, [tid], discipline=OW, workspace_id=workspace)
            neutral = exports.compute_match_quality(
                encounters.assign(p_home_wins=None), await _match_scores(session, tid, discipline=OW)
            )
            assert await run_match_quality_for_tournament(session, tid, workspace_id=workspace) == len(neutral) > 0
            assert await run_performance_for_tournament(session, tid, workspace_id=workspace, include_shap=False) == 0

            # A missing estimator library is not an unconverted artifact: the pass fails loudly instead of going neutral.
            library = tmp_path / "no_library.joblib"
            library.write_bytes(b"cnot_an_installed_estimator_lib\nBooster\n)\x81.")
            await registry_service.register_artifact(
                session,
                discipline=OW,
                algorithm_id=(
                    await registry_service.ensure_algorithm(session, exports.MODELS["standings"].algorithm_name)
                ).id,
                model_kind="standings",
                role_id=None,
                version="9.9.9",
                storage_uri=f"file://{library.as_posix()}",
                feature_version="test",
                training_cutoff_tournament_id=None,
                metrics=None,
                feature_importance=None,
            )
            with pytest.raises(ModuleNotFoundError, match="not_an_installed_estimator_lib"):
                await run_match_quality_for_tournament(session, tid, workspace_id=workspace)

    asyncio.run(check())


def test_performance_inference_uses_native_overwatch_roles_only(stats_parity_database, tmp_path) -> None:
    url, ids = stats_parity_database
    fixtures = load_fixture_models()

    async def predictions(session: AsyncSession, tid: int, workspace: int) -> list[tuple]:
        written = await run_performance_for_tournament(session, tid, workspace_id=workspace, include_shap=False)
        rows = (
            await session.execute(
                sa.select(
                    models.AnalyticsPerformance.player_id,
                    models.AnalyticsPerformance.impact_score,
                    models.AnalyticsPerformance.raw_value,
                )
                .where(models.AnalyticsPerformance.tournament_id == tid)
                .order_by(models.AnalyticsPerformance.player_id)
            )
        ).all()
        assert written == len(rows)
        return [tuple(r) for r in rows]

    async def check() -> None:
        async with _session(url, ids, lol=True) as session:
            tid, workspace = ids["tournament"], ids["workspace"]
            roles = await CatalogRoleRepository().rated_rows(session, discipline=OW, workspace_id=None)
            for code, row in roles.items():
                await _register_fixture_artifact(
                    session, tmp_path, "performance", f"performance_{code}", fixtures[f"performance_{code}"], row.id
                )
            # An all-role (null role id) artifact is not role-maskable and is left alone by the per-role loader.
            await _register_fixture_artifact(
                session, tmp_path, "performance", "all_roles", fixtures["performance_tank"], None
            )
            await session.commit()
            baseline = await predictions(session, tid, workspace)
            assert baseline

            # A LoL role under the same declared algorithm and an unrelated algorithm's Overwatch-role artifact are
            # both outside discovery: the result cannot change.
            await CatalogRoleRepository().project_module(session, discipline("lol"))
            lol_support = (await CatalogRoleRepository().rated_rows(session, discipline="lol", workspace_id=None))[
                "support"
            ]
            algorithm = await registry_service.ensure_algorithm(
                session, analytics_exports(OW).MODELS["performance"].algorithm_name
            )
            foreign = await registry_service.ensure_algorithm(session, "Someone else's performance model")
            stray = tmp_path / "stray.joblib"
            joblib.dump(fixtures["performance_damage"], stray)
            for algorithm_id, role in ((algorithm.id, lol_support), (foreign.id, roles["support"])):
                await registry_service.artifacts.create(
                    session,
                    models.MLModelArtifact(
                        algorithm_id=algorithm_id,
                        model_kind="performance",
                        dimension_id=role.dimension_id,
                        role_id=role.id,
                        version="stray",
                        storage_uri=str(stray),
                        feature_version="test",
                        is_active=True,
                    ),
                )
            await session.commit()
            assert await predictions(session, tid, workspace) == baseline

    asyncio.run(check())


def test_training_enumerates_the_catalogs_rated_roles_and_rejects_a_foreign_scope(
    stats_parity_database, tmp_path
) -> None:
    """The role loop is the discipline's rated catalog roles in display order, each artifact is registered on its native
    role id under the declared algorithm, and a workspace allowlist that excludes the cutoff trains nothing."""
    from types import SimpleNamespace

    url, ids = stats_parity_database
    exports = analytics_exports(OW)
    asked: list[str] = []

    def fake_train(df, *, role, val_df=None, devices):
        asked.append(role)
        return SimpleNamespace(
            role=role, model=_ForeignStandings(), metrics={"rows": float(len(df))}, feature_importance={}
        )

    async def check() -> None:
        async with _session(url, ids, lol=True) as session:
            tid = ids["tournament"]
            roles = await CatalogRoleRepository().rated_rows(session, discipline=OW, workspace_id=None)
            with (
                patch.object(config.settings, "analytics_models_dir", str(tmp_path)),
                patch.object(exports, "train_performance_v2", fake_train),
            ):
                # A contradictory allowlist is refused before any frame is built, model trained or file written.
                with pytest.raises(ValueError, match="outside the requested workspace scope"):
                    await train_all_models(
                        session, tid, model_kinds=["performance"], workspace_ids=[ids["workspace_other"]]
                    )
                assert asked == [] and list(tmp_path.iterdir()) == []

                summary = await train_all_models(
                    session, tid, model_kinds=["performance"], workspace_ids=[ids["workspace"]]
                )
            assert asked == list(roles)  # tank, damage, support: the catalog's order, no hard-coded tuple
            outcomes = summary["performance"]
            assert [o["role"] for o in outcomes] == list(roles)
            declared = exports.MODELS["performance"]
            algorithm_id = await session.scalar(
                sa.select(models.AnalyticsAlgorithm.id).where(models.AnalyticsAlgorithm.name == declared.algorithm_name)
            )
            stored = (
                await session.execute(
                    sa.select(models.MLModelArtifact.role_id, models.MLModelArtifact.algorithm_id).where(
                        models.MLModelArtifact.id.in_([o["artifact_id"] for o in outcomes])
                    )
                )
            ).all()
            assert {r.role_id for r in stored} == {row.id for row in roles.values()}
            assert {r.algorithm_id for r in stored} == {algorithm_id}

    asyncio.run(check())
