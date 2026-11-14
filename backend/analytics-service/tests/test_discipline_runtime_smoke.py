"""Runtime smoke of the P6 artifact conversion: the ordinary read paths serve converted artifacts, nothing else changes.

The whole chain runs for real, once, over the T6 conversion fixtures (the T4 pre-move pickles of the removed class paths):

1. ``export`` in a separate process on the frozen pre-move source (``git archive``), ``stage`` under the current code and
   ``apply`` on a scratch PostgreSQL clone at head (``tool.apply``: only ``storage_uri`` changes, one transaction);
2. the runtime then loads the converted artifacts the way production does -- the registry (``load_active_artifact(s)``
   by discipline, declared algorithm and native role id), ``run_for_tournament`` (performance, shift, standings,
   anomalies, match quality incl. its standings loader) -- as an ordinary non-owner role
   (``shared.testing.stats_access.native_role``);
3. every frozen D96 prediction receipt is reproduced bit-for-bit by the models the registry returned, and every table
   the runtime wrote equals the one written by a second clone whose artifacts were assembled independently from the
   fixture *state* (``load_fixture_models``) -- the converted files change nothing a consumer can observe;
4. the other game is untouched: a LoL tournament and a LoL role resolve to no artifact and to no read or write;
5. rollback restores the original URI set exactly (the old image's files were never touched), and the old paths stay
   unreadable by the new runtime until the old image serves them again.

Nothing is fitted or retrained; the estimators are the real LightGBM/XGBoost/scikit-learn objects.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import typing
from pathlib import Path
from unittest.mock import patch

import numpy as np

_REAL_DEFAULT_RNG = np.random.default_rng
import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from shared.disciplines import discipline
from shared.repository import CatalogRoleRepository
from shared.testing.stats_access import native_role
from shared.testing.stats_parity import legacy_database, seed_native_sentinel
from src.core import config
from src.core.analytics_exports import UnsupportedAnalytics, analytics_exports
from src.services.ml.inference.runner import run_for_tournament
from src.services.ml.models.base import artifact_path, load_artifact, save_artifact
from src.services.ml.training.registry import registry_service
from tests.test_artifact_discipline_conversion import (  # noqa: F401  (module fixtures reused by name)
    ALGORITHM,
    ROWS,
    Workspace,
    _receipt,
    _stage_in_process,
    _table,
    _uris,
    exported,
    old_tree,
    registry,
    tool,
    workspace,
)
from tests.test_ml_prediction_parity import (
    GOLDEN,
    ROLES,
    _assert_equal,
    _fit_forbidden,
    _fitted_performance,
    _shift_outputs,
    _standings_outputs,
    _to_json,
    evaluation_frame,
    load_fixture_models,
)

OW = "overwatch"
NEW_MODULE = "shared.disciplines.overwatch.analytics.models."
NAMES = {row[0]: row[1] for row in ROWS}
_REAL_DEFAULT_RNG = np.random.default_rng
#: The registry itself is not a runtime output; everything else under ``analytics`` is.
NOT_OUTPUT = ("ml_model_artifact", "algorithms", "alembic_version")


@contextlib.asynccontextmanager
async def _session(url: str, role: str | None = None) -> typing.AsyncIterator[AsyncSession]:
    """An async session; with ``role`` every connection is ``SET ROLE`` to that non-owner role for its whole life."""
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"), poolclass=NullPool)
    if role is not None:

        @event.listens_for(engine.sync_engine, "connect")
        def _become(dbapi_connection, _record) -> None:  # noqa: ANN001
            cursor = dbapi_connection.cursor()
            cursor.execute(f'SET ROLE "{role}"')
            cursor.close()

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            with patch.object(config.settings, "analytics_feature_cache_enabled", False):
                yield session
    finally:
        await engine.dispose()


async def _assert_not_superuser(session: AsyncSession) -> None:
    assert not await session.scalar(sa.text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user"))


async def _outputs(session: AsyncSession) -> dict[str, list[dict[str, typing.Any]]]:
    """Every row the runtime wrote, without surrogate keys, timestamps or the (per-clone) algorithm id."""
    tables = (
        await session.scalars(
            sa.text(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'analytics' "
                "AND table_type = 'BASE TABLE' AND table_name <> ALL(:skip) ORDER BY table_name"
            ).bindparams(sa.bindparam("skip", value=list(NOT_OUTPUT), type_=sa.ARRAY(sa.String)))
        )
    ).all()
    out: dict[str, list[dict[str, typing.Any]]] = {}
    for table in tables:
        rows = (
            await session.execute(
                sa.text(
                    f"SELECT to_jsonb(t) - 'id' - 'created_at' - 'updated_at' - 'algorithm_id' AS row "
                    f'FROM analytics."{table}" t ORDER BY 1::text'
                )
            )
        ).scalars()
        out[table] = list(rows)
    return {table: rows for table, rows in out.items() if rows}


async def _run_runtime(url: str, ids: dict[str, int], role: str) -> tuple[dict[str, int], dict[str, list]]:
    # `simulate_standings` draws from an unseeded `np.random.default_rng()`; both runs get the same stream so the
    # distribution it persists is a pure function of the (bit-identical) model.
    with patch("numpy.random.default_rng", lambda *_a, **_k: _REAL_DEFAULT_RNG(20261018)):
        async with _session(url, role) as session:
            await _assert_not_superuser(session)
            summary = await run_for_tournament(session, ids["tournament"], workspace_id=ids["workspace"])
            await session.rollback()  # the runners commit their own work; nothing is left open under the role
            return summary, await _outputs(session)


async def _register_independent_artifacts(url: str, tmp_path: Path) -> None:
    """The baseline clone's registry: the same five active artifacts, assembled from the fixture *state*, not converted."""
    fixtures = load_fixture_models()
    exports = analytics_exports(OW)
    async with _session(url) as session:
        roles = await registry_service.rated_roles(session, discipline=OW, active_only=False)
        wanted = [(f"performance_{code}", "performance", roles[code].id) for code in ROLES]
        wanted += [("standings", "standings", None), ("shift_default", "shift", None)]
        for name, kind, role_id in wanted:
            declaration = exports.MODELS[kind]
            algorithm = await registry_service.ensure_algorithm(session, declaration.algorithm_name)
            await registry_service.register_artifact(
                session,
                discipline=OW,
                algorithm_id=algorithm.id,
                model_kind=kind,
                role_id=role_id,
                version=declaration.model_version,
                storage_uri=save_artifact(
                    fixtures[name],
                    artifact_path(algorithm.id, declaration.model_version, f"{name}.joblib", root=str(tmp_path)),
                ),
                feature_version="2",
                training_cutoff_tournament_id=None,
                metrics=None,
                feature_importance=None,
            )
        await session.commit()


