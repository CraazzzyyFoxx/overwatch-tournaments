"""Node math for ``rank_peak`` / ``rank_climb`` over ``overwatch_rank.rank_snapshot``.

Rank snapshots carry no workspace of their own, so the interesting cases are the
division ordering, the per-``(season, role, platform)`` series boundary, and the
roster join that keeps a foreign user out.

Uses the SQLite fixture from ``test_scrim_achievement_isolation``.
"""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT), str(Path(__file__).resolve().parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import test_scrim_achievement_isolation as _scrim  # noqa: E402
from test_scrim_achievement_isolation import (  # noqa: E402
    REAL_AWAY_USER,
    REAL_HOME_USER,
    REAL_TOURNAMENT_ID,
    WORKSPACE_ID,
    _EngineTestCase,
)

# Importing the module is what registers the nodes.
importlib.import_module("src.services.achievement.engine.conditions.rank_history")  # noqa: E402

evaluator = _scrim.evaluator
eval_context = _scrim.eval_context
models = _scrim.models
enums = _scrim.enums

OUTSIDER_USER = 110
FOREIGN_USER = 111
FOREIGN_WORKSPACE_ID = WORKSPACE_ID + 1
FOREIGN_TOURNAMENT_ID = 42


class _RankFixture(_scrim._Fixture):
    def snapshot(
        self,
        user_id: int,
        division: str | None,
        *,
        captured_at: datetime,
        tier: int | None = 3,
        season: int | None = 12,
        role: str = "damage",
        platform: str = "pc",
        is_ranked: bool = True,
    ) -> None:
        self.insert(
            models.UserRankSnapshot.__table__,
            id=self._id(),
            user_id=user_id,
            social_account_id=user_id,
            battle_tag=f"Player{user_id}#1234",
            platform=platform,
            role=role,
            division=division,
            tier=tier,
            season=season,
            rank_value=None,
            mapping_version=None,
            is_ranked=is_ranked,
            captured_at=captured_at,
            source=enums.RankCollectionSource.scheduled.value,
        )

    def foreign_rostered(self, user_id: int) -> None:
        """A roster spot in a *different* workspace — invisible to this one."""
        self.insert(
            models.Tournament.__table__,
            id=FOREIGN_TOURNAMENT_ID,
            workspace_id=FOREIGN_WORKSPACE_ID,
            name="Foreign",
            slug="foreign",
            is_hidden=False,
            is_league=False,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )
        member_id = self._id()
        self.insert(
            models.WorkspaceMember.__table__,
            id=member_id,
            workspace_id=FOREIGN_WORKSPACE_ID,
            player_id=user_id,
        )
        team_id = self._id()
        self.insert(
            models.Team.__table__,
            id=team_id,
            tournament_id=FOREIGN_TOURNAMENT_ID,
            name="Foreign team",
            balancer_name="Foreign team",
            captain_id=user_id,
        )
        self.insert(
            models.Player.__table__,
            id=self._id(),
            tournament_id=FOREIGN_TOURNAMENT_ID,
            team_id=team_id,
            workspace_member_id=member_id,
            name="foreign",
            role=enums.HeroClass.damage,
            rank=3000,
            is_substitution=False,
            is_newcomer=False,
            is_newcomer_role=False,
        )


class _RankCase(_EngineTestCase):
    def setUp(self) -> None:
        self.db = _RankFixture()
        self.db.tournament(REAL_TOURNAMENT_ID, name="Real", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        team = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        self.db.player(REAL_TOURNAMENT_ID, team, self.db.member(REAL_HOME_USER), name="home")
        self.db.player(REAL_TOURNAMENT_ID, team, self.db.member(REAL_AWAY_USER), name="away")

    async def run_node(self, node_type: str, **params: object) -> set[tuple[int, ...]]:
        self.db.session.commit()
        self.context_obj = await self.context(None)
        return await evaluator.evaluate(
            self.db.shim,
            {"type": node_type, "params": params},
            self.context_obj,
        )


class RankPeakTests(_RankCase):
    async def test_one_diamond_snapshot_qualifies_gold_only_does_not(self) -> None:
        self.db.snapshot(REAL_HOME_USER, "gold", tier=2, season=11, captured_at=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.snapshot(REAL_HOME_USER, "diamond", tier=4, season=12, captured_at=datetime(2026, 2, 1, tzinfo=UTC))
        self.db.snapshot(REAL_AWAY_USER, "gold", tier=1, season=12, captured_at=datetime(2026, 2, 1, tzinfo=UTC))

        result = await self.run_node("rank_peak", min_division="diamond")

        self.assertEqual({(REAL_HOME_USER,)}, result)
        self.assertEqual(
            {"division": "diamond", "tier": 4, "season": 12, "role": "damage"},
            self.context_obj.evidence[(REAL_HOME_USER,)],
        )

    async def test_unranked_snapshot_and_wrong_role_are_ignored(self) -> None:
        # Right division, but the snapshot says the player was not ranked there.
        self.db.snapshot(
            REAL_HOME_USER, "master", captured_at=datetime(2026, 2, 1, tzinfo=UTC), is_ranked=False, role="tank"
        )
        # Right division and ranked, but on the role the filter excludes.
        self.db.snapshot(REAL_AWAY_USER, "master", captured_at=datetime(2026, 2, 1, tzinfo=UTC), role="damage")

        self.assertEqual(set(), await self.run_node("rank_peak", min_division="master", role="tank"))

    async def test_snapshots_without_a_roster_spot_here_never_award(self) -> None:
        self.db.snapshot(OUTSIDER_USER, "ultimate", captured_at=datetime(2026, 2, 1, tzinfo=UTC))
        self.db.foreign_rostered(FOREIGN_USER)
        self.db.snapshot(FOREIGN_USER, "ultimate", captured_at=datetime(2026, 2, 1, tzinfo=UTC))

        self.assertEqual(set(), await self.run_node("rank_peak", min_division="diamond"))

    async def test_unknown_division_raises(self) -> None:
        self.db.snapshot(REAL_HOME_USER, "diamond", captured_at=datetime(2026, 2, 1, tzinfo=UTC))

        with self.assertRaises(ValueError):
            await self.run_node("rank_peak", min_division="radiant")


class RankClimbTests(_RankCase):
    async def test_bronze_to_gold_is_two_division_steps(self) -> None:
        self.db.snapshot(REAL_HOME_USER, "bronze", captured_at=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.snapshot(REAL_HOME_USER, "silver", captured_at=datetime(2026, 1, 15, tzinfo=UTC))
        self.db.snapshot(REAL_HOME_USER, "gold", captured_at=datetime(2026, 2, 1, tzinfo=UTC))

        result = await self.run_node("rank_climb", op=">=", value=2)

        self.assertEqual({(REAL_HOME_USER,)}, result)
        self.assertEqual(
            {"from_division": "bronze", "to_division": "gold", "steps": 2, "season": 12},
            self.context_obj.evidence[(REAL_HOME_USER,)],
        )
        self.assertEqual(set(), await self.run_node("rank_climb", op=">=", value=3))

    async def test_a_fall_is_not_a_climb(self) -> None:
        self.db.snapshot(REAL_HOME_USER, "grandmaster", captured_at=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.snapshot(REAL_HOME_USER, "gold", captured_at=datetime(2026, 2, 1, tzinfo=UTC))
        # Recovering below where the series started is still not a climb.
        self.db.snapshot(REAL_HOME_USER, "platinum", captured_at=datetime(2026, 3, 1, tzinfo=UTC))

        self.assertEqual(set(), await self.run_node("rank_climb", op=">=", value=1))

    async def test_climb_spanning_two_seasons_is_two_series(self) -> None:
        self.db.snapshot(REAL_HOME_USER, "bronze", season=11, captured_at=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.snapshot(REAL_HOME_USER, "gold", season=12, captured_at=datetime(2026, 2, 1, tzinfo=UTC))

        self.assertEqual(set(), await self.run_node("rank_climb", op=">=", value=1))

    async def test_each_role_climbs_on_its_own(self) -> None:
        self.db.snapshot(REAL_HOME_USER, "bronze", role="tank", captured_at=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.snapshot(REAL_HOME_USER, "silver", role="tank", captured_at=datetime(2026, 2, 1, tzinfo=UTC))
        # The support series alone would be a 3-step climb, but it is filtered out.
        self.db.snapshot(REAL_HOME_USER, "bronze", role="support", captured_at=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.snapshot(REAL_HOME_USER, "platinum", role="support", captured_at=datetime(2026, 2, 1, tzinfo=UTC))

        self.assertEqual({(REAL_HOME_USER,)}, await self.run_node("rank_climb", op="==", value=1, role="tank"))
        self.assertEqual(set(), await self.run_node("rank_climb", op=">=", value=2, role="tank"))
