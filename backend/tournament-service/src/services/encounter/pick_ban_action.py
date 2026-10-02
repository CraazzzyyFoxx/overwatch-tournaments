"""The live pick-ban runtime: the cursor, the two ways a side answers a step
(``act`` for an open step, ``submit`` for a blind one), the self-healing the
room's reads perform, and the state payload the room renders.

Submissions are the source of truth (design D2/D3): every mutation writes a
``PickBanSubmission`` and then RE-PROJECTS ``PickBanEntry`` from the whole log,
so the board can never drift from the actions behind it and a reopened step
(dispute / admin) simply replaces its rows. The cursor is derived the same way
-- there is no step counter column to get out of step with the entries.

``_settle`` is the one place the room heals itself: it resolves ``system``
steps, expires a step whose timer ran out under its ``on_timeout`` policy,
reveals a blind step once every side has locked, and restarts the clock
whenever the current step changes. It runs before every mutation and on every
read, under the session lock, exactly as v1's ``auto_resolve_timeout`` /
``auto_complete_decider`` pair did.

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
from shared.core.enums import EncounterGameState, MapVetoSessionStatus, PickBanKind
from shared.core.errors import BaseAPIException as HTTPException
from shared.division_grid import DivisionGrid
from shared.domain import pick_ban_engine as engine
from shared.domain import pick_ban_rules as pbr
from shared.models.tournament.encounter import Encounter
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
    load_item_groups,
    pick_ban_session_service,
    resolved_steps,
)
from src.services.encounter.realtime_commit import emit_pick_ban_update

#: ``viewer_side`` default meaning "the side that is acting". A plain ``None``
#: default could not tell an admin acting FOR a side (who must get the neutral,
#: privacy-free view) from the captain acting as themselves.
ACTING_VIEWER = "__acting__"

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
        copy of "started_at + timer, naive rows are UTC" would drift."""
        if step.timer_seconds is None or pick_ban.current_step_started_at is None:
            return None
        started = pick_ban.current_step_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        return started + timedelta(seconds=step.timer_seconds)

    def _expired(self, pick_ban: PickBanSession, step: pbr.ResolvedStep) -> bool:
        deadline = self.step_deadline(pick_ban, step)
        return deadline is not None and datetime.now(UTC) >= deadline

    def _pending(self, rt: _Runtime) -> bool:
        """Whether a plain READ owes this room a mutation. Cheap and unlocked:
        the decision itself is re-made under the lock, and the overwhelmingly
        common answer on a poll is "nothing to do"."""
        if str(rt.pick_ban.status) == MapVetoSessionStatus.CANCELLED:
            return False
        step = pbr.current_step(rt.steps, rt.submissions)
        if step is None:
            return str(rt.pick_ban.status) != MapVetoSessionStatus.COMPLETED
        if str(rt.pick_ban.status) == MapVetoSessionStatus.COMPLETED:
            return True
        return step.is_system or pbr.ready_to_reveal(step, rt.submissions) or self._expired(rt.pick_ban, step)

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
                self._write(
                    session, rt, step, "system", pbr.resolve_system_step(step, self._ctx(rt, step)), state=pbr.REVEALED
                )
                changed = True
                continue
            if pbr.ready_to_reveal(step, rt.submissions):
                self._reveal(rt, step)
                changed = True
                continue
            if step.index == timed_index and step.on_timeout != "wait" and self._expired(rt.pick_ban, step):
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
                changed = True
                continue
            break

        pbr.project_entries(rt.entries, rt.steps, rt.submissions)
        closing = pbr.current_step(rt.steps, rt.submissions)
        if (closing.index if closing is not None else None) != timed_index:
            rt.pick_ban.current_step_started_at = datetime.now(UTC)
        if closing is None:
            if str(rt.pick_ban.status) == MapVetoSessionStatus.ACTIVE:
                rt.pick_ban.status = MapVetoSessionStatus.COMPLETED
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
        rt.pick_ban.current_step_started_at = datetime.now(UTC)
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
        self, session: AsyncSession, encounter_id: int, kind: PickBanKind
    ) -> tuple[Encounter, PickBanSession]:
        """The lock comes FIRST, before anything a decision reads: the cursor is
        derived from the submission log and written back to it, so two
        overlapping requests must not both resolve the same step (see
        ``pick_ban_session.get_pick_ban_session``)."""
        encounter = await self.encounter_repo.get(session, encounter_id)
        if encounter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")
        pick_ban = await self.sessions.get_pick_ban_session(session, encounter_id, kind, for_update=True)
        if pick_ban is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick-ban session is not initialized")
        if str(pick_ban.status) == MapVetoSessionStatus.CANCELLED:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pick-ban session is cancelled")
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
    ) -> dict[str, Any]:
        """One item onto an OPEN step's submission. A blind step is answered
        with :meth:`submit_items` instead -- appending one item at a time to a
        draft nobody may see would leak its size through the progress counter."""
        encounter, pick_ban = await self._lock(session, encounter_id, kind)
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
    ) -> dict[str, Any]:
        """Replace a BLIND step's draft, optionally locking it. A locked draft
        is final: the step reveals the moment every acting side has one."""
        encounter, pick_ban = await self._lock(session, encounter_id, kind)
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
        pick_ban_undo.clear_undo_request(pick_ban)
        await self._commit(session, rt, kind)
        return await self.get_pick_ban_state(
            session, encounter_id, kind, viewer_side=side if viewer_side == ACTING_VIEWER else viewer_side
        )

    async def dispute_step(
        self, session: AsyncSession, encounter_id: int, kind: PickBanKind, side: str
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
        self._reopen(session, rt, step)
        await self._commit(session, rt, kind)
        return await self.get_pick_ban_state(session, encounter_id, kind, viewer_side=side)

    async def admin_reopen_step(self, session: AsyncSession, encounter_id: int, kind: PickBanKind) -> dict[str, Any]:
        """The organizer's version of a dispute: the same replay, without the
        per-step attempt limit and without needing the step to allow disputes at
        all (design §5) -- the escape hatch for a room that revealed something
        wrong under a rule nobody anticipated."""
        encounter, pick_ban = await self._lock(session, encounter_id, kind)
        rt = await self._load(session, pick_ban, encounter, refresh=True)
        await self._settle(session, rt)
        step = self._reopenable(rt)
        if step is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="There is no settled step to reopen",
            )
        self._reopen(session, rt, step)
        await self._commit(session, rt, kind)
        return await self.get_pick_ban_state(session, encounter_id, kind, viewer_side=None)

    # -- the room's state --------------------------------------------------
    async def _series_state(
        self, session: AsyncSession, encounter: Encounter, pick_ban: PickBanSession | None
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """The series' positions and its live score, as the room renders them.

        With a map session the picks own the positions; without one (freeplay,
        or a room that never opened) exactly one position is offered at a time --
        but only for a room that can actually be played. A preview bracket, or an
        encounter whose slots are still waiting on an upstream result, has no
        series to open: creating its position on a mere READ wrote an
        ``encounter_game`` row for a matchup that may never exist.
        """
        if pick_ban is not None:
            games = await self.games.sync_games_with_picks(session, encounter, pick_ban)
        else:
            if (
                encounter.home_team_id is not None
                and encounter.away_team_id is not None
                and await is_encounter_live(session, encounter)
            ):
                # Committed here: the read RPC never commits, so a position opened
                # only on this session rolled back with it -- the room was handed a
                # game id that did not exist, and naming its map 404'd. Savepoint:
                # two viewers opening the room at once race onto
                # `uq_encounter_game_encounter_position`; the loser reads the
                # winner's row instead of failing the read.
                try:
                    async with session.begin_nested():
                        await self.games.ensure_freeplay_game(session, encounter)
                    await session.commit()
                except IntegrityError:
                    pass
            games = await self.games.list_games(session, encounter.id)
        reports = await self.games.reports_by_game(session, games)
        return (
            [self.games.serialize(game, reports.get(game.id, [])) for game in games],
            self.games.serialize_series(encounter, games),
        )

    async def get_pick_ban_state(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        *,
        viewer_side: str | None = None,
    ) -> dict[str, Any]:
        encounter = await self.encounter_repo.get(session, encounter_id)
        if encounter is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Encounter not found")

        readiness = await self.sessions.get_readiness(session, encounter_id)
        pick_ban = await self.sessions.ensure_pick_ban_session(session, encounter, kind)
        if kind == PickBanKind.HERO and pick_ban is not None:
            # Heroes are banned per map, one round at a time, and nothing pushes
            # "a map just got picked" -- so the hero session catches up with the
            # map phase here, on the read that is about to render it.
            await self.sessions.sync_hero_rounds(session, encounter)
        if pick_ban is None:
            # Names WHY rather than 400-ing the room: see
            # pick_ban_session.unavailable_reason.
            reason = await self.sessions.unavailable_reason(session, encounter, kind)
            state = build_unavailable_state(reason, readiness=readiness)
            if kind == PickBanKind.MAP:
                state["games"], state["series"] = await self._series_state(session, encounter, None)
            return state

        rt = await self._load(session, pick_ban, encounter)
        if self._pending(rt):
            # Double-checked: the unlocked read above only answers "is something
            # owed at all"; the decision is re-made under the lock, where another
            # reader may already have settled it.
            locked = await self.sessions.get_pick_ban_session(session, encounter_id, kind, for_update=True)
            if locked is not None:
                rt = await self._load(session, locked, encounter, refresh=True)
                if await self._settle(session, rt):
                    await session.flush()
                    if kind == PickBanKind.MAP:
                        await self.games.sync_games_with_picks(session, encounter, rt.pick_ban)
                    await emit_pick_ban_update(session, encounter_id, kind=kind.value)
                    await session.commit()
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
                blocked_rounds=await self._blocked_rounds(session, rt.encounter),
            ).to_json(),
            "undo": pick_ban_undo.undo_state(rt.pick_ban, rt.steps, rt.submissions),
        }
        if kind == PickBanKind.MAP:
            state["games"], state["series"] = await self._series_state(session, rt.encounter, rt.pick_ban)
        return state


pick_ban_action_service = PickBanActionService()