def _frozen_receipt_outputs(models_by_name: dict[str, typing.Any]) -> dict[str, typing.Any]:
    frame = evaluation_frame()
    with _fit_forbidden():
        return _to_json(
            {
                "fitted_performance": _fitted_performance(models_by_name, frame),
                "baselines": {
                    role: models_by_name[f"performance_{role}"]
                    .baseline.predict_proba(frame[["team_avg_mu", "opp_avg_mu", "mu_gap"]].fillna(0.0).to_numpy())
                    .tolist()
                    for role in ROLES
                },
                "standings_fitted": _standings_outputs(
                    models_by_name, frame.assign(home_team_id=range(12), away_team_id=range(1, 13))
                ),
                "shift": _shift_outputs(models_by_name, frame.assign(current_div=np.arange(12) % 7 + 1, grid_n_div=20)),
            }
        )


async def _registry_models(url: str) -> dict[str, typing.Any]:
    """Every row through the runtime's own selection: active ones by discipline/algorithm/role, history by its row."""
    exports = analytics_exports(OW)
    found: dict[int, typing.Any] = {}
    async with _session(url) as session:
        roles = await registry_service.rated_roles(session, discipline=OW, active_only=False)
        by_role_id = {row.id: code for code, row in roles.items()}
        for kind in ("performance", "standings", "shift"):
            declaration = exports.MODELS[kind]
            algorithm_id = await session.scalar(
                sa.text("SELECT id FROM analytics.algorithms WHERE name = :n"), {"n": declaration.algorithm_name}
            )
            assert algorithm_id is not None, declaration.algorithm_name
            if kind == "performance":
                active = await registry_service.load_active_artifacts(
                    session, discipline=OW, algorithm_id=algorithm_id, model_kind=kind
                )
                assert {by_role_id[a.role_id] for a in active} == set(ROLES) and len(active) == 3
            else:
                one = await registry_service.load_active_artifact(
                    session, discipline=OW, algorithm_id=algorithm_id, model_kind=kind, role_id=None
                )
                assert one is not None
                active = [one]
            for artifact in active:
                found[artifact.id] = load_artifact(artifact.storage_uri)
        # The active rows are exactly the inventory's active rows: history is never selected as the live model.
        assert set(found) == {row[0] for row in ROWS if row[4]}
        rows = (await session.execute(sa.text("SELECT id, storage_uri FROM analytics.ml_model_artifact"))).all()
    for artifact_id, uri in rows:
        found.setdefault(artifact_id, load_artifact(uri))
    return {NAMES[artifact_id]: model for artifact_id, model in found.items()}


