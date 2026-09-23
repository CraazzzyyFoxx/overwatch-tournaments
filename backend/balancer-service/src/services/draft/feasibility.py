"""Session-scoped draft feasibility: DB-backed reads plus CPU-offloaded analysis.

Pure value types live in ``src.domain.draft.entities``; the pure bipartite-
matching rules live in ``src.domain.draft.feasibility``. This module is the
only one of the three that touches a database session or the event loop — it
loads rows, translates them into the algorithm's input, and runs the
CPU-bound matching via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftAutopickStrategy, DraftPlayerStatus, DraftStatus
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.roster_shape import RosterShape
from shared.models.balancer.draft import DraftPick, DraftSession
from shared.repository.draft import DraftPickRepository, DraftPlayerRepository, DraftTeamRepository
from shared.services.roster_shape_access import get_effective_roster_shape
from src.domain.draft import fit as sug
from src.domain.draft import rules
from src.domain.draft.entities import (
    DraftAssignment,
    DraftFeasibilityReport,
    DraftFeasibilityState,
    DraftPickOption,
    DraftSnapshot,
    FitConfig,
    FitResult,
    TeamFitScore,
)
from src.domain.draft.feasibility import (
    analyze_draft_feasibility,
    build_feasibility_state,
    evaluate_pick_options,
)
from src.services.draft import loaders
from src.services.draft.rosters import DraftRosterService, draft_rosters

__all__ = ("DraftFeasibilityService", "feasibility_service")


class DraftFeasibilityService:
    def __init__(
        self,
        *,
        teams_repo: DraftTeamRepository = DraftTeamRepository(),
        players_repo: DraftPlayerRepository = DraftPlayerRepository(),
        picks_repo: DraftPickRepository = DraftPickRepository(),
        rosters: DraftRosterService = draft_rosters,
    ) -> None:
        self.teams_repo = teams_repo
        self.players_repo = players_repo
        self.picks_repo = picks_repo
        self.rosters = rosters

    async def load_snapshot(self, session: AsyncSession, draft_session: DraftSession) -> DraftSnapshot:
        """Load the session's rows once, and resolve their rosters once with them.

        Roles and ranks ride in the snapshot rather than being fetched per step,
        so a single request cannot see two different answers for the same player.
        """
        teams = await self.teams_repo.list_by_session(session, draft_session.id)
        players = await self.players_repo.list_by_session(session, draft_session.id, options=loaders.player_options())
        picks = await self.picks_repo.list_by_session(session, draft_session.id)
        return DraftSnapshot(
            teams=tuple(teams),
            players=tuple(players),
            picks=tuple(picks),
            rosters=await self.rosters.load(session, draft_session, players),
        )

    async def resolve_shape(self, session: AsyncSession, draft_session: DraftSession) -> RosterShape:
        """The roster shape this draft's teams must fill.

        The single place that knows which ids a draft resolves its shape from, so
        callers never re-derive the tournament/workspace precedence. Both levels are
        cache-backed, so calling this per request step is cheap.
        """
        return await get_effective_roster_shape(
            session,
            tournament_id=draft_session.tournament_id,
            workspace_id=draft_session.workspace_id,
        )

    async def state_from_snapshot(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        snapshot: DraftSnapshot,
    ) -> DraftFeasibilityState:
        """Translate an already-loaded snapshot into the matching input."""
        return build_feasibility_state(
            shape=await self.resolve_shape(session, draft_session),
            teams=snapshot.teams,
            players=snapshot.players,
            picks=snapshot.picks,
            rosters=snapshot.rosters,
        )

    async def load_feasibility_state(self, session: AsyncSession, draft_session: DraftSession) -> DraftFeasibilityState:
        return await self.state_from_snapshot(session, draft_session, await self.load_snapshot(session, draft_session))

    async def analyze_session(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        *,
        hypothetical: DraftAssignment | None = None,
        state: DraftFeasibilityState | None = None,
    ) -> DraftFeasibilityReport:
        if state is None:
            state = await self.load_feasibility_state(session, draft_session)
        # The bipartite matching is pure CPU; run it off the event loop.
        return await asyncio.to_thread(
            analyze_draft_feasibility,
            team_ids=state.team_ids,
            slot_targets=state.slot_targets,
            players=state.players,
            assignments=state.assignments,
            hypothetical=hypothetical,
        )

    async def evaluate_session_pick_options(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        *,
        team_id: int,
        state: DraftFeasibilityState | None = None,
    ) -> tuple[DraftPickOption, ...]:
        if state is None:
            state = await self.load_feasibility_state(session, draft_session)
        # Up to 21 forced-pick matchings (see evaluate_pick_options) — pure CPU,
        # run them off the event loop.
        return await asyncio.to_thread(
            evaluate_pick_options,
            team_id=team_id,
            team_ids=state.team_ids,
            slot_targets=state.slot_targets,
            players=state.players,
            assignments=state.assignments,
        )

    async def options_for_current_pick(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        pick: DraftPick,
        *,
        actor_auth_user_id: int,
        actor_player_ids: list[int],
        is_workspace_admin: bool,
    ) -> tuple[DraftPickOption, ...]:
        if draft_session.current_pick_id != pick.id:
            raise HTTPException(status_code=409, detail="Options are available only for the current pick")
        team = await self.teams_repo.get(
            session,
            pick.draft_team_id,
            options=loaders.team_options(),
            populate_existing=True,
        )
        if not is_workspace_admin and not rules.is_on_clock_captain(
            team,
            actor_auth_user_id=actor_auth_user_id,
            actor_player_ids=actor_player_ids,
        ):
            raise HTTPException(
                status_code=403,
                detail="Only the on-clock captain or an admin may read options",
            )
        return await self.evaluate_session_pick_options(session, draft_session, team_id=pick.draft_team_id)

    async def rank_current_suggestions(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
    ) -> tuple[DraftPick, list[FitResult]]:
        if draft_session.current_pick_id is None:
            raise HTTPException(status_code=409, detail="Draft has no current pick")
        current = await self.picks_repo.get(session, draft_session.current_pick_id)
        if current is None:
            raise HTTPException(status_code=409, detail="Draft has no current pick")
        snapshot = await self.load_snapshot(session, draft_session)
        available = [p for p in snapshot.players if p.status == "available"]
        shape = await self.resolve_shape(session, draft_session)
        counts = rules.team_slot_counts(
            snapshot.players, snapshot.picks, current.draft_team_id, shape, snapshot.rosters
        )
        capacity = rules.role_openings(shape, counts)
        # Same construction as autopick's, from the same snapshot rosters, so
        # a suggestion and the autopick that follows it cannot disagree.
        fit_players = sug.fit_players(available, snapshot.rosters)
        options = await self.evaluate_session_pick_options(
            session,
            draft_session,
            team_id=current.draft_team_id,
            state=await self.state_from_snapshot(session, draft_session, snapshot),
        )
        safe_options = {(option.player_id, option.role) for option in options if option.is_safe}
        ranked = sug.rank_suggestions(
            fit_players,
            capacity,
            FitConfig(),
            strategy=DraftAutopickStrategy(draft_session.autopick_strategy),
            limit=5,
            allowed_options=safe_options,
        )
        return current, ranked

    async def team_fit_scores(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        *,
        team_id: int,
    ) -> list[TeamFitScore]:
        """Fit for every (available player x role this team can still seat), 1..99.

        NOT the autopick answer: no global-safety filter and no captain queue --
        this is the "how well would they fit us" column a captain reads while the
        board is still open, so it covers every choice they could make, not only
        the one the clock would take. Same candidate list and same ``player_fit``
        as autopick, so the two numbers cannot come from different rosters.
        """
        if draft_session.status in (DraftStatus.COMPLETED.value, DraftStatus.CANCELLED.value):
            return []
        snapshot = await self.load_snapshot(session, draft_session)
        shape = await self.resolve_shape(session, draft_session)
        counts = rules.team_slot_counts(snapshot.players, snapshot.picks, team_id, shape, snapshot.rosters)
        capacity = rules.role_openings(shape, counts)
        if not any(opening > 0 for opening in capacity.values()):
            return []  # this team's roster is full
        available = [p for p in snapshot.players if p.status == DraftPlayerStatus.AVAILABLE.value]
        players = sug.fit_players(available, snapshot.rosters)
        results = sug.candidates(
            players, capacity, FitConfig(), DraftAutopickStrategy(draft_session.autopick_strategy)
        )
        by_id = {player.player_id: player for player in players}
        ordered = sorted(results, key=lambda result: sug.sort_key(result, by_id))
        if not shape.has_role_slots:
            # No seat carries a role, so a player is one entry: their best one.
            best: dict[int, FitResult] = {}
            for result in ordered:
                best.setdefault(result.player_id, result)
            ordered = list(best.values())
        return [
            TeamFitScore(
                player_id=result.player_id,
                role=result.role if shape.has_role_slots else None,
                score=score,
            )
            for result, score in zip(ordered, sug.normalized_scores(ordered), strict=True)
        ]


feasibility_service = DraftFeasibilityService()
