"""Node regressions for the registration- and draft-derived condition leaves.

These three nodes read rows nothing else in the engine touches
(``balancer.registration``, ``tournament.tournament_phase_schedule`` and the
``balancer.draft_*`` family), and each of them has a way of awarding the wrong
person: a sheet-imported registration has no player identity at all, a
tournament may simply never have had a registration phase, and a draft's
captain is a different person from everyone they picked.
"""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"
for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT), str(Path(__file__).resolve().parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import test_scrim_achievement_isolation as _scrim  # noqa: E402
from test_scrim_achievement_isolation import (  # noqa: E402
    LATER_TOURNAMENT_ID,
    REAL_AWAY_USER,
    REAL_HOME_USER,
    REAL_TOURNAMENT_ID,
    WORKSPACE_ID,
    _EngineTestCase,
)

from shared.core.enums import DraftPickStatus, DraftPlayerStatus, DraftStatus, TournamentStatus  # noqa: E402

# Importing the modules is what registers the nodes.
importlib.import_module("src.services.achievement.engine.conditions.registration")  # noqa: E402
importlib.import_module("src.services.achievement.engine.conditions.draft")  # noqa: E402

evaluator = _scrim.evaluator
eval_context = _scrim.eval_context
models = _scrim.models

USER_C = 104

OTHER_WORKSPACE_ID = 2
FOREIGN_TOURNAMENT_ID = 99

REG_OPEN = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
CHECK_IN_OPEN = datetime(2026, 5, 8, 18, 0, tzinfo=UTC)


class _RegistrationFixture(_scrim._Fixture):
    def phase(self, tournament_id: int, status: TournamentStatus, starts_at: datetime) -> None:
        self.insert(
            models.TournamentPhaseSchedule.__table__,
            id=self._id(),
            tournament_id=tournament_id,
            status=status,
            starts_at=starts_at,
        )

    def registration(
        self,
        tournament_id: int,
        member_id: int | None,
        *,
        submitted_at: datetime,
        checked_in: bool = False,
        checked_in_at: datetime | None = None,
        is_substitute: bool = False,
        is_team_manager: bool = False,
        deleted_at: datetime | None = None,
    ) -> int:
        registration_id = self._id()
        self.insert(
            models.BalancerRegistration.__table__,
            id=registration_id,
            tournament_id=tournament_id,
            workspace_member_id=member_id,
            status="approved",
            submitted_at=submitted_at,
            checked_in=checked_in,
            checked_in_at=checked_in_at,
            is_substitute=is_substitute,
            is_team_manager=is_team_manager,
            deleted_at=deleted_at,
        )
        return registration_id

    def draft_session(self, tournament_id: int, *, workspace_id: int = WORKSPACE_ID) -> int:
        session_id = self._id()
        self.insert(
            models.DraftSession.__table__,
            id=session_id,
            tournament_id=tournament_id,
            workspace_id=workspace_id,
            status=DraftStatus.COMPLETED,
        )
        return session_id

    def draft_team(self, session_id: int, *, captain_member_id: int | None, position: int) -> int:
        team_id = self._id()
        self.insert(
            models.DraftTeam.__table__,
            id=team_id,
            session_id=session_id,
            captain_workspace_member_id=captain_member_id,
            name=f"draft-team-{position}",
            draft_position=position,
        )
        return team_id

    def draft_player(self, session_id: int, registration_id: int, member_id: int | None) -> int:
        player_id = self._id()
        self.insert(
            models.DraftPlayer.__table__,
            id=player_id,
            session_id=session_id,
            registration_id=registration_id,
            workspace_member_id=member_id,
            status=DraftPlayerStatus.PICKED,
        )
        return player_id

    def draft_pick(
        self,
        session_id: int,
        team_id: int,
        *,
        overall_no: int,
        picked_player_id: int | None,
        round_no: int = 1,
        status: str = DraftPickStatus.COMPLETED,
        is_autopick: bool = False,
    ) -> int:
        pick_id = self._id()
        self.insert(
            models.DraftPick.__table__,
            id=pick_id,
            session_id=session_id,
            overall_no=overall_no,
            round_no=round_no,
            pick_in_round=overall_no,
            draft_team_id=team_id,
            picked_player_id=picked_player_id,
            status=status,
            is_autopick=is_autopick,
        )
        return pick_id

    def foreign_tournament(self, tournament_id: int) -> None:
        """A tournament in another workspace — ``_Fixture.tournament`` always uses ours."""
        self.insert(
            models.Tournament.__table__,
            id=tournament_id,
            workspace_id=OTHER_WORKSPACE_ID,
            name="foreign",
            slug=f"tournament-{tournament_id}",
            is_hidden=False,
            is_league=False,
            start_date=REG_OPEN,
        )


class _RegistrationCase(_EngineTestCase):
    def setUp(self) -> None:
        self.db = _RegistrationFixture()

    async def context(self, tournament_id: int | None):  # noqa: ANN201
        grid = await _scrim.runner._resolve_grid(self.db.shim, WORKSPACE_ID, None)
        tournament = self.db.session.get(models.Tournament, tournament_id) if tournament_id else None
        return eval_context.EvalContext(
            workspace_id=WORKSPACE_ID,
            tournament=tournament,
            grid=grid,
            normalizer=None,
        )

    def open_tournament(self, tournament_id: int = REAL_TOURNAMENT_ID, *, with_phases: bool = True) -> None:
        self.db.tournament(tournament_id, name="Cup", is_hidden=False, start=REG_OPEN)
        if with_phases:
            self.db.phase(tournament_id, TournamentStatus.REGISTRATION, REG_OPEN)
            self.db.phase(tournament_id, TournamentStatus.CHECK_IN, CHECK_IN_OPEN)

    async def evaluate(self, rule: dict, tournament_id: int | None):  # noqa: ANN201
        return await evaluator.evaluate(self.db.shim, rule, await self.context(tournament_id))


class RegistrationTimingTests(_RegistrationCase):
    async def test_signup_window_excludes_the_late_entrant(self) -> None:
        self.open_tournament()
        self.db.registration(
            REAL_TOURNAMENT_ID, self.db.member(REAL_HOME_USER), submitted_at=REG_OPEN + timedelta(minutes=30)
        )
        self.db.registration(
            REAL_TOURNAMENT_ID, self.db.member(REAL_AWAY_USER), submitted_at=REG_OPEN + timedelta(days=2)
        )
        self.db.session.commit()

        result = await self.evaluate(
            {"type": "registration_timing", "params": {"event": "signup", "op": "<=", "value": 60}},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, result)

    async def test_sheet_registration_without_a_member_is_never_awarded(self) -> None:
        self.open_tournament()
        self.db.registration(REAL_TOURNAMENT_ID, None, submitted_at=REG_OPEN + timedelta(minutes=5))
        self.db.registration(
            REAL_TOURNAMENT_ID,
            self.db.member(REAL_AWAY_USER),
            submitted_at=REG_OPEN + timedelta(minutes=5),
            deleted_at=REG_OPEN + timedelta(days=1),
        )
        self.db.session.commit()

        result = await self.evaluate(
            {"type": "registration_timing", "params": {"event": "signup", "op": "<=", "value": 60}},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual(set(), result)

    async def test_tournament_without_a_registration_phase_awards_nobody(self) -> None:
        self.open_tournament(with_phases=False)
        self.db.registration(REAL_TOURNAMENT_ID, self.db.member(REAL_HOME_USER), submitted_at=REG_OPEN)
        self.db.session.commit()

        result = await self.evaluate(
            {"type": "registration_timing", "params": {"event": "signup", "op": "<=", "value": 60}},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual(set(), result)

    async def test_check_in_measures_against_the_check_in_phase(self) -> None:
        """The same row qualifies on check-in lateness while failing the signup window."""
        self.open_tournament()
        self.db.registration(
            REAL_TOURNAMENT_ID,
            self.db.member(REAL_HOME_USER),
            submitted_at=REG_OPEN + timedelta(days=2),
            checked_in=True,
            checked_in_at=CHECK_IN_OPEN - timedelta(minutes=10),
        )
        # Registered but never checked in: not measurable, not a failed threshold.
        self.db.registration(
            REAL_TOURNAMENT_ID, self.db.member(REAL_AWAY_USER), submitted_at=REG_OPEN + timedelta(minutes=1)
        )
        self.db.session.commit()

        result = await self.evaluate(
            {"type": "registration_timing", "params": {"event": "check_in", "op": "<=", "value": -5}},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, result)

    async def test_other_workspace_registration_is_invisible(self) -> None:
        self.open_tournament(LATER_TOURNAMENT_ID)
        self.db.foreign_tournament(FOREIGN_TOURNAMENT_ID)
        self.db.phase(FOREIGN_TOURNAMENT_ID, TournamentStatus.REGISTRATION, REG_OPEN)
        self.db.registration(
            LATER_TOURNAMENT_ID, self.db.member(REAL_HOME_USER), submitted_at=REG_OPEN + timedelta(minutes=1)
        )
        self.db.registration(
            FOREIGN_TOURNAMENT_ID, self.db.member(REAL_AWAY_USER), submitted_at=REG_OPEN + timedelta(minutes=1)
        )
        self.db.session.commit()

        result = await self.evaluate(
            {"type": "registration_timing", "params": {"event": "signup", "op": "<=", "value": 60}},
            None,
        )
        self.assertEqual({(REAL_HOME_USER, LATER_TOURNAMENT_ID)}, result)


class RegistrationFlagTests(_RegistrationCase):
    async def test_substitute_flag_selects_only_the_bench(self) -> None:
        self.open_tournament()
        self.db.registration(
            REAL_TOURNAMENT_ID, self.db.member(REAL_HOME_USER), submitted_at=REG_OPEN, is_substitute=True
        )
        self.db.registration(REAL_TOURNAMENT_ID, self.db.member(REAL_AWAY_USER), submitted_at=REG_OPEN)
        self.db.session.commit()

        result = await self.evaluate(
            {"type": "registration_flag", "params": {"flag": "substitute"}},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, result)

    async def test_explicit_false_value_inverts_the_flag(self) -> None:
        self.open_tournament()
        self.db.registration(
            REAL_TOURNAMENT_ID,
            self.db.member(REAL_HOME_USER),
            submitted_at=REG_OPEN,
            checked_in=True,
            checked_in_at=CHECK_IN_OPEN,
        )
        self.db.registration(REAL_TOURNAMENT_ID, self.db.member(REAL_AWAY_USER), submitted_at=REG_OPEN)
        self.db.session.commit()

        result = await self.evaluate(
            {"type": "registration_flag", "params": {"flag": "checked_in", "value": False}},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual({(REAL_AWAY_USER, REAL_TOURNAMENT_ID)}, result)


class DraftPickTests(_RegistrationCase):
    def draft(self, tournament_id: int = REAL_TOURNAMENT_ID) -> dict:
        """A one-team draft: a captain plus two picked players, first overall is HOME."""
        session_id = self.db.draft_session(tournament_id)
        team_id = self.db.draft_team(session_id, captain_member_id=self.db.member(USER_C), position=1)
        first = self.db.draft_player(
            session_id,
            self.db.registration(tournament_id, self.db.member(REAL_HOME_USER), submitted_at=REG_OPEN),
            self.db.member(REAL_HOME_USER),
        )
        second = self.db.draft_player(
            session_id,
            self.db.registration(tournament_id, self.db.member(REAL_AWAY_USER), submitted_at=REG_OPEN),
            self.db.member(REAL_AWAY_USER),
        )
        self.db.draft_pick(session_id, team_id, overall_no=1, picked_player_id=first)
        self.db.draft_pick(session_id, team_id, overall_no=2, picked_player_id=second, round_no=2, is_autopick=True)
        return {"session_id": session_id, "team_id": team_id, "first": first, "second": second}

    async def test_first_overall_pick_is_exactly_one_player(self) -> None:
        self.open_tournament()
        self.draft()
        self.db.session.commit()

        result = await self.evaluate(
            {"type": "draft_pick", "params": {"op": "==", "value": 1}},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, result)

    async def test_captain_role_awards_the_captain_not_their_picks(self) -> None:
        self.open_tournament()
        self.draft()
        self.db.session.commit()

        result = await self.evaluate(
            {"type": "draft_pick", "params": {"role": "captain"}},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual({(USER_C, REAL_TOURNAMENT_ID)}, result)

    async def test_autopick_filter_and_unfinished_picks(self) -> None:
        self.open_tournament()
        draft = self.draft()
        # An on-clock pick already pointing at a player has not happened yet.
        pending_player = self.db.draft_player(
            draft["session_id"],
            self.db.registration(REAL_TOURNAMENT_ID, self.db.member(USER_C), submitted_at=REG_OPEN),
            self.db.member(USER_C),
        )
        self.db.draft_pick(
            draft["session_id"],
            draft["team_id"],
            overall_no=3,
            picked_player_id=pending_player,
            round_no=3,
            status=DraftPickStatus.ON_CLOCK,
            is_autopick=True,
        )
        self.db.session.commit()

        result = await self.evaluate(
            {"type": "draft_pick", "params": {"autopick": True}},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual({(REAL_AWAY_USER, REAL_TOURNAMENT_ID)}, result)

    async def test_draft_in_another_workspace_is_invisible(self) -> None:
        self.db.foreign_tournament(FOREIGN_TOURNAMENT_ID)
        # The session claims our workspace; the tournament it belongs to does not.
        session_id = self.db.draft_session(FOREIGN_TOURNAMENT_ID, workspace_id=WORKSPACE_ID)
        team_id = self.db.draft_team(session_id, captain_member_id=self.db.member(USER_C), position=1)
        picked = self.db.draft_player(
            session_id,
            self.db.registration(FOREIGN_TOURNAMENT_ID, self.db.member(REAL_HOME_USER), submitted_at=REG_OPEN),
            self.db.member(REAL_HOME_USER),
        )
        self.db.draft_pick(session_id, team_id, overall_no=1, picked_player_id=picked)
        self.db.session.commit()

        self.assertEqual(set(), await self.evaluate({"type": "draft_pick", "params": {}}, None))
        self.assertEqual(set(), await self.evaluate({"type": "draft_pick", "params": {"role": "captain"}}, None))


class EvidenceTests(_RegistrationCase):
    async def test_every_node_records_why_the_player_qualified(self) -> None:
        self.open_tournament()
        member = self.db.member(REAL_HOME_USER)
        registration_id = self.db.registration(
            REAL_TOURNAMENT_ID, member, submitted_at=REG_OPEN + timedelta(minutes=30), is_team_manager=True
        )
        session_id = self.db.draft_session(REAL_TOURNAMENT_ID)
        team_id = self.db.draft_team(session_id, captain_member_id=self.db.member(REAL_AWAY_USER), position=2)
        drafted = self.db.draft_player(session_id, registration_id, member)
        self.db.draft_pick(session_id, team_id, overall_no=4, picked_player_id=drafted, round_no=2)
        self.db.session.commit()

        key = (REAL_HOME_USER, REAL_TOURNAMENT_ID)
        context = await self.context(REAL_TOURNAMENT_ID)
        await evaluator.evaluate(
            self.db.shim,
            {"type": "registration_timing", "params": {"event": "signup", "op": "<=", "value": 60}},
            context,
        )
        self.assertEqual(30.0, context.evidence[key]["minutes"])
        self.assertEqual("signup", context.evidence[key]["event"])

        context = await self.context(REAL_TOURNAMENT_ID)
        rule = {"type": "registration_flag", "params": {"flag": "team_manager"}}
        await evaluator.evaluate(self.db.shim, rule, context)
        self.assertEqual({"flag": "team_manager", "value": True}, context.evidence[key])

        context = await self.context(REAL_TOURNAMENT_ID)
        await evaluator.evaluate(self.db.shim, {"type": "draft_pick", "params": {}}, context)
        self.assertEqual({"overall_no": 4, "round_no": 2, "autopick": False}, context.evidence[key])

        context = await self.context(REAL_TOURNAMENT_ID)
        await evaluator.evaluate(self.db.shim, {"type": "draft_pick", "params": {"role": "captain"}}, context)
        self.assertEqual({"draft_position": 2}, context.evidence[(REAL_AWAY_USER, REAL_TOURNAMENT_ID)])
