"""Achievement leaves read a member who played for two teams of one tournament once: placements from
``participant_result``, stage and series facts from the member's final team (spec §11.2–11.4).

Uses the SQLite fixture from ``test_scrim_achievement_isolation``.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
for candidate in (
    str(REPO_BACKEND_ROOT),
    str(REPO_BACKEND_ROOT / "stats-service"),
    str(Path(__file__).resolve().parent),
):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from test_achievement_engine_nodes import CLIMB_GRID, _NodeCase, evaluator  # noqa: E402
from test_scrim_achievement_isolation import (  # noqa: E402
    IS_CAPTAIN_RULE,
    LATER_TOURNAMENT_ID,
    REAL_AWAY_USER,
    REAL_HOME_USER,
    REAL_TOURNAMENT_ID,
    WORKSPACE_ID,
)

from shared.core.enums import EncounterStatus, StageType  # noqa: E402
from shared.domain.achievements.validation import derive_depends_on  # noqa: E402
from src.services.achievement.engine import runner  # noqa: E402

HOME_KEY = (REAL_HOME_USER, REAL_TOURNAMENT_ID)
JAN, FEB = datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 2, 1, tzinfo=UTC)


class TwoTeamMemberConditionTests(_NodeCase):
    def _two_teams(self, tournament_id: int = REAL_TOURNAMENT_ID, *, start: datetime = JAN) -> tuple[int, int]:
        """REAL_HOME_USER plays for team A as tank, then for team B (the final team) as damage."""
        self.db.tournament(tournament_id, name=f"T{tournament_id}", is_hidden=False, start=start)
        member = self.db.member(REAL_HOME_USER)
        first = self.db.team(tournament_id, "A", captain_id=REAL_HOME_USER)
        final = self.db.team(tournament_id, "B", captain_id=None)
        self.db.player(tournament_id, first, member, name="home-a", role="tank")
        self.db.player(tournament_id, final, member, name="home-b", role="damage")
        return first, final

    async def run_tree(self, tree: dict, tournament_id: int | None, *, grid=None) -> set:
        return await evaluator.evaluate(self.db.shim, tree, await self.context(tournament_id, grid=grid))

    async def test_standing_position_reads_the_final_team_result(self) -> None:
        first, final = self._two_teams()
        self.db.standing(REAL_TOURNAMENT_ID, first, overall_position=1)
        self.db.placement(REAL_TOURNAMENT_ID, final, 3)
        self.db.session.commit()

        position = {"type": "standing_position", "params": {"op": "==", "value": 1}}
        self.assertEqual(set(), await self.run_tree(position, REAL_TOURNAMENT_ID))
        position["params"] = {"op": "<=", "value": 3}
        self.assertEqual({HOME_KEY}, await self.run_tree(position, REAL_TOURNAMENT_ID))

    async def test_standing_count_by_role_counts_the_final_team_role_once(self) -> None:
        first, final = self._two_teams()
        self.db.standing(REAL_TOURNAMENT_ID, first, overall_position=1)
        self.db.standing(REAL_TOURNAMENT_ID, final, overall_position=1)
        self.db.placement(REAL_TOURNAMENT_ID, final, 1)
        self.db.session.commit()

        params = {"position_op": "==", "position_value": 1, "count_by": "role", "op": ">=", "value": 2}
        self.assertEqual(set(), await self.run_tree({"type": "standing_count", "params": params}, None))
        params["value"] = 1
        self.assertEqual({(REAL_HOME_USER,)}, await self.run_tree({"type": "standing_count", "params": params}, None))

    async def test_a_non_final_team_win_does_not_extend_a_win_streak(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=JAN)
        won = self.db.team(REAL_TOURNAMENT_ID, "W", captain_id=REAL_HOME_USER)
        self.db.player(REAL_TOURNAMENT_ID, won, self.db.member(REAL_HOME_USER), name="home")
        self.db.standing(REAL_TOURNAMENT_ID, won, overall_position=1)
        self.db.placement(REAL_TOURNAMENT_ID, won, 1)
        first, final = self._two_teams(LATER_TOURNAMENT_ID, start=FEB)
        self.db.standing(LATER_TOURNAMENT_ID, first, overall_position=1)
        self.db.placement(LATER_TOURNAMENT_ID, final, 2)
        self.db.session.commit()

        streak = {"type": "consecutive", "params": {"metric": "win", "min_streak": 2}}
        self.assertEqual(set(), await self.run_tree(streak, None))

    async def test_reached_playoffs_is_the_final_team_reaching_them(self) -> None:
        first, final = self._two_teams()
        groups = self.db.stage(REAL_TOURNAMENT_ID, name="groups", stage_type=StageType.ROUND_ROBIN, order=1)
        playoff = self.db.stage(REAL_TOURNAMENT_ID, name="playoff", stage_type=StageType.SINGLE_ELIMINATION, order=2)
        self.db.standing(REAL_TOURNAMENT_ID, first, overall_position=1, stage_id=playoff)
        self.db.standing(REAL_TOURNAMENT_ID, final, overall_position=5, stage_id=groups, buchholz=1.0)
        self.db.placement(REAL_TOURNAMENT_ID, final, 5)
        self.db.session.commit()

        self.assertEqual(set(), await self.run_tree({"type": "reached_playoffs", "params": {}}, REAL_TOURNAMENT_ID))

    async def test_tournament_winrate_is_the_final_team_winrate(self) -> None:
        first, final = self._two_teams()
        rival_a = self.db.team(REAL_TOURNAMENT_ID, "C", captain_id=REAL_AWAY_USER)
        rival_b = self.db.team(REAL_TOURNAMENT_ID, "D", captain_id=None)
        self.db.encounter(
            REAL_TOURNAMENT_ID, first, rival_a, first_score=2, second_score=0, status=EncounterStatus.COMPLETED
        )
        self.db.encounter(
            REAL_TOURNAMENT_ID, final, rival_b, first_score=0, second_score=2, status=EncounterStatus.COMPLETED
        )
        self.db.placement(REAL_TOURNAMENT_ID, final, 4, field_size=4)
        self.db.session.commit()

        # Both teams together are 2 of 4 maps; the final team alone is 0 of 2.
        winrate = {"type": "tournament_winrate", "params": {"op": ">=", "value": 0.5}}
        self.assertEqual(set(), await self.run_tree(winrate, REAL_TOURNAMENT_ID))

    async def test_div_change_reads_the_final_team_rank(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=JAN)
        only = self.db.team(REAL_TOURNAMENT_ID, "O", captain_id=REAL_HOME_USER)
        member = self.db.member(REAL_HOME_USER)
        self.db.player(REAL_TOURNAMENT_ID, only, member, name="home", rank=500)
        self.db.tournament(LATER_TOURNAMENT_ID, name="T2", is_hidden=False, start=FEB)
        first = self.db.team(LATER_TOURNAMENT_ID, "A", captain_id=REAL_HOME_USER)
        final = self.db.team(LATER_TOURNAMENT_ID, "B", captain_id=None)
        self.db.player(LATER_TOURNAMENT_ID, first, member, name="home-a", rank=2500)
        self.db.player(LATER_TOURNAMENT_ID, final, member, name="home-b", rank=500)
        self.db.placement(LATER_TOURNAMENT_ID, final, 1)
        self.db.session.commit()

        for direction in ("up", "down"):
            change = {"type": "div_change", "params": {"direction": direction, "min_shift": 1}}
            self.assertEqual(set(), await self.run_tree(change, None, grid=CLIMB_GRID))


class ResultWriteSelectsPlacementRulesTests(_NodeCase):
    async def test_participant_result_change_selects_placement_rules_only(self) -> None:
        position = {"type": "standing_position", "params": {"op": "==", "value": 1}}
        self.db.rule(1, "winner", position, derive_depends_on(position, discipline="overwatch"))
        self.db.rule(2, "captain", IS_CAPTAIN_RULE, derive_depends_on(IS_CAPTAIN_RULE, discipline="overwatch"))
        self.db.session.commit()

        selected = await runner._select_rules(
            self.db.shim, WORKSPACE_ID, "overwatch", None, ["tournament.participant_result"]
        )
        self.assertEqual(["winner"], [rule.slug for rule in selected])
