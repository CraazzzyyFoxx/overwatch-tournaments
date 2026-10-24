"""Tests for the pre-encounter OpenSkill mu snapshot.

Regression for a standings-frame fan-out: the snapshot must return one row per
(encounter_id, team_id), or the standings merges duplicate rows and
uq_analytics_match_quality trips on insert. A team holds at most one live seat of
an encounter, and every live seat with a roster is one team -- duel or lobby.

Regression for an outcome leak: the replay starts from the players' seed ratings,
so an encounter's own result never reaches its pre-encounter snapshot.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

import pandas as pd

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))


opp = importlib.import_module("src.services.ml.features.opponent_strength")


def _player(uid: int, role: str, rank: int = 2000) -> SimpleNamespace:
    return SimpleNamespace(user_id=uid, role=role, rank=rank, is_newcomer=False, is_newcomer_role=False)


def _team(team_id: int, players: list) -> SimpleNamespace:
    return SimpleNamespace(id=team_id, players=players)


def _seat(slot: int, team_id: int | None, placement: int | None, *, active: bool = True) -> SimpleNamespace:
    return SimpleNamespace(slot=slot, team_id=team_id, placement=placement, active=active)


async def _snapshot(matches: list, rosters: dict) -> pd.DataFrame:
    with (
        patch.object(opp.analytics_service, "lookback_tournament_ids", AsyncMock(return_value=[1, 2, 3, 4])),
        patch.object(opp.analytics_service, "get_matches_for_tournaments", AsyncMock(return_value=matches)),
        patch.object(opp.analytics_service, "get_rosters", AsyncMock(return_value=rosters)),
        patch.object(opp, "get_id_role", lambda p: f"{p.user_id}-{p.role}"),
    ):
        return await opp._snapshot_pre_encounter_team_mu_uncached(SimpleNamespace(), 4, discipline="overwatch")


class SnapshotSeatTests(IsolatedAsyncioTestCase):
    async def test_one_row_per_live_seat_with_a_roster(self) -> None:
        p1, p2, p3 = _player(1, "tank"), _player(2, "tank"), _player(3, "damage")
        rosters = {10: _team(10, [p1]), 20: _team(20, [p2]), 30: _team(30, [p3])}
        duel = SimpleNamespace(id=1, teams=[_seat(1, 10, 1), _seat(2, 20, 2)])
        # A lobby: every seat is one team; a retired seat and a seat whose team is gone are not.
        lobby = SimpleNamespace(
            id=2,
            teams=[
                _seat(1, 10, 2),
                _seat(2, 20, 1),
                _seat(3, 30, 3),
                _seat(4, 99, None, active=False),
                _seat(5, None, 4),
            ],
        )

        df = await _snapshot([duel, lobby, duel], rosters)

        # One row per (encounter_id, team_id), no fan-out -- the repeated duel is read once.
        self.assertEqual(0, int(df.duplicated(subset=["encounter_id", "team_id"]).sum()))
        self.assertEqual(
            {(1, 10), (1, 20), (2, 10), (2, 20), (2, 30)},
            {(int(r.encounter_id), int(r.team_id)) for r in df.itertuples(index=False)},
        )

    async def test_a_snapshot_holds_only_the_results_played_before_it(self) -> None:
        p1, p2 = _player(1, "tank"), _player(2, "tank")
        rosters = {10: _team(10, [p1]), 20: _team(20, [p2])}
        first = SimpleNamespace(id=1, teams=[_seat(1, 10, 1), _seat(2, 20, 2)])
        second = SimpleNamespace(id=2, teams=[_seat(1, 10, 1), _seat(2, 20, 2)])

        df = await _snapshot([first, second], rosters)

        # Equally ranked teams are equal before their first encounter, whoever went on to win it.
        before = df[df["encounter_id"] == 1].set_index("team_id")["avg_mu"]
        self.assertEqual(before[10], before[20])
        # The second snapshot is taken after the first win: the winner rose, the loser fell.
        later = df[df["encounter_id"] == 2].set_index("team_id")["avg_mu"]
        self.assertGreater(later[10], before[10])
        self.assertLess(later[20], before[20])