async def _other_game_is_untouched(url: str, ids: dict[str, int], role: str) -> None:
    sync = sa.create_engine(url)
    try:
        with sync.begin() as conn:
            seed_native_sentinel(conn, ids)
    finally:
        sync.dispose()
    async with _session(url) as owner:  # the LoL module's role catalogue, projected as a deployment does
        await CatalogRoleRepository().project_module(owner, discipline("lol"))
        await owner.commit()
    exports = analytics_exports(OW)
    async with _session(url, role) as session:
        await _assert_not_superuser(session)
        before = await _outputs(session)
        # Scoped selection: a LoL role never resolves to an Overwatch artifact, and neither does a foreign algorithm.
        lol_support = (await CatalogRoleRepository().rated_rows(session, discipline="lol", workspace_id=None))[
            "support"
        ]
        performance = await session.scalar(
            sa.text("SELECT id FROM analytics.algorithms WHERE name = :n"),
            {"n": exports.MODELS["performance"].algorithm_name},
        )
        support = (await registry_service.rated_roles(session, discipline=OW, active_only=False))["support"]
        # LoL declares no analytics module: the registry refuses it outright, for a one-role and an all-roles load.
        for load in (
            registry_service.load_active_artifact(
                session, discipline="lol", algorithm_id=performance, model_kind="performance", role_id=lol_support.id
            ),
            registry_service.load_active_artifacts(
                session, discipline="lol", algorithm_id=performance, model_kind="performance"
            ),
        ):
            with pytest.raises(UnsupportedAnalytics):
                await load
        # The LoL role id is not a rated role of Overwatch either: nothing is returned for it.
        assert (
            await registry_service.load_active_artifact(
                session, discipline=OW, algorithm_id=performance, model_kind="performance", role_id=lol_support.id
            )
            is None
        )
        assert (
            await registry_service.load_active_artifact(
                session, discipline=OW, algorithm_id=performance, model_kind="performance", role_id=support.id
            )
        ) is not None
        # A LoL tournament has no analytics module: every runner reads and writes nothing.
        assert await run_for_tournament(session, ids["tournament_lol"], workspace_id=ids["workspace"]) == {}
        await session.rollback()
        assert await _outputs(session) == before


