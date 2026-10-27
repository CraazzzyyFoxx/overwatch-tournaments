"""Session-scoped draft feasibility: DB-backed reads plus CPU-offloaded analysis.

Pure value types live in ``src.domain.draft.entities``; the pure bipartite-
matching rules live in ``src.domain.draft.feasibility``. This module is the
only one of the three that touches a database session or the event loop — it
loads rows, translates them into the algorithm's input, and runs the
CPU-bound matching via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import dataclasses
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftAutopickStrategy, DraftPlayerStatus, DraftStatus
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import DISCIPLINES
from shared.domain.roster_shape import RosterShape
from shared.models.draft import DraftPick, DraftSession
from shared.repository.draft import DraftPickRepository, DraftPlayerRepository, DraftTeamRepository
from src.domain.balancer.config.defaults import AlgorithmConfig, apply_config_overrides, default_role_settings
from src.domain.balancer.config.public_contract import normalize_config_payload
from src.domain.draft import fit as sug
from src.domain.draft import rules
from src.domain.draft.entities import (
    DraftAssignment,
    DraftFeasibilityReport,
    DraftFeasibilityState,
    DraftPickOption,
    DraftSnapshot,
    FitPlayer,
    FitResult,
    TeamFitScore,
)
from src.domain.draft.feasibility import (
    analyze_draft_feasibility,
    build_feasibility_state,
    evaluate_pick_options,
)
from src.services.draft import loaders
from src.services.draft import realtime as draft_rt
from src.services.draft.rosters import DraftRosterService, draft_rosters

__all__ = ("DraftFeasibilityService", "feasibility_service", "single_flight")


_inflight: dict[str, asyncio.Future[Any]] = {}


async def single_flight[T](key: str, compute: Callable[[], Awaitable[T]]) -> T:
    """Run ``compute`` once per ``key`` at a time in this process; concurrent callers await that run.

    A waiter never inherits the leader's failure: if the leader raises (or its
    request is cancelled), the waiter computes for itself, so one caller's error
    or disconnect cannot fail everybody else's request.
    """
    pending = _inflight.get(key)
    if pending is not None:
        try:
            return await asyncio.shield(pending)
        except Exception:  # noqa: BLE001 — the leader failed; answer for ourselves
            return await compute()
    future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
    _inflight[key] = future
    try:
        result = await compute()
    except BaseException as exc:
        future.set_exception(exc if isinstance(exc, Exception) else RuntimeError("shared read abandoned"))
        future.exception()  # retrieved: waiters recover on their own, nothing left to log
        raise
    else:
        future.set_result(result)
        return result
    finally:
        del _inflight[key]


@dataclasses.dataclass(slots=True)
class _ReadState:
    """One board state as every read of it sees it."""

    at: float
    key: str
    snapshot: DraftSnapshot
    #: ``sug.fit_players`` of the available players: the same list for every team's fit, so the first builds it.
    fit_players: list[FitPlayer] | None = None
    #: ``evaluate_pick_options`` per team: the on-clock captain's options and its queue's autopick preview ask the
    #: same matchings of the same state, so they run once.
    pick_options: dict[int, tuple[DraftPickOption, ...]] = dataclasses.field(default_factory=dict)


# Bounds staleness for writes that bypass the event log, like the board's TTL.
_READ_SNAPSHOT_TTL_SECONDS = 15.0
_read_snapshots: dict[str, _ReadState] = {}
# The shape (the owner's team format) and role impacts (its balancer knobs) behind the fit reads: neither moves with
# the board, yet each fit, asked per team by every captain at once, re-read both. Same staleness bound.
_read_contexts: dict[tuple[int, int], tuple[float, RosterShape, dict[str, float]]] = {}


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
        """The roster shape this draft's teams must fill. The single place callers ask; ``loaders.shape`` knows the
        owner."""
        return await loaders.shape(session, draft_session)

    async def resolve_role_impact(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
    ) -> dict[str, float]:
        """Base per-role impact for this draft: defaults <- the owner's stored knobs (``loaders.role_overrides``).

        Read live on every call rather than captured at session start, so the
        operator moving a role's weight in the balancer drawer moves what the
        draft's autopick, /suggestions and /fit consider a good fit too.
        """
        config = apply_config_overrides(
            AlgorithmConfig(role_settings=default_role_settings(draft_session.discipline)),
            normalize_config_payload(await loaders.role_overrides(session, draft_session)),
        )
        return {
            role.code: config.role_settings[role.code].impact if role.code in config.role_settings else 1.0
            for role in DISCIPLINES[draft_session.discipline].rated_dimension.roles
        }

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

    async def load_read_snapshot(self, session: AsyncSession, draft_session: DraftSession) -> DraftSnapshot:
        """``load_snapshot`` shared by every read of the same board state in this process.

        Fit and the pick queue are asked per team, and every captain and admin
        re-asks on every draft event, so the players, picks and rosters are one
        answer for all of them, keyed like the board. Teams are re-read per call
        because a captain's private ``pick_queue`` changes without an event.

        READ PATHS ONLY. The rows are detached from the session that loaded them
        and shared by concurrent readers: nothing may mutate them, and a write
        that resolves after mutating must see its own change, which a shared
        snapshot of the prior state would hide.
        """
        state = await self._read_state(session, draft_session)
        teams = await self.teams_repo.list_by_session(session, draft_session.id)
        return dataclasses.replace(state.snapshot, teams=tuple(teams))

    async def board_snapshot(
        self, session: AsyncSession, draft_session: DraftSession, last_event_id: int | None, *, max_age: float
    ) -> DraftSnapshot:
        """The read snapshot of the state at ``last_event_id`` for the public board.

        Shared with that state's fit and queue reads, so a board built first warms them and a board built after them
        loads nothing; reloaded once older than ``max_age``, so the board keeps its own staleness bound. READ PATHS
        ONLY, like ``load_read_snapshot``.
        """
        return (await self._state_at(session, draft_session, last_event_id, max_age=max_age)).snapshot

    async def _read_state(self, session: AsyncSession, draft_session: DraftSession) -> _ReadState:
        return await self._state_at(session, draft_session, await draft_rt.last_event_id(session, draft_session.id))

    async def _state_at(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        event_id: int | None,
        *,
        max_age: float = _READ_SNAPSHOT_TTL_SECONDS,
    ) -> _ReadState:
        key = f"{draft_session.id}:{draft_session.version}:{event_id or 0}"
        now = time.monotonic()
        for stale in [k for k, state in _read_snapshots.items() if now - state.at > _READ_SNAPSHOT_TTL_SECONDS]:
            del _read_snapshots[stale]
        state = _read_snapshots.get(key)
        if state is None or now - state.at > max_age:
            snapshot = await single_flight(f"snapshot:{key}", lambda: self.load_snapshot(session, draft_session))
            state = _read_snapshots.get(key)
            # The flight's first caller stores it, its joiners share that state; a reload replaces the older one.
            if state is None or state.snapshot is not snapshot:
                state = _read_snapshots[key] = _ReadState(now, key, snapshot)
        return state

    async def read_context(
        self, session: AsyncSession, draft_session: DraftSession
    ) -> tuple[RosterShape, dict[str, float]]:
        """``resolve_shape`` and ``resolve_role_impact`` shared by the read paths of one session in this process.

        READ PATHS ONLY, like ``load_read_snapshot``: a write resolves both live.
        """
        key = (draft_session.id, draft_session.version)
        now = time.monotonic()
        for stale in [k for k, (at, *_) in _read_contexts.items() if now - at > _READ_SNAPSHOT_TTL_SECONDS]:
            del _read_contexts[stale]
        entry = _read_contexts.get(key)
        if entry is None:

            async def load() -> tuple[float, RosterShape, dict[str, float]]:
                return (
                    now,
                    await self.resolve_shape(session, draft_session),
                    await self.resolve_role_impact(session, draft_session),
                )

            entry = _read_contexts.setdefault(key, await single_flight(f"context:{key}", load))
        return entry[1], entry[2]

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
        # Forced-pick matchings only for the unsafe options (see
        # evaluate_pick_options) — pure CPU, run them off the event loop.
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
        return await self.read_pick_options(session, draft_session, team_id=pick.draft_team_id)

    async def read_pick_options(
        self, session: AsyncSession, draft_session: DraftSession, *, team_id: int
    ) -> tuple[DraftPickOption, ...]:
        """``evaluate_session_pick_options`` once per board state and team, off the shared read snapshot.

        READ PATHS ONLY, like ``load_read_snapshot``: a pick validates against a snapshot of its own.
        """
        state = await self._read_state(session, draft_session)
        options = state.pick_options.get(team_id)
        if options is None:
            shape, _ = await self.read_context(session, draft_session)
            snapshot = state.snapshot
            matching = build_feasibility_state(
                shape=shape,
                teams=snapshot.teams,
                players=snapshot.players,
                picks=snapshot.picks,
                rosters=snapshot.rosters,
            )
            options = await single_flight(
                f"options:{state.key}:{team_id}",
                lambda: self.evaluate_session_pick_options(session, draft_session, team_id=team_id, state=matching),
            )
            state.pick_options[team_id] = options
        return options

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
        available = [p for p in snapshot.players if p.status == DraftPlayerStatus.AVAILABLE.value]
        shape = await self.resolve_shape(session, draft_session)
        counts = rules.team_slot_counts(
            snapshot.players, snapshot.picks, current.draft_team_id, shape, snapshot.rosters
        )
        impact = await self.resolve_role_impact(session, draft_session)
        capacity = rules.role_openings(shape, counts, impact)
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
            rules.team_fit_config(shape, counts, impact),
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
        # Fit reads no team row, so it skips the per-call teams re-read the queue needs.
        state = await self._read_state(session, draft_session)
        snapshot = state.snapshot
        shape, impact = await self.read_context(session, draft_session)
        counts = rules.team_slot_counts(snapshot.players, snapshot.picks, team_id, shape, snapshot.rosters)
        capacity = rules.role_openings(shape, counts, impact)
        if not any(opening > 0 for opening in capacity.values()):
            return []  # this team's roster is full
        if state.fit_players is None:
            available = [p for p in snapshot.players if p.status == DraftPlayerStatus.AVAILABLE.value]
            state.fit_players = sug.fit_players(available, snapshot.rosters)
        players = state.fit_players
        results = sug.candidates(
            players,
            capacity,
            rules.team_fit_config(shape, counts, impact),
            DraftAutopickStrategy(draft_session.autopick_strategy),
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
