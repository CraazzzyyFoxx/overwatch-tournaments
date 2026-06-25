"""Tests for the pre-encounter OpenSkill mu snapshot.

Regression for a standings-frame fan-out: a self/placeholder encounter
(home_team_id == away_team_id) made the snapshot emit the same
(encounter_id, team_id) twice, which duplicated rows through the standings
merges and tripped uq_analytics_match_quality on insert. The snapshot must
skip self-encounters and return one row per (encounter_id, team_id).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import pandas as pd

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ["DEBUG"] = "false"
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

opp = importlib.import_module("src.services.ml.features.opponent_strength")


def _player(uid: int, role: str) -> SimpleNamespace:
    return SimpleNamespace(user_id=uid, role=role)


def _team(team_id: int, players: list) -> SimpleNamespace:
    return SimpleNamespace(id=team_id, players=players)


class SnapshotDedupTests(IsolatedAsyncioTestCase):
    async def test_self_encounter_skipped_and_unique_team_rows(self) -> None:
        from openskill.models import PlackettLuce

        pl = PlackettLuce()
        p1, p2, p3 = _player(1, "tank"), _player(2, "tank"), _player(3, "dps")
        e_normal = SimpleNamespace(
            id=1,
            home_team_id=10,
            away_team_id=20,
            home_team=_team(10, [p1]),
            away_team=_team(20, [p2]),
            home_score=2,
            away_score=1,
        )
        e_self = SimpleNamespace(  # the prod bug: team 63 vs itself
            id=94,
            home_team_id=63,
            away_team_id=63,
            home_team=_team(63, [p3]),
            away_team=_team(63, [p3]),
            home_score=1,
            away_score=3,
        )
        ratings = {f"{p.user_id}-{p.role}": pl.rating() for p in (p1, p2, p3)}

        with (
            patch.object(opp, "get_data_frame", AsyncMock(return_value=pd.DataFrame({"x": [1]}))),
            patch.object(opp.v1_service, "lookback_start_tournament_id", AsyncMock(return_value=1)),
            patch.object(opp.v1_service, "get_matches", AsyncMock(return_value=[e_normal, e_self])),
            patch.object(opp.v1_service, "get_teams_with_players", AsyncMock(return_value=[])),
            patch.object(opp, "prepare_openskill_data", return_value=(None, ratings, None)),
            patch.object(opp, "get_id_role", lambda p: f"{p.user_id}-{p.role}"),
        ):
            df = await opp._snapshot_pre_encounter_team_mu_uncached(SimpleNamespace(), 4)

        # Self-encounter 94 is dropped entirely.
        self.assertNotIn(94, df["encounter_id"].tolist())
        # One row per (encounter_id, team_id), no fan-out.
        self.assertEqual(0, int(df.duplicated(subset=["encounter_id", "team_id"]).sum()))
        # The normal encounter contributes exactly its two teams.
        self.assertEqual(
            {(1, 10), (1, 20)},
            {(int(r.encounter_id), int(r.team_id)) for r in df.itertuples(index=False)},
        )