def test_converted_artifacts_serve_the_runtime_with_unchanged_outputs_and_roll_back(
    workspace: Workspace,  # noqa: F811
    exported: Path,  # noqa: F811
    registry: str,  # noqa: F811
    stats_parity_template: tuple[str, dict[str, int]],
    tmp_path: Path,
) -> None:
    url = registry
    _, ids = stats_parity_template
    template = workspace.template_url  # the derived template: it holds the algorithm rows the fixture registered
    bundle, new_root = _stage_in_process(workspace, exported, tmp_path)
    receipt_path = bundle / "receipt.json"
    original = _uris(url)
    before = _table(url)
    originals = {
        a["registry"]["id"]: Path(a["old"]["storage_uri"].removeprefix("file://"))
        for a in _receipt(bundle)["artifacts"]
    }
    old_bytes = {p: p.read_bytes() for p in set(originals.values())}
    # Registry rows carry the algorithm names the module declares (otherwise nothing would be selected below).
    assert set(ALGORITHM.values()) == {analytics_exports(OW).MODELS[k].algorithm_name for k in ALGORITHM}

    applied = tool.apply(receipt_path, url)
    assert applied["status"] == "applied" and applied["applied"]["rows_changed"] == len(ROWS)
    converted = _uris(url)
    assert converted != original and all(Path(u.removeprefix("file://")).is_file() for u in converted.values())

    # 1. the registry hands the runtime converted models; each frozen D96 receipt is reproduced exactly
    models_by_name = asyncio.run(_registry_models(url))
    assert set(models_by_name) == set(NAMES.values())
    assert all(type(model).__module__.startswith(NEW_MODULE) for model in models_by_name.values())
    actual = _frozen_receipt_outputs(models_by_name)
    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))["synthetic"]
    _assert_equal(actual, {k: expected[k] for k in actual}, ("synthetic",))

    # 2. the runtime paths, as a non-owner role, on converted artifacts ...
    with native_role(url, write=True) as role:
        summary, converted_rows = asyncio.run(_run_runtime(url, ids, role))
        asyncio.run(_other_game_is_untouched(url, ids, role))
    assert summary["performance"] > 0 and summary["match_quality"] > 0, summary
    assert {"performance", "match_quality"} <= set(converted_rows), sorted(converted_rows)

    # 3. ... equal what an independently assembled registry produces for the same data
    with legacy_database(template_url=template) as baseline_url:
        asyncio.run(_register_independent_artifacts(baseline_url, tmp_path))
        with native_role(baseline_url, write=True) as baseline_role:
            baseline_summary, baseline_rows = asyncio.run(_run_runtime(baseline_url, ids, baseline_role))
    assert summary == baseline_summary
    # The simulation's generator is fixed in `_run_runtime`, so every table -- the whole standings distribution
    # included (mean, quantiles, prob_top1/3/8, histogram) -- is compared exactly, and standings must exist.
    assert "standings_distribution" in converted_rows and "standings_distribution" in baseline_rows
    assert converted_rows == baseline_rows

    # 4. rollback: the original URI set, every other column untouched, old image's files never modified
    tool.rollback(receipt_path, url)
    assert _uris(url) == original
    after = _table(url)
    assert {i: {k: v for k, v in r.items() if k != "storage_uri"} for i, r in after.items()} == {
        i: {k: v for k, v in r.items() if k != "storage_uri"} for i, r in before.items()
    }
    assert {p: p.read_bytes() for p in old_bytes} == old_bytes
    # The old class paths exist only in the old image: the new runtime refuses them rather than aliasing them.
    with pytest.raises(ModuleNotFoundError):
        load_artifact(original[9001])
    assert all(
        Path(u.removeprefix("file://")).is_file() for u in converted.values()
    )  # converted files stay for re-apply
    assert tool.apply(receipt_path, url)["status"] == "applied" and _uris(url) == converted
    assert new_root.is_dir()
