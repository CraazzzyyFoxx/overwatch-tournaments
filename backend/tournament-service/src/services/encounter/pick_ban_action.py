"""The live pick-ban runtime: the cursor, the two ways a side answers a step
(``act`` for an open step, ``submit`` for a blind one), the write-side healing
that keeps the room in step with its own rules, and the state payload the room
renders.

Submissions are the source of truth (design D2/D3): every mutation writes a
``PickBanSubmission`` and then RE-PROJECTS ``PickBanEntry`` from the whole log,
so the board can never drift from the actions behind it and a reopened step
(dispute / admin) simply replaces its rows. The cursor is derived the same way
-- there is no step counter column to get out of step with the entries.

``_settle`` resolves ``system`` steps, expires a step whose timer ran out under
its ``on_timeout`` policy, reveals a blind step once every side has locked, and
restarts the clock whenever the current step changes. It runs before every
mutation and inside ``reconcile_room``, under the session lock.

``get_pick_ban_state`` is a PURE READ -- no row lock, no write, no commit, no
signal. Healing it would otherwise do lives in :meth:`PickBanActionService.
reconcile_room`, driven by ``room_reconcile``: a post-commit trigger after
every room write plus two scheduled sweeps. A viewer's poll taking the
encounter's row lock put every spectator behind the captains and behind each
other, which is what this split exists to prevent.

Design: docs/plans/2026-09-28-pick-ban-constructor.md §5, §7, §9.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import EncounterGameState, EncounterStatus, MapVetoSessionStatus, PickBanKind
from shared.core.errors import BaseAPIException as HTTPException
from shared.division_grid import DivisionGrid
from shared.domain import pick_ban_engine as engine
from shared.domain import pick_ban_rules as pbr
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.encounter_report import EncounterMapReport
from shared.models.tournament.pick_ban import PickBanEntry, PickBanSession, PickBanSubmission
from shared.models.tournament.team import Player
from shared.repository import (
    EncounterRepository,
    PickBanEntryRepository,
    PickBanSubmissionRepository,
)
from shared.services.bracket.usability import is_encounter_live
from shared.services.division_grid.resolution import resolve_tournament_division
from src.core.workspace import get_division_grid
from src.services.encounter import pick_ban_undo
from src.services.encounter.games import EncounterGameService, encounter_game_service
from src.services.encounter.pick_ban_session import (
    PickBanSessionService,
    assert_not_paused,
    load_item_groups,
    pick_ban_session_service,
    resolved_steps,
    step_clock,
)
from src.services.encounter.realtime_commit import emit_pick_ban_update
from src.services.encounter.room_journal import record_room_event

#: ``viewer_side`` default meaning "the side that is acting". A plain ``None``
#: default could not tell an admin acting FOR a side (who must get the neutral,
#: privacy-free view) from the captain acting as themselves.
ACTING_VIEWER = "__acting__"

GameSnapshot = tuple[list[EncounterGame], dict[int, list[EncounterMapReport]]]


def _source_of(viewer_side: str | None) -> str:
    """Who is writing, for the journal: the same read of ``viewer_side`` the
    captain-only guards run on, so the two can never disagree."""
    return "captain" if viewer_side == ACTING_VIEWER else "admin"


_CAPTAIN_ACTIONS = ("ban", "pick", "protect")
#: Roster reading order of a target board: the three roles in team order, mains
#: before the substitutes that cover them, then by name.
_ROLE_ORDER = {"tank": 0, "damage": 1, "support": 2}


# ── serialization ────────────────────────────────────────────────────────────


def serialize_pick_ban_entry(entry: PickBanEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "item_id": entry.item_id,
        "round": entry.round,
        "order": entry.order,
        "action_index": entry.action_index,
        "picked_by": entry.picked_by,
        "protected_by": entry.protected_by,
        "status": entry.status,
        "team_id": entry.team_id,
        # Set only on a ban carried in from an earlier round, which the room
        # badges with its origin map and nothing may act on.
        "carried_from_round": entry.carried_from_round,
    }


def serialize_pick_ban_session(pick_ban: PickBanSession) -> dict[str, Any]:
    return {
        "id": pick_ban.id,
        "kind": pick_ban.kind,
        "status": pick_ban.status,
        "first_side": pick_ban.first_side,
        "awaiting_choice": pick_ban.awaiting_choice,
        "pending_loser_side": pick_ban.pending_loser_side,
        "seed_source": pick_ban.seed_source,
        "home_seed": pick_ban.home_seed,
        "away_seed": pick_ban.away_seed,
        # Passthrough of the session's reserve snapshot, string-keyed by slot
        # position, gaps and reserve-less slots omitted -- see
        # pick_ban_session.ensure_pick_ban_session's slot_reserves comment.
        # Always None for kind=hero (no reserve concept there).
        "slot_reserves": pick_ban.slot_reserves_json,
        "started_at": pick_ban.started_at.isoformat() if pick_ban.started_at else None,
        "current_step_started_at": (
            pick_ban.current_step_started_at.isoformat() if pick_ban.current_step_started_at else None
        ),
        # Set = the room is frozen by an organizer: no clock, no captain write.
        "paused_at": pick_ban.paused_at.isoformat() if pick_ban.paused_at else None,
    }


def serialize_submission(row: pbr.SubmissionLike) -> dict[str, Any]:
    return {
        "step_index": row.step_index,
        "side": row.side,
        "attempt": row.attempt,
        "state": row.state,
        "items": [
            {"item_id": int(item["item_id"]), "target_player_id": item.get("target_player_id")}
            for item in (row.items_json or [])
        ],
    }


def serialize_target(player: Player, grid: DivisionGrid) -> dict[str, Any]:
    role = getattr(player.role, "value", player.role)
    return {
        "player_id": player.id,
        "name": player.name,
        # The TS contract spells roles lowercase; `HeroClass` already does, but
        # a raw column read can hand back whatever the DB stored.
        "role": role.lower() if isinstance(role, str) else None,
        "sub_role": player.sub_role,
        "is_substitution": bool(player.is_substitution),
        # Against the tournament's own grid, exactly as `PlayerRead.division`.
        "division": resolve_tournament_division(player.rank, tournament_grid=grid),
    }


def _target_sort_key(player: Player) -> tuple[int, int, str]:
    role = getattr(player.role, "value", player.role)
    rank = _ROLE_ORDER.get(role.lower(), len(_ROLE_ORDER)) if isinstance(role, str) else len(_ROLE_ORDER)
    return (rank, 1 if player.is_substitution else 0, player.name or "")


def build_unavailable_state(reason: str, *, readiness: dict[str, bool]) -> dict[str, Any]:
    return {
        "session": None,
        "reason": reason,
        "readiness": readiness,
        "sequence": [],
        "pool": [],
        "submissions": [],
        "viewer_side": None,
        "viewer_can_act": False,
        "allowed_actions": [],
        "current_step_index": None,
        "current_step": None,
        "expected_action": None,
        "acting_sides": [],
        "step_progress": None,
        "step_deadline": None,
        "current_round": None,
        "is_complete": False,
        "eligible": None,
        "draft_issues": [],
        "targets": None,
        "dispute": pbr.DisputeState(False, None, 0, 0).to_json(),
        "games": [],
        "series": None,
        "undo": pick_ban_undo.undo_state(None, [], []),
    }


# ── the loaded room ──────────────────────────────────────────────────────────


@dataclass
class _Runtime:
    """One consistent read of everything the rules need: the session row, its
    resolved steps, its board, its action log, and the lookups the condition
    leaves resolve against."""

    pick_ban: PickBanSession
    encounter: Encounter
    steps: list[pbr.ResolvedStep]
    entries: list[PickBanEntry]
    submissions: list[PickBanSubmission]
    groups: dict[int, str | None] = field(default_factory=dict)
    #: ``{"home": home roster, "away": away roster}`` -- the STATE payload's
    #: orientation. ``RuntimeCtx.targets`` flips it (a side names the OPPONENT).
    rosters: dict[str, list[Player]] = field(default_factory=dict)


class PickBanActionService:
    def __init__(
        self,
        *,
        entry_repo: PickBanEntryRepository = PickBanEntryRepository(),
        submission_repo: PickBanSubmissionRepository = PickBanSubmissionRepository(),
        encounter_repo: EncounterRepository = EncounterRepository(),
        games: EncounterGameService = encounter_game_service,
        sessions: PickBanSessionService = pick_ban_session_service,
    ) -> None:
        self.entry_repo = entry_repo
        self.submission_repo = submission_repo
        self.encounter_repo = encounter_repo
        self.games = games
        self.sessions = sessions

    # -- loading -----------------------------------------------------------
    async def _load(
        self, session: AsyncSession, pick_ban: PickBanSession, encounter: Encounter, *, refresh: bool = False
    ) -> _Runtime:
        """``refresh`` re-reads rows already in the identity map, which every
        load taken AFTER locking the session must do -- the pre-lock snapshot is
        exactly what the lock exists to discard."""
        entries = list(
            await self.entry_repo.list_by_session(session, pick_ban.id, ordered=True, populate_existing=refresh)
        )
        submissions = list(await self.submission_repo.list_by_session(session, pick_ban.id, populate_existing=refresh))
        steps = resolved_steps(pick_ban)
        groups = await load_item_groups(session, PickBanKind(pick_ban.kind), [entry.item_id for entry in entries])
        rosters: dict[str, list[Player]] = {}
        if any(step.target is not None for step in steps):
            rosters = await self._load_rosters(session, encounter)
        return _Runtime(
            pick_ban=pick_ban,
            encounter=encounter,
            steps=steps,
            entries=entries,
            submissions=submissions,
            groups=groups,
            rosters=rosters,
        )

    async def _load_rosters(self, session: AsyncSession, encounter: Encounter) -> dict[str, list[Player]]:
        """Both teams' roster rows, in the room's reading order. One query: a
        target step needs both sides at once (each side bans for the other)."""
        team_ids = [team_id for team_id in (encounter.home_team_id, encounter.away_team_id) if team_id is not None]
        if not team_ids:
            return {"home": [], "away": []}
        rows = (await session.execute(select(Player).where(Player.team_id.in_(team_ids)))).scalars().all()
        return {
            "home": sorted((row for row in rows if row.team_id == encounter.home_team_id), key=_target_sort_key),
            "away": sorted((row for row in rows if row.team_id == encounter.away_team_id), key=_target_sort_key),
        }

    def _ctx(self, rt: _Runtime, step: pbr.ResolvedStep) -> pbr.RuntimeCtx:
        """The rules' view of the room for ONE step. ``available_item_ids`` is
        the step's own round, carried bans excluded (they are already spent);
        ``targets`` is flipped, because a side names the OPPONENT's players."""
        available = tuple(
            entry.item_id
            for entry in rt.entries
            if entry.carried_from_round is None and entry.round == step.round and str(entry.status) == pbr.AVAILABLE
        )
        targets: dict[str, list[pbr.TargetPlayer]] = {}
        if step.target is not None and rt.rosters:
            for side, opponent in (("home", "away"), ("away", "home")):
                targets[side] = [
                    pbr.TargetPlayer(
                        player_id=player.id,
                        role=(
                            role.lower()
                            if isinstance(role := getattr(player.role, "value", player.role), str)
                            else None
                        ),
                    )
                    for player in rt.rosters.get(opponent, [])
                ]
        return pbr.RuntimeCtx(
            kind=str(rt.pick_ban.kind),
            round=step.round,
            best_of=rt.encounter.best_of,
            available_item_ids=available,
            groups=rt.groups,
            history=pbr.history_of(rt.steps, rt.submissions),
            targets=targets,
        )

    # -- settling ----------------------------------------------------------
    @staticmethod
    def step_deadline(pick_ban: PickBanSession, step: pbr.ResolvedStep) -> datetime | None:
        """When the open step runs out, or ``None`` when it is untimed. Public:
        the pre-game rooms overview flags an overdue room with it, and a second
        copy of "started_at + timer, naive rows are UTC" would drift.

        A PAUSED session is untimed by the same answer: this one ``None`` is what
        stops the expiry, the room's countdown and the overview's ``overdue`` flag
        together, so there is no second place that has to remember the pause.
        """
        if step.timer_seconds is None or pick_ban.current_step_started_at is None or pick_ban.paused_at is not None:
            return None
        started = pick_ban.current_step_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return started + timedelta(seconds=step.timer_seconds)

    def _expired(self, pick_ban: PickBanSession, step: pbr.ResolvedStep) -> bool:
        deadline = self.step_deadline(pick_ban, step)
        return deadline is not None and datetime.now(UTC) >= deadline

    def session_pending(
        self,
        pick_ban: PickBanSession,
        steps: list[pbr.ResolvedStep],
        submissions: list[PickBanSubmission],
    ) -> bool:
        """Whether ``_settle`` would move this session. Cheap and unlocked: the
        decision itself is re-made under the lock, and the overwhelmingly common
        answer is "nothing to do".

        Takes the three rows it actually reads rather than a ``_Runtime`` so the
        due-room scheduler can ask it of hundreds of sessions off two batched
        queries, instead of loading each room's entries, groups and rosters.
        """
        if str(pick_ban.status) == MapVetoSessionStatus.CANCELLED:
            return False
        step = pbr.current_step(steps, submissions)
        if step is None:
            return str(pick_ban.status) != MapVetoSessionStatus.COMPLETED
        if str(pick_ban.status) == MapVetoSessionStatus.COMPLETED:
            return True
        # A ``wait`` step outlives its timer by design: ``_settle`` never expires
        # it, so counting it as due would lock the room on every tick for nothing.
        expired = step.on_timeout != "wait" and self._expired(pick_ban, step)
        return step.is_system or pbr.ready_to_reveal(step, submissions) or expired

    @staticmethod
    def _writable_attempt(rt: _Runtime, step_index: int) -> int:
        """Which attempt a NEW submission for this step belongs to.

        Normally the current one. But an undo voids a step's whole attempt
        without opening the next, so re-answering the reopened step has to move
        on: ``(session, step, side, attempt)`` is unique, and reusing a voided
        attempt's number would collide with the row it voided.
        """
        attempt = pbr.current_attempt(rt.submissions, step_index)
        rows = [row for row in rt.submissions if row.step_index == step_index and row.attempt == attempt]
        return attempt + 1 if rows and all(row.state == pbr.VOIDED for row in rows) else attempt

    def _write(
        self,
        session: AsyncSession,
        rt: _Runtime,
        step: pbr.ResolvedStep,
        side: str,
        items: list[dict[str, Any]],
        *,
        state: str,
    ) -> PickBanSubmission:
        """Create or replace ``side``'s live submission for this step."""
        attempt = self._writable_attempt(rt, step.index)
        row = pbr.side_submission(rt.submissions, step.index, side)
        now = datetime.now(UTC)
        normalized = [
            {"item_id": int(item["item_id"]), "target_player_id": item.get("target_player_id")} for item in items
        ]
        if row is None:
            row = PickBanSubmission(
                session_id=rt.pick_ban.id,
                step_index=step.index,
                side=side,
                attempt=attempt,
                state=state,
                items_json=normalized,
            )
            session.add(row)
            rt.submissions.append(row)
        else:
            row.items_json = normalized
            row.state = state
        if state in (pbr.LOCKED, pbr.REVEALED) and row.locked_at is None:
            row.locked_at = now
        if state == pbr.REVEALED and row.revealed_at is None:
            row.revealed_at = now
        return row

    @staticmethod
    def _reveal(rt: _Runtime, step: pbr.ResolvedStep) -> None:
        now = datetime.now(UTC)
        for side in step.sides:
            row = pbr.side_submission(rt.submissions, step.index, side)
            if row is None or row.state == pbr.REVEALED:
                continue
            row.state = pbr.REVEALED
            if row.locked_at is None:
                row.locked_at = now
            if row.revealed_at is None:
                row.revealed_at = now

    async def _settle(self, session: AsyncSession, rt: _Runtime) -> bool:
        """Advance the room as far as it can go without a captain: resolve
        ``system`` steps, expire the step on the clock, reveal what is fully
        locked. Returns whether anything changed.

        Only the step that was current when this started may EXPIRE: the clock
        belongs to that step, and a step that becomes current here has not been
        on it for a single second.

        A paused room still settles -- system steps, reveals, completion -- so an
        organizer acting during the pause sees the board move. Only the EXPIRY
        stops, and it needs no check here: ``step_deadline`` is ``None`` while
        paused. A step that opens during the pause starts on ``step_clock``.
        """
        if str(rt.pick_ban.status) == MapVetoSessionStatus.CANCELLED:
            return False
        opening = pbr.current_step(rt.steps, rt.submissions)
        timed_index = opening.index if opening is not None else None
        changed = False
        # Each pass settles one step; the +2 covers the terminal no-op pass.
        for _ in range(len(rt.steps) + 2):
            pbr.project_entries(rt.entries, rt.steps, rt.submissions)
            step = pbr.current_step(rt.steps, rt.submissions)
            if step is None:
                break
            if step.is_system:
                items = pbr.resolve_system_step(step, self._ctx(rt, step))
                self._write(session, rt, step, "system", items, state=pbr.REVEALED)
                await record_room_event(
                    session,
                    rt.encounter.id,
                    action="step_auto_resolved",
                    source="system",
                    kind=str(rt.pick_ban.kind),
                    data={
                        "step_index": step.index,
                        "round": step.round,
                        "action": step.action,
                        "item_ids": [int(item["item_id"]) for item in items],
                    },
                )
                changed = True
                continue
            if pbr.ready_to_reveal(step, rt.submissions):
                self._reveal(rt, step)
                await record_room_event(
                    session,
                    rt.encounter.id,
                    action="step_revealed",
                    source="system",
                    kind=str(rt.pick_ban.kind),
                    data={"step_index": step.index, "round": step.round},
                )
                changed = True
                continue
            if step.index == timed_index and step.on_timeout != "wait" and self._expired(rt.pick_ban, step):
                stood_in: list[str] = []
                for side in step.acting_sides:
                    row = pbr.side_submission(rt.submissions, step.index, side)
                    if row is not None and row.state in (pbr.LOCKED, pbr.REVEALED):
                        continue
                    items = list(row.items_json or []) if row is not None else []
                    if step.on_timeout == "random_fill":
                        items = pbr.random_fill(step, side, items, self._ctx(rt, step))
                    # Force-lock ignores `min`: standing in for a captain who
                    # never answered must not be blocked by what they owed.
                    self._write(session, rt, step, side, items, state=pbr.LOCKED)
                    pbr.project_entries(rt.entries, rt.steps, rt.submissions)
                    stood_in.append(side)
                await record_room_event(
                    session,
                    rt.encounter.id,
                    action="step_timed_out",
                    source="system",
                    kind=str(rt.pick_ban.kind),
                    # ``sides`` is who the clock answered FOR, not who the step
                    # belonged to: a side that locked in time was not timed out.
                    data={
                        "step_index": step.index,
                        "round": step.round,
                        "policy": step.on_timeout,
                        "sides": stood_in,
                    },
                )
                changed = True
                continue
            break

        pbr.project_entries(rt.entries, rt.steps, rt.submissions)
        closing = pbr.current_step(rt.steps, rt.submissions)
        if (closing.index if closing is not None else None) != timed_index:
            rt.pick_ban.current_step_started_at = step_clock(rt.pick_ban)
        if closing is None:
            if str(rt.pick_ban.status) == MapVetoSessionStatus.ACTIVE:
                rt.pick_ban.status = MapVetoSessionStatus.COMPLETED
                await record_room_event(
                    session,
                    rt.encounter.id,
                    action="session_completed",
                    source="system",
                    kind=str(rt.pick_ban.kind),
                )
                changed = True
        elif str(rt.pick_ban.status) == MapVetoSessionStatus.COMPLETED:
            rt.pick_ban.status = MapVetoSessionStatus.ACTIVE
            changed = True
        return changed

    # -- committing --------------------------------------------------------
    async def _commit(self, session: AsyncSession, rt: _Runtime, kind: PickBanKind) -> None:
        """Settle whatever this mutation unlocked, re-project, keep the series'
        games in step with the picks, and publish."""
        await self._settle(session, rt)
        await session.flush()
        if kind == PickBanKind.MAP:
            await self.games.sync_games_with_picks(session, rt.encounter, rt.pick_ban)
        await emit_pick_ban_update(session, rt.encounter.id, kind=kind.value)
        await session.commit()

    async def _blocked_rounds(self, session: AsyncSession, encounter: Encounter) -> frozenset[int]:
        """Series positions that already carry a claim or an accepted result --
        the rounds a dispute may no longer reopen, whichever kind asks."""
        games = await self.games.list_games(session, encounter.id)
        reports = await self.games.reports_by_game(session, games)
        return frozenset(
            game.position for game in games if game.state == EncounterGameState.CONFIRMED or reports.get(game.id)
        )

    # -- reopening ---------------------------------------------------------
    def _reopen(self, session: AsyncSession, rt: _Runtime, step: pbr.ResolvedStep) -> None:
        """Void the step's current attempt and open the next one, each captain's
        draft prefilled with what they had. The clock restarts; a session that
        had run out of sequence comes back to life."""
        attempt = pbr.current_attempt(rt.submissions, step.index)
        previous: dict[str, list[dict[str, Any]]] = {}
        for row in rt.submissions:
            if row.step_index != step.index or row.attempt != attempt or row.state == pbr.VOIDED:
                continue
            previous[row.side] = [dict(item) for item in (row.items_json or [])]
            row.state = pbr.VOIDED
        for side in step.acting_sides:
            row = PickBanSubmission(
                session_id=rt.pick_ban.id,
                step_index=step.index,
                side=side,
                attempt=attempt + 1,
                state=pbr.DRAFT,
                items_json=previous.get(side, []),
            )
            session.add(row)
            rt.submissions.append(row)
        pbr.project_entries(rt.entries, rt.steps, rt.submissions)
        rt.pick_ban.current_step_started_at = step_clock(rt.pick_ban)
        if str(rt.pick_ban.status) == MapVetoSessionStatus.COMPLETED:
            rt.pick_ban.status = MapVetoSessionStatus.ACTIVE
        pick_ban_undo.clear_undo_request(rt.pick_ban)

    @staticmethod
    def _reopenable(rt: _Runtime) -> pbr.ResolvedStep | None:
        """The latest fully revealed step, provided nothing was submitted after
        it -- reopening a step whose successor has already been answered would
        invalidate that answer."""
        touched = [
            step
            for step in rt.steps
            if any(pbr.side_submission(rt.submissions, step.index, side) is not None for side in step.sides)
        ]
        if not touched:
            return None
        latest = touched[-1]
        for side in latest.sides:
            row = pbr.side_submission(rt.submissions, latest.index, side)
            if row is None or row.state != pbr.REVEALED:
                return None
        return latest

    # -- locking -----------------------------------------------------------
    async def _lock(
        self, session: AsyncSession, encounter_id: int, kind: PickBanKind, *, captain: bool = True
    ) -> tuple[Encounter, PickBanSession]:
        """The lock comes FIRST, before anything a decision reads: the cursor is
        derived from the submission log and written back to it, so two
        overlapping requests must not both resolve the same step (see
        ``pick_ban_session.get_pick_ban_session``).

        ``captain=False`` is the organizer override: a pause stops the CAPTAINS,
        and the staff member who paused the room is exactly who still has to be
        able to fix what they paused it for.
        """
        # Admin actions bypass the captain RPC loader. Keep every mutation in
        # encounter -> session order, including the room journal's FK writes.
        encounter = await self.sessions._lock_encounter(session, encounter_id)
        pick_ban = await self.sessions.get_pick_ban_session(session, encounter_id, kind, for_update=True)
        if pick_ban is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick-ban session is not initialized")
        if str(pick_ban.status) == MapVetoSessionStatus.CANCELLED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick-ban session is cancelled")
        if captain:
            assert_not_paused(pick_ban)
        return encounter, pick_ban

    @staticmethod
    def _require_step(rt: _Runtime) -> pbr.ResolvedStep:
        step = pbr.current_step(rt.steps, rt.submissions)
        if step is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick-ban sequence is already complete")
        return step

    @staticmethod
    def _require_turn(rt: _Runtime, step: pbr.ResolvedStep, side: str) -> None:
        if side not in step.acting_sides:
            whose = " and ".join(step.acting_sides) or "nobody"
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"It's {whose} team's turn, not {side}")
        row = pbr.side_submission(rt.submissions, step.index, side)
        if row is not None and row.state in (pbr.LOCKED, pbr.REVEALED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Your answer to this step is already locked"
            )

    # -- public API --------------------------------------------------------
    async def perform_pick_ban_action(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        side: str,
        *,
        item_id: int,
        action: str,
        target_player_id: int | None = None,
        viewer_side: str | None = ACTING_VIEWER,
        actor_auth_user_id: int | None = None,
    ) -> dict[str, Any]:
        """One item onto an OPEN step's submission. A blind step is answered
        with :meth:`submit_items` instead -- appending one item at a time to a
        draft nobody may see would leak its size through the progress counter."""
        # ``viewer_side`` is the admin discriminator this module already runs on
        # (see ACTING_VIEWER): an organizer acting FOR a side passes it as None.
        encounter, pick_ban = await self._lock(session, encounter_id, kind, captain=viewer_side == ACTING_VIEWER)
        rt = await self._load(session, pick_ban, encounter, refresh=True)
        await self._settle(session, rt)
        step = self._require_step(rt)
        if step.blind:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This step is blind -- submit the whole draft instead",
            )
        if action != step.action:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Expected action '{step.action}', got '{action}'"
            )
        self._require_turn(rt, step, side)

        row = pbr.side_submission(rt.submissions, step.index, side)
        items = [dict(item) for item in (row.items_json or [])] if row is not None else []
        items.append({"item_id": item_id, "target_player_id": target_player_id})
        issues = pbr.validate_items(step, side, items, self._ctx(rt, step), final=False)
        if issues:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=", ".join(issues))

        self._write(session, rt, step, side, items, state=pbr.LOCKED if len(items) >= step.count else pbr.DRAFT)
        await record_room_event(
            session,
            encounter_id,
            action="acted",
            # Derived from the SAME discriminator the lock above runs on, never a
            # second flag: a journal that can disagree with who was allowed to
            # act is worse than no journal.
            source=_source_of(viewer_side),
            kind=kind.value,
            side=side,
            actor_auth_user_id=actor_auth_user_id,
            data={
                "step_index": step.index,
                "round": step.round,
                "action": action,
                "item_id": item_id,
                "target_player_id": target_player_id,
            },
        )
        # Any open undo consent was given against the action that WAS last; this
        # one supersedes it, so the agreement dies with the state it was read on.
        pick_ban_undo.clear_undo_request(pick_ban)
        await self._commit(session, rt, kind)
        return await self.get_pick_ban_state(
            session, encounter_id, kind, viewer_side=side if viewer_side == ACTING_VIEWER else viewer_side
        )

    async def submit_items(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        side: str,
        *,
        items: list[dict[str, Any]],
        lock: bool,
        viewer_side: str | None = ACTING_VIEWER,
        actor_auth_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Replace a BLIND step's draft, optionally locking it. A locked draft
        is final: the step reveals the moment every acting side has one."""
        encounter, pick_ban = await self._lock(session, encounter_id, kind, captain=viewer_side == ACTING_VIEWER)
        rt = await self._load(session, pick_ban, encounter, refresh=True)
        await self._settle(session, rt)
        step = self._require_step(rt)
        if not step.blind:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This step is open -- take it one item at a time",
            )
        self._require_turn(rt, step, side)

        draft = [{"item_id": int(item["item_id"]), "target_player_id": item.get("target_player_id")} for item in items]
        issues = pbr.validate_items(step, side, draft, self._ctx(rt, step), final=lock)
        if issues:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=", ".join(issues))

        self._write(session, rt, step, side, draft, state=pbr.LOCKED if lock else pbr.DRAFT)
        source = _source_of(viewer_side)
        # A captain's unlocked draft is an autosave -- it changes nothing anyone
        # else can see, and journalling every keystroke would bury the room's
        # story. An organizer's is a deliberate write on someone else's behalf.
        if lock or source == "admin":
            await record_room_event(
                session,
                encounter_id,
                action="draft_locked" if lock else "draft_set",
                source=source,
                kind=kind.value,
                side=side,
                actor_auth_user_id=actor_auth_user_id,
                data={"step_index": step.index, "round": step.round, "items": draft},
            )
        pick_ban_undo.clear_undo_request(pick_ban)
        await self._commit(session, rt, kind)
        return await self.get_pick_ban_state(
            session, encounter_id, kind, viewer_side=side if viewer_side == ACTING_VIEWER else viewer_side
        )

    async def dispute_step(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        side: str,
        *,
        actor_auth_user_id: int | None = None,
    ) -> dict[str, Any]:
        """A captain unilaterally reopens the blind step that just revealed --
        the answer to "they banned for the wrong player" that does not need the
        opponent's agreement, because the step is replayed by BOTH sides."""
        encounter, pick_ban = await self._lock(session, encounter_id, kind)
        rt = await self._load(session, pick_ban, encounter, refresh=True)
        await self._settle(session, rt)
        state = pbr.dispute_target(
            rt.steps,
            rt.submissions,
            side=side,
            blocked_rounds=await self._blocked_rounds(session, encounter),
        )
        if not state.available or state.step_index is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This step cannot be reopened",
            )
        step = next(candidate for candidate in rt.steps if candidate.index == state.step_index)
        attempt = pbr.current_attempt(rt.submissions, step.index)
        self._reopen(session, rt, step)
        await record_room_event(
            session,
            encounter_id,
            action="step_disputed",
            source="captain",
            kind=kind.value,
            side=side,
            actor_auth_user_id=actor_auth_user_id,
            # The attempt being thrown away, not the fresh one `_reopen` opened:
            # "they disputed attempt 1" is what the dispute limit counts.
            data={"step_index": step.index, "attempt": attempt},
        )
        await self._commit(session, rt, kind)
        return await self.get_pick_ban_state(session, encounter_id, kind, viewer_side=side)

    async def admin_reopen_step(
        self, session: AsyncSession, encounter_id: int, kind: PickBanKind, *, actor_auth_user_id: int | None = None
    ) -> dict[str, Any]:
        """The organizer's version of a dispute: the same replay, without the
        per-step attempt limit and without needing the step to allow disputes at
        all (design §5) -- the escape hatch for a room that revealed something
        wrong under a rule nobody anticipated."""
        encounter, pick_ban = await self._lock(session, encounter_id, kind, captain=False)
        rt = await self._load(session, pick_ban, encounter, refresh=True)
        await self._settle(session, rt)
        step = self._reopenable(rt)
        if step is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="There is no settled step to reopen",
            )
        self._reopen(session, rt, step)
        await record_room_event(
            session,
            encounter_id,
            action="step_reopened",
            source="admin",
            kind=kind.value,
            actor_auth_user_id=actor_auth_user_id,
            data={"step_index": step.index},
        )
        await self._commit(session, rt, kind)
        return await self.get_pick_ban_state(session, encounter_id, kind, viewer_side=None)

    # -- the room's state --------------------------------------------------
    async def _game_snapshot(
        self, session: AsyncSession, encounter: Encounter, *, refresh: bool = False
    ) -> GameSnapshot:
        if refresh:
            # The pre-lock identity-map rows are not a mutation snapshot.
            result = await session.execute(
                self.games.game_repo.select()
                .where(
                    EncounterGame.encounter_id == encounter.id,
                    EncounterGame.state != EncounterGameState.CANCELLED,
                )
                .order_by(EncounterGame.position, EncounterGame.id)
                .execution_options(populate_existing=True)
            )
            games = list(result.scalars().all())
        else:
            games = await self.games.list_games(session, encounter.id)
        return games, await self.games.reports_by_game(session, games)

    async def freeplay_owed(self, session: AsyncSession, encounter: Encounter) -> bool:
        """Whether the series owes freeplay its next position.

        Freeplay offers ONE position at a time, only for a playable room, and
        only while no map session owns the positions instead.
        """
        map_session = await self.sessions.get_pick_ban_session(session, encounter.id, PickBanKind.MAP)
        if map_session is not None and str(map_session.status) != MapVetoSessionStatus.CANCELLED:
            return False
        games = await self.games.list_games(session, encounter.id)
        return (
            encounter.home_team_id is not None
            and encounter.away_team_id is not None
            and len(games) < encounter.best_of
            and not engine.series_complete(self.games.live_score(games), encounter.best_of)
            and not any(
                game.state
                in (
                    EncounterGameState.PLANNED,
                    EncounterGameState.AWAITING_RESULT,
                    EncounterGameState.DISPUTED,
                )
                for game in games
            )
            and await is_encounter_live(session, encounter)
        )

    # -- the write-side healer ---------------------------------------------
    async def room_owes_write(self, session: AsyncSession, encounter: Encounter) -> bool:
        """Whether anything about this room is out of step with its own rules.

        Entirely UNLOCKED, and ordered cheapest-first so a steady room -- the
        overwhelmingly common case on both scheduled sweeps -- answers ``False``
        without ever reaching for a row lock. Every branch mirrors exactly what
        :meth:`reconcile_room` would then do; one that did not would make the
        healer take the encounter lock on every tick and change nothing.
        """
        for kind in (PickBanKind.MAP, PickBanKind.HERO):
            pick_ban = await self.sessions.get_pick_ban_session(session, encounter.id, kind)
            if pick_ban is None:
                if await self.sessions.creation_plan(session, encounter, kind) is not None:
                    return True
                continue
            if str(pick_ban.status) == MapVetoSessionStatus.CANCELLED:
                continue
            rt_steps = resolved_steps(pick_ban)
            submissions = list(await self.submission_repo.list_by_session(session, pick_ban.id))
            if self.session_pending(pick_ban, rt_steps, submissions):
                return True
            if kind == PickBanKind.MAP:
                entries = list(await self.entry_repo.list_by_session(session, pick_ban.id, ordered=True))
                games, reports = await self._game_snapshot(session, encounter)
                changes, stale = self.games._pick_game_changes(entries, games, reports)
                if changes or stale:
                    return True
        if await self.sessions.hero_round_owed(session, encounter):
            return True
        return await self.freeplay_owed(session, encounter)

    async def reconcile_room(self, session: AsyncSession, encounter_id: int, *, skip_locked: bool) -> bool:
        """Apply every heal this room owes, under the encounter lock, and publish
        what changed. Returns whether anything did.

        This is the ONLY place the room heals itself. The state read is pure
        (design: a viewer's poll must never queue behind a captain's write), so
        every "a map just got picked", "the clock ran out", "the series owes a
        position" catches up here -- after every room write (``room_reconcile``'s
        post-commit trigger) and on its two scheduled sweeps.

        ``skip_locked`` is for those sweeps: both tournament-service replicas run
        them, and a room another writer already holds needs no second healer.

        Lock order is the room's everywhere: encounter, then session.
        """
        encounter = await self.encounter_repo.get(session, encounter_id)
        # A finished match's room is history: a session abandoned mid-veto must
        # not be random-filled to completion (and grow games) months later.
        if encounter is None or encounter.status == EncounterStatus.COMPLETED:
            return False
        if not await self.room_owes_write(session, encounter):
            return False
        locked_encounter = (
            await self.sessions.try_lock_encounter(session, encounter_id)
            if skip_locked
            else await self.sessions._lock_encounter(session, encounter_id)
        )
        if locked_encounter is None:
            return False
        encounter = locked_encounter

        changed: set[str] = set()
        map_session = await self._reconcile_map(session, encounter, changed)
        if map_session is None or str(map_session.status) == MapVetoSessionStatus.CANCELLED:
            # Only once the map room is known not to own the positions: a
            # concurrent bootstrap may have opened it while this healer waited.
            if await self.freeplay_owed(session, encounter):
                try:
                    async with session.begin_nested():
                        await self.games.ensure_freeplay_game(session, encounter)
                    changed.add(PickBanKind.MAP.value)
                except IntegrityError:
                    # Another writer opened the same position first; its row is
                    # the one the room reports against.
                    pass
        await self._reconcile_hero(session, encounter, changed)
        if not changed:
            # Nothing to keep -- and nothing to go on holding the encounter for.
            # A sweep walks hundreds of rooms on one session; a lock left open
            # here would be held for the rest of it.
            await session.rollback()
            return False
        await session.flush()
        for kind_value in sorted(changed):
            await emit_pick_ban_update(session, encounter.id, kind=kind_value)
        await session.commit()
        return True

    async def _reconcile_map(
        self, session: AsyncSession, encounter: Encounter, changed: set[str]
    ) -> PickBanSession | None:
        """Open the map room if it is owed, settle it, and keep the series' games
        in step with its picks. Returns the map session, if any."""
        existed = await self.sessions.get_pick_ban_session(session, encounter.id, PickBanKind.MAP) is not None
        map_session = await self.sessions._ensure_pick_ban_session(
            session, encounter, PickBanKind.MAP, commit=False, encounter_locked=True
        )
        if map_session is None:
            return None
        if not existed:
            changed.add(PickBanKind.MAP.value)
        if str(map_session.status) == MapVetoSessionStatus.CANCELLED:
            return map_session
        locked = await self.sessions.get_pick_ban_session(session, encounter.id, PickBanKind.MAP, for_update=True)
        if locked is None:
            return None  # a concurrent reset dropped it
        rt = await self._load(session, locked, encounter, refresh=True)
        if await self._settle(session, rt):
            changed.add(PickBanKind.MAP.value)
        await session.flush()
        games, reports = await self._game_snapshot(session, encounter, refresh=True)
        plan, stale = self.games._pick_game_changes(rt.entries, games, reports)
        if plan or stale:
            await self.games._sync_games_with_snapshot(session, encounter, rt.entries, games, reports)
            changed.add(PickBanKind.MAP.value)
        return locked

    async def _reconcile_hero(self, session: AsyncSession, encounter: Encounter, changed: set[str]) -> None:
        """Open the hero room if it is owed, grow its rounds with the series, and
        settle it."""
        existed = await self.sessions.get_pick_ban_session(session, encounter.id, PickBanKind.HERO) is not None
        hero = await self.sessions._ensure_pick_ban_session(
            session, encounter, PickBanKind.HERO, commit=False, encounter_locked=True
        )
        if hero is None:
            return
        if not existed:
            changed.add(PickBanKind.HERO.value)
        if await self.sessions._sync_hero_rounds(session, encounter, commit=False, encounter_locked=True):
            changed.add(PickBanKind.HERO.value)
        locked = await self.sessions.get_pick_ban_session(session, encounter.id, PickBanKind.HERO, for_update=True)
        if locked is None or str(locked.status) == MapVetoSessionStatus.CANCELLED:
            return
        rt = await self._load(session, locked, encounter, refresh=True)
        if await self._settle(session, rt):
            changed.add(PickBanKind.HERO.value)

    async def get_pick_ban_state(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        *,
        viewer_side: str | None = None,
    ) -> dict[str, Any]:
        """The room as it stands RIGHT NOW. A pure read: no lock, no write, no
        commit, no signal.

        It used to heal the room it was about to render, which put every viewer's
        poll behind the encounter's row lock -- and so behind the captains and
        behind each other. Whatever this read finds un-healed is owed to
        :meth:`reconcile_room`, which runs after every room write and on a one-
        second sweep, and which signals the room when it lands.
        """
        encounter = await self.encounter_repo.get(session, encounter_id)
        if encounter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

        readiness = await self.sessions.get_readiness(session, encounter_id)
        pick_ban = await self.sessions.get_pick_ban_session(session, encounter_id, kind)
        if pick_ban is None:
            # Names WHY rather than 400-ing the room: see
            # pick_ban_session.unavailable_reason. A room whose gates have all
            # opened but whose session the reconciler has not created yet reads
            # as `not_ready` for that moment -- the screen the captains are on.
            reason = await self.sessions.unavailable_reason(session, encounter, kind)
            state = build_unavailable_state(reason, readiness=readiness)
            if kind == PickBanKind.MAP:
                games, reports = await self._game_snapshot(session, encounter)
                state["games"] = [self.games.serialize(game, reports.get(game.id, [])) for game in games]
                state["series"] = self.games.serialize_series(encounter, games)
            return state

        rt = await self._load(session, pick_ban, encounter)
        return await self._build_state(session, rt, kind, readiness=readiness, viewer_side=viewer_side)

    async def _build_state(
        self,
        session: AsyncSession,
        rt: _Runtime,
        kind: PickBanKind,
        *,
        readiness: dict[str, bool],
        viewer_side: str | None,
    ) -> dict[str, Any]:
        """Render ``rt``. Pure: the room is rendered as it is, never as it ought
        to be -- drift is :meth:`reconcile_room`'s to fix."""
        games, reports = await self._game_snapshot(session, rt.encounter)
        blocked_rounds = frozenset(
            game.position for game in games if game.state == EncounterGameState.CONFIRMED or reports.get(game.id)
        )
        step = pbr.current_step(rt.steps, rt.submissions)
        acting: list[str] = []
        if step is not None:
            progress = pbr.step_progress(step, rt.submissions)
            acting = [side for side in step.acting_sides if not progress[side]["locked"]]
        viewer_can_act = (
            step is not None
            and viewer_side in acting
            and step.action in _CAPTAIN_ACTIONS
            and str(rt.pick_ban.status) != MapVetoSessionStatus.CANCELLED
            and rt.pick_ban.paused_at is None
        )

        eligible: dict[str, Any] | None = None
        draft_issues: list[str] = []
        if viewer_can_act and step is not None and viewer_side is not None:
            ctx = self._ctx(rt, step)
            eligible = pbr.eligible_items(step, viewer_side, ctx).to_json()
            row = pbr.side_submission(rt.submissions, step.index, viewer_side)
            draft_issues = pbr.validate_items(
                step, viewer_side, list(row.items_json or []) if row is not None else [], ctx, final=True
            )

        targets: dict[str, list[dict[str, Any]]] | None = None
        if any(candidate.target is not None for candidate in rt.steps):
            grid = await get_division_grid(session, None, tournament_id=rt.encounter.tournament_id)
            targets = {
                side: [serialize_target(player, grid) for player in rt.rosters.get(side, [])]
                for side in ("home", "away")
            }

        state: dict[str, Any] = {
            "session": serialize_pick_ban_session(rt.pick_ban),
            "readiness": readiness,
            "sequence": [candidate.to_json() for candidate in rt.steps],
            "pool": [serialize_pick_ban_entry(entry) for entry in rt.entries],
            "submissions": [
                serialize_submission(row) for row in pbr.visible_submissions(rt.steps, rt.submissions, viewer_side)
            ],
            "viewer_side": viewer_side,
            "viewer_can_act": viewer_can_act,
            "allowed_actions": [step.action] if viewer_can_act and step is not None else [],
            "current_step_index": step.index if step is not None else None,
            "current_step": step.to_json() if step is not None else None,
            "expected_action": step.action if step is not None else None,
            "acting_sides": acting,
            "step_progress": pbr.step_progress(step, rt.submissions) if step is not None else None,
            "step_deadline": (
                deadline.isoformat()
                if step is not None and (deadline := self.step_deadline(rt.pick_ban, step)) is not None
                else None
            ),
            "current_round": step.round if step is not None else engine.current_round(rt.entries),
            "is_complete": step is None,
            "eligible": eligible,
            "draft_issues": draft_issues,
            "targets": targets,
            "dispute": pbr.dispute_target(
                rt.steps,
                rt.submissions,
                side=viewer_side,
                blocked_rounds=blocked_rounds,
            ).to_json(),
            "undo": pick_ban_undo.undo_state(rt.pick_ban, rt.steps, rt.submissions),
        }
        if kind == PickBanKind.MAP:
            state["games"] = [self.games.serialize(game, reports.get(game.id, [])) for game in games]
            state["series"] = self.games.serialize_series(rt.encounter, games)
        return state


pick_ban_action_service = PickBanActionService()
