"""No transaction idles across long CPU work: pgBouncer disconnects a client idle in one for 60 s.

Model fits take minutes, the Points/Linear pass is linear in the workspace's history and the standings simulation
quadratic in its teams. The reads around them are stubs that each run a real statement on a live session, so
``in_transaction()`` at the CPU step is the real answer.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
import sqlalchemy as sa

from shared.testing.db import real_db_sessionmaker
from src.core import config
from src.core.analytics_exports import analytics_exports
from src.services.analytics import flows
from src.services.ml.inference import runner
from src.services.ml.training import orchestrator
from src.services.ml.training.registry import registry_service

OW = analytics_exports("overwatch")


def _touching(session):
    """An async stub returning ``result`` after a statement, so the transaction a real read or write would begin is open."""

    def stub(result):
        async def call(*args, **kwargs):
            await session.execute(sa.select(1))
            return result

        return call

    return stub


def _run(check) -> None:
    async def main() -> None:
        async with real_db_sessionmaker() as factory, factory() as session:
            await check(session)

    asyncio.run(main())


def test_every_fit_runs_outside_a_transaction(tmp_path) -> None:
    frame = pd.DataFrame({"current_div": [1.0], "next_tournament_div": [2.0]})
    roles = {"tank": SimpleNamespace(id=1), "support": SimpleNamespace(id=2)}
    fits: list[tuple[str, bool]] = []

    async def check(session) -> None:
        touching = _touching(session)

        def fit(kind: str):
            def call(df, **kwargs):
                fits.append((kwargs.get("role", kind), session.in_transaction()))
                return SimpleNamespace(model={}, metrics={}, feature_importance={})

            return call

        with (
            patch.object(config.settings, "analytics_models_dir", str(tmp_path)),
            patch.object(orchestrator, "tournament_discipline", touching("overwatch")),
            patch.object(orchestrator, "tournament_ids_up_to", touching([1, 2, 3])),
            patch.object(orchestrator, "_build_training_frame", touching(frame)),
            patch.object(orchestrator, "build_shift_feature_frame", touching(frame)),
            patch.object(orchestrator, "build_standings_training_frame", touching(frame)),
            patch.object(registry_service, "ensure_algorithm", touching(SimpleNamespace(id=1))),
            patch.object(registry_service, "rated_roles", touching(roles)),
            patch.object(registry_service, "register_artifact", touching(SimpleNamespace(id=1))),
            patch.object(OW, "train_performance_v2", fit("performance")),
            patch.object(OW, "train_shift_v2", fit("shift")),
            patch.object(OW, "train_standings_v2", fit("standings")),
        ):
            await orchestrator.train_all_models(session, 3)

    _run(check)
    assert fits == [("tank", False), ("support", False), ("shift", False), ("standings", False)]


def test_the_points_and_linear_pass_runs_outside_a_transaction() -> None:
    seen: list[bool] = []

    class Stop(Exception):
        pass

    async def check(session) -> None:
        touching = _touching(session)

        def points(df):
            seen.append(session.in_transaction())
            raise Stop

        with (
            patch.object(flows, "tournament_discipline", touching("overwatch")),
            patch.object(flows.flows_service, "get_data_frame", touching(pd.DataFrame({"tournament_id": [1]}))),
            patch.object(flows, "compute_points_shifts", points),
            pytest.raises(Stop),
        ):
            await flows.flows_service.recalculate_analytics(session, 1, workspace_id=1)

    _run(check)
    assert seen == [False]


def test_the_standings_simulation_runs_outside_a_transaction() -> None:
    seen: list[bool] = []
    forecast = pd.DataFrame({"home_team_id": [10, 20], "away_team_id": [20, 10]})
    model = SimpleNamespace(predict_proba=lambda df: [0.9, 0.1])

    async def check(session) -> None:
        touching = _touching(session)

        def simulate(matchups, teams, **kwargs):
            seen.append(session.in_transaction())
            return pd.DataFrame()

        with (
            patch.object(runner, "tournament_module", touching(("overwatch", OW))),
            patch.object(runner, "_algorithm_id", touching(1)),
            patch.object(runner.registry_service, "load_active_artifact", touching(SimpleNamespace(storage_uri="s"))),
            patch.object(runner, "load_artifact_or_none", lambda _uri: model),
            patch.object(runner, "build_standings_forecast_frame", touching(forecast)),
            patch.object(OW, "simulate_standings", simulate),
        ):
            assert await runner.run_standings_for_tournament(session, 7, workspace_id=3) == 0

    _run(check)
    assert seen == [False]
