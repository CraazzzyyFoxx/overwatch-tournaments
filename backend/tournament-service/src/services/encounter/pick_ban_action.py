"""The live pick-ban runtime: the cursor, the two ways a participation answers
a step (``act`` for an open step, ``submit`` for a blind one), the write-side
healing that keeps the room in step with its own rules, and the state payload
the room renders.

Submissions are the source of truth: every mutation writes a
``PickBanSubmission`` and then RE-PROJECTS ``PickBanEntry`` from the whole log,
so the board can never drift from the actions behind it and a reopened step
(dispute / admin) simply replaces its rows. The cursor is derived the same way
-- there is no step counter column to get out of step with the entries.

Everything the room names is a PARTICIPATION: who may act, whose draft
is private, who a journal row belongs to. ``encounter_team_id IS NULL`` on a
submission is the engine, and nothing else.

``_settle`` resolves ``system`` steps, expires a step whose timer ran out under
its ``on_timeout`` policy, reveals a blind step once every actor has locked, and
restarts the clock whenever the current step changes. It runs before every
mutation and inside ``reconcile_room``, under the session lock.

``get_pick_ban_state`` is a PURE READ -- no row lock, no write, no commit, no
signal. Healing lives in :meth:`PickBanActionService.reconcile_room`, driven by
``room_reconcile``: a post-commit trigger after every room write plus two
scheduled sweeps. A viewer's poll that took the encounter's row lock would
queue every spectator behind the captains and behind each other.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import EncounterGameState, EncounterStatus, MapVetoSessionStatus, PickBanKind
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import rated_role_codes
from shared.division_grid import DivisionGrid
from shared.domain import pick_ban_engine as engine
from shared.domain import pick_ban_rules as pbr
from shared.models.encounter.encounter import Encounter
from shared.models.encounter.game import EncounterGame, EncounterGameTeam
from shared.models.encounter.pick_ban import PickBanEntry, PickBanSession, PickBanSubmission
from shared.models.encounter.team import EncounterTeam
from shared.models.tournament.team import Player
from shared.repository import (
    EncounterRepository,
    PickBanEntryRepository,
    PickBanSubmissionRepository,
)
from shared.services.division_grid.resolution import resolve_tournament_division
from src.core.workspace import get_division_grid
from src.services.bracket.usability import is_encounter_live
from src.services.encounter import pick_ban_undo
from src.services.encounter.games import OPEN_STATES, EncounterGameService, encounter_game_service
from src.services.encounter.pick_ban_session import (
    MemberSeat,
    PickBanSessionService,
    assert_not_paused,
    load_item_groups,
    load_member_seats,
    members_by_team,
    pick_ban_session_service,
    resolved_steps,
    step_clock,
)
from src.services.encounter.realtime_commit import emit_pick_ban_update
from src.services.encounter.room_journal import record_room_event
from src.services.encounter.veto_session import side_codes

#: ``viewer`` default meaning "the participation that is acting". A plain
#: ``None`` default could not tell an admin acting FOR a participation (who
#: must get the neutral, privacy-free view) from the captain acting as
#: themselves.
ACTING_VIEWER = -1

_encounters = EncounterRepository()

GameSnapshot = tuple[list[EncounterGame], dict[int, list[Any]]]


def _source_of(viewer: int | None) -> str:
    """Who is writing, for the journal: the same read of ``viewer`` the
    captain-only guards run on, so the two can never disagree."""
    return "captain" if viewer == ACTING_VIEWER else "admin"


_CAPTAIN_ACTIONS = ("ban", "pick", "protect", "side_pick", "assign")


def _item(item: Mapping[str, Any]) -> dict[str, Any]:
    """One answered item as the log stores and serves it: ``member_id`` only on an assignment's items."""
    stored = {"item_id": int(item["item_id"]), "target_player_id": item.get("target_player_id")}
    if item.get("member_id") is not None:
        stored["member_id"] = int(item["member_id"])
    return stored


# ── serialization ────────────────────────────────────────────────────────────


def serialize_pick_ban_entry(entry: PickBanEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "item_id": entry.item_id,
        "round": entry.round,
        "order": entry.order,
        "action_index": entry.action_index,
        # The pair the board's CHECK keeps in step: ``team`` names a
        # participation, every other kind is the engine or an organizer.
        "picked_by_kind": entry.picked_by_kind,
        "picked_by_team_id": entry.picked_by_team_id,
        # Whose hero a pick is: a mix member step's member, or whom an assignment gave it to (spec §11.6 R4-11).
        "picked_for_member_id": entry.picked_for_member_id,
        "protected_by_kind": entry.protected_by_kind,
        "protected_by_team_id": entry.protected_by_team_id,
        "status": entry.status,
        # Set only on a ban carried in from an earlier round, which the room
        # badges with its origin map and nothing may act on.
        "carried_from_round": entry.carried_from_round,
    }


def serialize_pick_ban_session(pick_ban: PickBanSession) -> dict[str, Any]:
    return {
        "id": pick_ban.id,
        "kind": pick_ban.kind,
        "status": pick_ban.status,
        #: The participation that opens the round in play.
        "first_team_id": pick_ban.first_team_id,
        "awaiting_choice": pick_ban.awaiting_choice,
        "pending_chooser_team_id": pick_ban.pending_chooser_team_id,
        "seed_source": pick_ban.seed_source,
        # Passthrough of the session's reserve snapshot, string-keyed by slot
        # position, gaps and reserve-less slots omitted -- see
        # pick_ban_session.creation_plan's slot_reserves comment.
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
        "encounter_team_id": row.encounter_team_id,
        #: The member a member step's answer is for; null for a team step.
        "team_member_id": row.team_member_id,
        "attempt": row.attempt,
        "state": row.state,
        "items": [_item(item) for item in (row.items_json or [])],
    }


def serialize_target(player: Player, grid: DivisionGrid) -> dict[str, Any]:
    return {
        "player_id": player.id,
        "name": player.name,
        "role": player.role_ref.model_dump() if player.role_ref is not None else None,
        "is_substitution": bool(player.is_substitution),
        # Against the tournament's own grid, exactly as `PlayerRead.division`.
        "division": resolve_tournament_division(player.rank, tournament_grid=grid),
    }


def build_unavailable_state(reason: str, *, readiness: dict[str, bool]) -> dict[str, Any]:
    return {
        "session": None,
        "reason": reason,
        "readiness": readiness,
        "sequence": [],
        "pool": [],
        "submissions": [],
        "viewer_team_id": None,
        "viewer_can_act": False,
        "allowed_actions": [],
        "current_step_index": None,
        "current_step": None,
        "expected_action": None,
        "acting_team_ids": [],
        "members": [],
        "acting_member_ids": [],
        "viewer_member_ids": [],
        "member_eligible": None,
        "step_progress": None,
        "step_deadline": None,
        "current_round": None,
        "is_complete": False,
        "eligible": None,
        "draft_issues": [],
        "targets": None,
        "sides": [],
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
    #: The live seats, in slot order -- the actor vocabulary of every step.
    teams: list[EncounterTeam]
    steps: list[pbr.ResolvedStep]
    entries: list[PickBanEntry]
    submissions: list[PickBanSubmission]
    groups: dict[int, str | None] = field(default_factory=dict)
    #: ``{participation: its own roster}``. ``RuntimeCtx.targets`` flips it (a
    #: participation names the OPPONENT's players).
    rosters: dict[int, list[Player]] = field(default_factory=dict)
    #: A mix match's seated members in pick order (``load_member_seats``); empty in a tournament.
    seats: list[MemberSeat] = field(default_factory=list)
    #: ``{member: heroes they may not pick}`` -- the session's Fearless snapshot (``pool_json["exclusions"]``).
    exclusions: dict[int, frozenset[int]] = field(default_factory=dict)

    @property
    def participants(self) -> list[int]:
        return [team.id for team in self.teams]

    @property
    def members(self) -> dict[int, list[int]]:
        return members_by_team(self.seats)


class PickBanActionService:
    def __init__(
        self,
        *,
        entry_repo: PickBanEntryRepository = PickBanEntryRepository(),
        submission_repo: PickBanSubmissionRepository = PickBanSubmissionRepository(),
        games: EncounterGameService = encounter_game_service,
        sessions: PickBanSessionService = pick_ban_session_service,
    ) -> None:
        self.entry_repo = entry_repo
        self.submission_repo = submission_repo
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
        teams = await self.sessions.teams_of(session, encounter.id)
        steps = resolved_steps(pick_ban, teams)
        groups = await load_item_groups(
            session, PickBanKind(pick_ban.kind), [entry.item_id for entry in entries], encounter.discipline
        )
        rosters: dict[int, list[Player]] = {}
        if any(step.target is not None for step in steps):
            rosters = await self._load_rosters(session, teams, encounter.discipline)
        seats = await load_member_seats(session, encounter)
        snapshot = dict(pick_ban.pool_json or {}).get("exclusions") or {}
        exclusions = {int(member): frozenset(heroes) for member, heroes in snapshot.items()}
        return _Runtime(
            pick_ban=pick_ban,
            encounter=encounter,
            teams=teams,
            steps=steps,
            entries=entries,
            submissions=submissions,
            groups=groups,
            rosters=rosters,
            seats=seats,
            exclusions=exclusions,
        )

    async def _load_rosters(
        self, session: AsyncSession, teams: list[EncounterTeam], discipline: str
    ) -> dict[int, list[Player]]:
        """Every seat's roster rows, in the room's reading order: the game's rated roles in declaration order, mains
        before the substitutes that cover them, then by name. One query: a target step needs them all at once (each
        seat bans for the others)."""
        role_order = {code: index for index, code in enumerate(rated_role_codes(discipline))}
        by_source = {team.team_id: team.id for team in teams if team.team_id is not None}
        rosters: dict[int, list[Player]] = {team.id: [] for team in teams}
        if not by_source:
            return rosters
        rows = (await session.execute(select(Player).where(Player.team_id.in_(tuple(by_source))))).scalars().all()
        for row in rows:
            participation = by_source.get(row.team_id)
            if participation is not None:
                rosters[participation].append(row)

        def key(player: Player) -> tuple[int, int, str]:
            return (role_order.get(player.role, len(role_order)), 1 if player.is_substitution else 0, player.name or "")

        return {team_id: sorted(players, key=key) for team_id, players in rosters.items()}

    def _ctx(self, rt: _Runtime, step: pbr.ResolvedStep) -> pbr.RuntimeCtx:
        """The rules' view of the room for ONE step. ``available_item_ids`` is
        the step's own round, carried bans excluded (they are already spent);
        ``targets`` is flipped, because a participation names its OPPONENTS'
        players."""
        available = tuple(
            entry.item_id
            for entry in rt.entries
            if entry.carried_from_round is None and entry.round == step.round and str(entry.status) == pbr.AVAILABLE
        )
        targets: dict[int, list[pbr.TargetPlayer]] = {}
        if step.target is not None and rt.rosters:
            for team_id in rt.participants:
                targets[team_id] = [
                    pbr.TargetPlayer(
                        player_id=player.id,
                        role=player.role,
                    )
                    for opponent, players in rt.rosters.items()
                    if opponent != team_id
                    for player in players
                ]
        return pbr.RuntimeCtx(
            kind=str(rt.pick_ban.kind),
            round=step.round,
            best_of=rt.encounter.best_of,
            available_item_ids=available,
            groups=rt.groups,
            history=pbr.history_of(rt.steps, rt.submissions),
            targets=targets,
            members=rt.members,
            exclusions=rt.exclusions,
        )

    # -- sides -------------------------------------------------------------
    async def _apply_side_pick(
        self, session: AsyncSession, rt: _Runtime, step: pbr.ResolvedStep, actor: int, side: str
    ) -> None:
        """Write the chooser's side on the round's game, and the remaining side
        on the other seat.

        ``uq_game_team_side`` is the backstop: two participations cannot start
        one game on the same side, so a concurrent writer that got there first
        makes this transaction fail rather than quietly overwrite it.

        A PLAYED position keeps the sides it was played on: only a round replayed
        after a reset gets here for one, and a no-op keeps that room's tick from
        failing on every pass.
        """
        sides = side_codes(rt.encounter)
        if side not in sides:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{rt.encounter.discipline} has no side {side!r}",
            )
        position = step.round or 1
        if position in await self.games.played_positions(session, rt.encounter.id):
            return
        game = next(
            (game for game in await self.games.list_games(session, rt.encounter.id) if game.position == position),
            None,
        )
        if game is None:
            game = await self.games.open_game(session, rt.encounter, position=position)
        rows = {row.encounter_team_id: row for row in (await self.games.lines_by_game(session, [game]))[game.id]}
        # Cleared and flushed FIRST: a re-pick after an undo swaps the sides
        # round, and ``uq_game_team_side`` sees the half-applied state of one
        # statement batch -- the old holder would still own the side the new
        # one is being given.
        for row in rows.values():
            row.starting_side = None
        await session.flush()
        remaining = [code for code in sides if code != side]
        for team_id in rt.participants:
            row = rows.get(team_id)
            if row is None:
                row = EncounterGameTeam(game_id=game.id, encounter_id=rt.encounter.id, encounter_team_id=team_id)
                self.games.line_repo.add(session, row)
                rows[team_id] = row
            row.starting_side = side if team_id == actor else (remaining.pop(0) if remaining else None)
        await session.flush()

    def _sides_state(
        self, rt: _Runtime, games: list[EncounterGame], lines: dict[int, list[EncounterGameTeam]]
    ) -> list[dict[str, Any]]:
        """What each position's sides stand at, for the rooms that have any."""
        if not side_codes(rt.encounter):
            return []
        positions = {game.id: game.position for game in games}
        return [
            {
                "game_id": game_id,
                "position": positions[game_id],
                "sides": {str(row.encounter_team_id): row.starting_side for row in rows},
            }
            for game_id, rows in sorted(lines.items())
            if any(row.starting_side is not None for row in rows)
        ]

    def _bind_side_actors(self, rt: _Runtime) -> bool:
        """Give every unbound ``side:<code>`` step its actors, once the
        ``side_pick`` of its round has handed that side out.

        A round's steps are all resolved when the round OPENS, but a side only
        exists once the pick is played, so those steps are written with no
        actors and keep their token (``ResolvedStep.actors_token``). This is the
        other half: it runs at the top of every ``_settle`` pass and again the
        moment a side pick reveals, and it writes the bound sequence back to the
        session so the next request reads actors rather than an empty list. The
        token STAYS: undoing the pick has to be able to take the binding back.
        """
        unbound = [step for step in rt.steps if step.is_unbound]
        if not unbound:
            return False
        sides = side_codes(rt.encounter)
        participants = rt.participants
        bound = False
        for index, step in enumerate(rt.steps):
            if not step.is_unbound:
                continue
            assigned = pbr.assigned_sides(rt.steps, rt.submissions, sides, participants=participants, round=step.round)
            try:
                actors = pbr.resolve_actors(
                    step.actors_token or "",
                    participants=participants,
                    opener=rt.pick_ban.first_team_id or participants[0],
                    sides=assigned,
                )
            except pbr.UnassignedSide:
                continue  # its side pick has not revealed yet
            rt.steps[index] = step.model_copy(update={"actors": actors})
            bound = True
        if bound:
            # A member step bound to a side owes its members only now (spec §11.6 R4-2: ``lol_draft``'s picks).
            rt.steps = pbr.bind_members(rt.steps, rt.members)
            rt.pick_ban.resolved_sequence_json = [step.to_json() for step in rt.steps]
        return bound

    def side_pick_pending(self, rt: _Runtime, position: int) -> bool:
        """Whether position ``position`` still owes a ``side_pick`` an answer.

        A game cannot START while the side it is played on is undecided: the
        position stays ``planned`` -- named, but not open for claims -- until the
        pick resolves or the clock flips a coin for it.
        """
        if not side_codes(rt.encounter):
            return False
        return any(
            step.action == "side_pick"
            and (step.round or 1) == position
            and (step.is_unbound or not pbr.ready_to_reveal(step, rt.submissions))
            for step in rt.steps
        )

    def _blocked_positions(self, rt: _Runtime) -> frozenset[int]:
        """Positions no game may leave ``planned`` on yet."""
        rounds = {step.round or 1 for step in rt.steps if step.action == "side_pick"}
        return frozenset(position for position in rounds if self.side_pick_pending(rt, position))

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
        on: ``(session, step, participation, attempt)`` is unique, and reusing a
        voided attempt's number would collide with the row it voided.
        """
        attempt = pbr.current_attempt(rt.submissions, step_index)
        rows = [row for row in rt.submissions if row.step_index == step_index and row.attempt == attempt]
        return attempt + 1 if rows and all(row.state == pbr.VOIDED for row in rows) else attempt

    def _write(
        self,
        session: AsyncSession,
        rt: _Runtime,
        step: pbr.ResolvedStep,
        actor: int | None,
        items: list[dict[str, Any]],
        *,
        state: str,
        member: int | None = None,
    ) -> PickBanSubmission:
        """Create or replace ``actor``'s -- on a member step, ``member``'s -- live submission for this step."""
        attempt = self._writable_attempt(rt, step.index)
        row = pbr.actor_submission(rt.submissions, step.index, actor, member)
        now = datetime.now(UTC)
        normalized = [_item(item) for item in items]
        if row is None:
            row = PickBanSubmission(
                session_id=rt.pick_ban.id,
                encounter_id=rt.encounter.id,
                step_index=step.index,
                encounter_team_id=actor,
                team_member_id=member,
                attempt=attempt,
                state=state,
                items_json=normalized,
            )
            self.submission_repo.add(session, row)
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
        for actor, member in step.answers:
            row = pbr.actor_submission(rt.submissions, step.index, actor, member)
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
        self._bind_side_actors(rt)
        opening = pbr.current_step(rt.steps, rt.submissions)
        timed_index = opening.index if opening is not None else None
        changed = False
        # Each pass settles one step; the +2 covers the terminal no-op pass.
        for _ in range(len(rt.steps) + 2):
            pbr.project_entries(rt.entries, rt.steps, rt.submissions)
            step = pbr.current_step(rt.steps, rt.submissions)
            if step is None:
                break
            if step.is_unbound:
                # The ``side_pick`` that hands this step's side out has not been
                # played yet, and the cursor stops here (``current_step``), so
                # there is nothing this pass can settle. The bind above runs
                # again on the next one, after that step reveals.
                break
            if step.is_system:
                items = pbr.resolve_system_step(step, self._ctx(rt, step))
                self._write(session, rt, step, None, items, state=pbr.REVEALED)
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
                if step.action == "side_pick":
                    await self._settle_side_pick(session, rt, step)
                    # The side now exists, so every later step of this round
                    # that names it can finally be bound.
                    self._bind_side_actors(rt)
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
                owing: list[tuple[int, int | None]] = []
                for actor, member in step.answers:
                    row = pbr.actor_submission(rt.submissions, step.index, actor, member)
                    if actor is not None and (row is None or row.state not in (pbr.LOCKED, pbr.REVEALED)):
                        owing.append((actor, member))
                # A member step's stand-ins are matched jointly, across both teams (spec §11.6 R4-9): a hero is the
                # match's once, so one member's random hero must never strand another's.
                joint = (
                    pbr.fill_member_answers(
                        step, [(actor, member) for actor, member in owing if member is not None], self._ctx(rt, step)
                    )
                    if step.member is not None and step.on_timeout == "random_fill"
                    else {}
                )
                stood_in: list[int] = []
                for actor, member in owing:
                    row = pbr.actor_submission(rt.submissions, step.index, actor, member)
                    items = list(row.items_json or []) if row is not None else []
                    if step.action == "side_pick":
                        # A side nobody chose is a coin flip, which is what the
                        # rules call for; ``random_fill`` has no items to draw on.
                        items = [{"item_id": self._coin_flip_side(rt), "target_player_id": None}]
                    elif member is not None and step.on_timeout == "random_fill":
                        items = joint[(actor, member)]
                    elif step.on_timeout == "random_fill":
                        # A team's draft topped up at random; an assignment, a random matching (R4-9).
                        items = pbr.random_fill(step, actor, items, self._ctx(rt, step))
                    # Force-lock ignores `min`: standing in for a captain who
                    # never answered must not be blocked by what they owed.
                    self._write(session, rt, step, actor, items, state=pbr.LOCKED, member=member)
                    pbr.project_entries(rt.entries, rt.steps, rt.submissions)
                    if actor not in stood_in:
                        stood_in.append(actor)
                await record_room_event(
                    session,
                    rt.encounter.id,
                    action="step_timed_out",
                    source="system",
                    kind=str(rt.pick_ban.kind),
                    # ``team_ids`` is who the clock answered FOR, not who the step
                    # belonged to: an actor that locked in time was not timed out.
                    data={
                        "step_index": step.index,
                        "round": step.round,
                        "policy": step.on_timeout,
                        "team_ids": stood_in,
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

    def _coin_flip_side(self, rt: _Runtime) -> int:
        """The default a ``side_pick`` nobody answered settles on: a coin flip
        between the discipline's sides, encoded as the index the item slot
        carries."""
        return secrets.randbelow(len(side_codes(rt.encounter)) or 1)

    async def _settle_side_pick(self, session: AsyncSession, rt: _Runtime, step: pbr.ResolvedStep) -> None:
        """Write the revealed side onto the round's game rows."""
        sides = side_codes(rt.encounter)
        for actor in step.acting_actors:
            row = pbr.actor_submission(rt.submissions, step.index, actor)
            items = list(row.items_json or []) if row is not None else []
            if not items or not sides:
                continue
            index = int(items[0]["item_id"])
            await self._apply_side_pick(session, rt, step, actor, sides[index % len(sides)])

    # -- committing --------------------------------------------------------
    async def _commit(self, session: AsyncSession, rt: _Runtime, kind: PickBanKind) -> None:
        """Settle whatever this mutation unlocked, re-project, keep the series'
        games in step with the picks, and publish."""
        await self._settle(session, rt)
        await session.flush()
        if kind == PickBanKind.MAP:
            await self.games.sync_games_with_picks(
                session, rt.encounter, rt.pick_ban, blocked_positions=self._blocked_positions(rt)
            )
        await emit_pick_ban_update(session, rt.encounter.id, kind=kind.value)
        await session.commit()

    async def _blocked_rounds(self, session: AsyncSession, encounter: Encounter) -> frozenset[int]:
        """Series positions that already carry a claim or an accepted result --
        the rounds a dispute may no longer reopen, whichever kind asks."""
        return await self.games.played_positions(session, encounter.id)

    # -- reopening ---------------------------------------------------------
    async def _reopen(self, session: AsyncSession, rt: _Runtime, step: pbr.ResolvedStep) -> None:
        """Void the step's current attempt and open the next one. The clock
        restarts; a session that had run out of sequence comes back to life.

        Only a BLIND step's new drafts are prefilled with what each actor had:
        a blind draft stays private until everyone locks, so the prefill is a
        convenience nobody else sees. An open step's draft IS the board (it is
        projected as it is written), so a prefilled one would keep the voided
        item applied and turn the captain's next action into a second item --
        it starts EMPTY, the voided item available again. That covers a
        ``side_pick`` (never blind) too; its round's side-bound steps are also
        unbound and the position's sides taken back, so the re-choice binds
        everything afresh. Callers refuse a played position first."""
        attempt = pbr.current_attempt(rt.submissions, step.index)
        side_pick = step.action == "side_pick"
        previous: dict[tuple[int, int | None], list[dict[str, Any]]] = {}
        for row in rt.submissions:
            if row.step_index != step.index or row.attempt != attempt or row.state == pbr.VOIDED:
                continue
            if row.encounter_team_id is not None:
                previous[(row.encounter_team_id, row.team_member_id)] = [dict(item) for item in (row.items_json or [])]
            row.state = pbr.VOIDED
        for actor, member in step.answers:
            if actor is None:
                continue
            row = PickBanSubmission(
                session_id=rt.pick_ban.id,
                encounter_id=rt.encounter.id,
                step_index=step.index,
                encounter_team_id=actor,
                team_member_id=member,
                attempt=attempt + 1,
                state=pbr.DRAFT,
                items_json=previous.get((actor, member), []) if step.blind else [],
            )
            self.submission_repo.add(session, row)
            rt.submissions.append(row)
        if side_pick:
            # The `apply_undo` rule: `_bind_side_actors` rebinds only unbound steps.
            rt.steps = [
                other.unbound() if other.round == step.round and other.is_bound_to_side else other for other in rt.steps
            ]
            rt.pick_ban.resolved_sequence_json = [other.to_json() for other in rt.steps]
            await self.games.clear_sides(session, rt.encounter.id, {step.round or 1})
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
            if any(
                pbr.actor_submission(rt.submissions, step.index, actor, member) is not None
                for actor, member in step.answers
            )
        ]
        if not touched:
            return None
        latest = touched[-1]
        for actor, member in latest.answers:
            row = pbr.actor_submission(rt.submissions, latest.index, actor, member)
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
    def _require_mix_members(encounter: Encounter, members: Iterable[int | None]) -> None:
        """Only a mix match seats members (spec §11.6 R4-6): a ``member_id`` on a tournament room is a 422, for its
        captain and its organizer alike -- act and submit both ask here, before any turn is read."""
        if encounter.custom_game_id is None and any(member is not None for member in members):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="member_id names a mix match's seat"
            )

    @staticmethod
    def _require_turn(rt: _Runtime, step: pbr.ResolvedStep, actor: int, member: int | None = None) -> None:
        if actor not in step.acting_actors:
            names = {team.id: team.name for team in rt.teams}
            whose = " and ".join(names.get(other, str(other)) for other in step.acting_actors) or "nobody"
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"It's {whose}'s turn, not {names.get(actor, actor)}'s",
            )
        if step.member is not None and (actor, member) not in step.answers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Name a member of your team who owes this pick"
            )
        if step.member is None and member is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="This step is the team's, not a member's"
            )
        row = pbr.actor_submission(rt.submissions, step.index, actor, member)
        if row is not None and row.state in (pbr.LOCKED, pbr.REVEALED):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Your answer to this step is already locked"
            )

    @staticmethod
    def _bind_free_pick(rt: _Runtime, step: pbr.ResolvedStep, actor: int, member: int | None) -> pbr.ResolvedStep:
        """A free-order pick (member ``any``) made for a teammate the step does not name yet: the step names them now,
        and the team's later free picks of the round the rest (:func:`pbr.rebind_free_pick`). Anything else -- another
        step, a member who is no choice -- is left to :meth:`_require_turn` to refuse."""
        if (
            step.member != "any"
            or member is None
            or (actor, member) in step.answers
            or member not in pbr.free_pick_choices(rt.steps, step, actor, rt.members)
        ):
            return step
        if any(
            pbr.actor_submission(rt.submissions, step.index, seat_actor, seat_member) is not None
            for seat_actor, seat_member in step.answers
            if seat_actor == actor
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Your answer to this step is already locked"
            )
        rt.steps = pbr.rebind_free_pick(rt.steps, step, actor, member, rt.members)
        rt.pick_ban.resolved_sequence_json = [other.to_json() for other in rt.steps]
        return next(other for other in rt.steps if other.index == step.index)

    @staticmethod
    def _require_picker(
        rt: _Runtime,
        step: pbr.ResolvedStep,
        actor: int,
        member: int | None,
        *,
        viewer: int | None,
        viewer_member: int | None,
    ) -> None:
        """A ``captains_only`` member step through the captain route: the team's captain picks, for any teammate; a
        team whose lineup crowns nobody picks as without the rule, each member for themselves. A host acting through
        the organizer route (``viewer`` None) is never refused here."""
        if not step.captains_only or viewer != ACTING_VIEWER:
            return
        captain = next((seat.id for seat in rt.seats if seat.team_id == actor and seat.is_captain), None)
        if viewer_member is not None and viewer_member == (captain if captain is not None else member):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your team's captain picks its heroes")

    # -- public API --------------------------------------------------------
    async def perform_pick_ban_action(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        encounter_team_id: int,
        *,
        item_id: int,
        action: str,
        target_player_id: int | None = None,
        member_id: int | None = None,
        viewer: int | None = ACTING_VIEWER,
        viewer_member: int | None = None,
        actor_auth_user_id: int | None = None,
    ) -> dict[str, Any]:
        """One item onto an OPEN step's submission. A blind step is answered
        with :meth:`submit_items` instead -- appending one item at a time to a
        draft nobody may see would leak its size through the progress counter.
        On a mix's member step ``member_id`` names whom the hero is for (spec §11.6 R4-1); ``viewer_member`` is the
        acting account's own mix seat, which the answer reads the room as (see :meth:`get_pick_ban_state`)."""
        # ``viewer`` is the admin discriminator this module already runs on
        # (see ACTING_VIEWER): an organizer acting FOR a seat passes it as None.
        encounter, pick_ban = await self._lock(session, encounter_id, kind, captain=viewer == ACTING_VIEWER)
        self._require_mix_members(encounter, [member_id])
        rt = await self._load(session, pick_ban, encounter, refresh=True)
        await self._settle(session, rt)
        step = self._require_step(rt)
        if step.blind:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This step is blind -- submit the whole draft instead",
            )
        if step.action == "assign":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This step assigns the team's heroes -- submit the whole assignment instead",
            )
        if action != step.action:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Expected action '{step.action}', got '{action}'"
            )
        step = self._bind_free_pick(rt, step, encounter_team_id, member_id)
        self._require_turn(rt, step, encounter_team_id, member_id)
        self._require_picker(rt, step, encounter_team_id, member_id, viewer=viewer, viewer_member=viewer_member)

        row = pbr.actor_submission(rt.submissions, step.index, encounter_team_id, member_id)
        items = [dict(item) for item in (row.items_json or [])] if row is not None else []
        items.append({"item_id": item_id, "target_player_id": target_player_id})
        if step.action == "side_pick":
            self._assert_side_choice(rt, item_id)
        else:
            issues = pbr.validate_items(
                step, encounter_team_id, items, self._ctx(rt, step), final=False, member=member_id
            )
            if issues:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=", ".join(issues))

        self._write(
            session,
            rt,
            step,
            encounter_team_id,
            items,
            state=pbr.LOCKED if len(items) >= step.count else pbr.DRAFT,
            member=member_id,
        )
        await record_room_event(
            session,
            encounter_id,
            action="acted",
            # Derived from the SAME discriminator the lock above runs on, never a
            # second flag: a journal that can disagree with who was allowed to
            # act is worse than no journal.
            source=_source_of(viewer),
            kind=kind.value,
            encounter_team_id=encounter_team_id,
            actor_auth_user_id=actor_auth_user_id,
            data={
                "step_index": step.index,
                "round": step.round,
                "action": action,
                "item_id": item_id,
                "target_player_id": target_player_id,
                **({"member_id": member_id} if member_id is not None else {}),
            },
        )
        # Any open undo consent was given against the action that WAS last; this
        # one supersedes it, so the agreement dies with the state it was read on.
        pick_ban_undo.clear_undo_request(pick_ban)
        await self._commit(session, rt, kind)
        return await self.get_pick_ban_state(
            session,
            encounter_id,
            kind,
            viewer=encounter_team_id if viewer == ACTING_VIEWER else viewer,
            viewer_member=viewer_member,
        )

    def _assert_side_choice(self, rt: _Runtime, item_id: int) -> None:
        """A side pick names an INDEX into the discipline's sides, not a pool
        item: there is no board entry to validate it against."""
        sides = side_codes(rt.encounter)
        if not sides:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{rt.encounter.discipline} declares no sides to pick",
            )
        if not 0 <= item_id < len(sides):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Pick one of: {', '.join(f'{index} ({code})' for index, code in enumerate(sides))}",
            )

    async def submit_items(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        encounter_team_id: int,
        *,
        items: list[dict[str, Any]],
        lock: bool,
        viewer: int | None = ACTING_VIEWER,
        viewer_member: int | None = None,
        actor_auth_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Replace a BLIND step's draft, optionally locking it. A locked draft
        is final: the step reveals the moment every acting participation has one.
        A mix's assignment step (open, spec §11.6 R4-1) is answered here too, each item naming its ``member_id``;
        ``viewer_member`` is as for :meth:`perform_pick_ban_action`."""
        encounter, pick_ban = await self._lock(session, encounter_id, kind, captain=viewer == ACTING_VIEWER)
        self._require_mix_members(encounter, [item.get("member_id") for item in items])
        rt = await self._load(session, pick_ban, encounter, refresh=True)
        await self._settle(session, rt)
        step = self._require_step(rt)
        if not step.blind and step.action != "assign":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This step is open -- take it one item at a time",
            )
        self._require_turn(rt, step, encounter_team_id)

        draft = [_item(item) for item in items]
        issues = pbr.validate_items(step, encounter_team_id, draft, self._ctx(rt, step), final=lock)
        if issues:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=", ".join(issues))

        self._write(session, rt, step, encounter_team_id, draft, state=pbr.LOCKED if lock else pbr.DRAFT)
        source = _source_of(viewer)
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
                encounter_team_id=encounter_team_id,
                actor_auth_user_id=actor_auth_user_id,
                data={"step_index": step.index, "round": step.round, "items": draft},
            )
        pick_ban_undo.clear_undo_request(pick_ban)
        await self._commit(session, rt, kind)
        return await self.get_pick_ban_state(
            session,
            encounter_id,
            kind,
            viewer=encounter_team_id if viewer == ACTING_VIEWER else viewer,
            viewer_member=viewer_member,
        )

    async def dispute_step(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        encounter_team_id: int,
        *,
        actor_auth_user_id: int | None = None,
    ) -> dict[str, Any]:
        """A captain unilaterally reopens the blind step that just revealed --
        the answer to "they banned for the wrong player" that does not need the
        opponent's agreement, because the step is replayed by EVERY actor."""
        encounter, pick_ban = await self._lock(session, encounter_id, kind)
        rt = await self._load(session, pick_ban, encounter, refresh=True)
        await self._settle(session, rt)
        state = pbr.dispute_target(
            rt.steps,
            rt.submissions,
            actor=encounter_team_id,
            blocked_rounds=await self._blocked_rounds(session, encounter),
        )
        if not state.available or state.step_index is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This step cannot be reopened",
            )
        step = next(candidate for candidate in rt.steps if candidate.index == state.step_index)
        attempt = pbr.current_attempt(rt.submissions, step.index)
        await self._reopen(session, rt, step)
        await record_room_event(
            session,
            encounter_id,
            action="step_disputed",
            source="captain",
            kind=kind.value,
            encounter_team_id=encounter_team_id,
            actor_auth_user_id=actor_auth_user_id,
            # The attempt being thrown away, not the fresh one `_reopen` opened:
            # "they disputed attempt 1" is what the dispute limit counts.
            data={"step_index": step.index, "attempt": attempt},
        )
        await self._commit(session, rt, kind)
        return await self.get_pick_ban_state(session, encounter_id, kind, viewer=encounter_team_id)

    async def admin_reopen_step(
        self, session: AsyncSession, encounter_id: int, kind: PickBanKind, *, actor_auth_user_id: int | None = None
    ) -> dict[str, Any]:
        """The organizer's version of a dispute: the same replay, without the
        per-step attempt limit and without needing the step to allow disputes at
        all -- the escape hatch for a room that revealed something
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
        if step.action == "side_pick" and (step.round or 1) in await self.games.played_positions(session, encounter.id):
            raise pick_ban_undo.side_locked()
        await self._reopen(session, rt, step)
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
        return await self.get_pick_ban_state(session, encounter_id, kind, viewer=None)

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
        return games, await self.games.claims_by_game(session, games)

    async def freeplay_owed(self, session: AsyncSession, encounter: Encounter) -> bool:
        """Whether the series owes freeplay its next position.

        Freeplay offers ONE position at a time, only for a playable room, and
        only while no map session owns the positions instead.
        """
        map_session = await self.sessions.get_pick_ban_session(session, encounter.id, PickBanKind.MAP)
        if map_session is not None and str(map_session.status) != MapVetoSessionStatus.CANCELLED:
            return False
        games = await self.games.list_games(session, encounter.id)
        teams = await self.sessions.teams_of(session, encounter.id)
        return (
            len(teams) == encounter.slot_count
            and len(games) < encounter.best_of
            and not await self.games.series_settled(session, encounter)
            and not any(game.state in OPEN_STATES for game in games)
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
        teams = await self.sessions.teams_of(session, encounter.id)
        for kind in (PickBanKind.MAP, PickBanKind.HERO):
            pick_ban = await self.sessions.get_pick_ban_session(session, encounter.id, kind)
            if pick_ban is None:
                if await self.sessions.creation_plan(session, encounter, kind) is not None:
                    return True
                continue
            if str(pick_ban.status) == MapVetoSessionStatus.CANCELLED:
                continue
            rt_steps = resolved_steps(pick_ban, teams)
            submissions = list(await self.submission_repo.list_by_session(session, pick_ban.id))
            if self.session_pending(pick_ban, rt_steps, submissions):
                return True
            if await self.sessions.round_owed(session, encounter, kind):
                return True
            if kind == PickBanKind.MAP:
                entries = list(await self.entry_repo.list_by_session(session, pick_ban.id, ordered=True))
                games, claims = await self._game_snapshot(session, encounter)
                changes, stale = self.games._pick_game_changes(entries, games, claims)
                if changes or stale:
                    return True
        return await self.freeplay_owed(session, encounter)

    async def reconcile_room(self, session: AsyncSession, encounter_id: int, *, skip_locked: bool) -> bool:
        """Apply every heal this room owes, under the encounter lock, and publish
        what changed. Returns whether anything did.

        This is the ONLY place the room heals itself. The state read is pure
        (a viewer's poll must never queue behind a captain's write), so
        every "a map just got picked", "the clock ran out", "a position was
        confirmed and the next map's bans are owed", "the series owes a
        position" catches up here -- after every room write (``room_reconcile``'s
        post-commit trigger, which a game claim's own signal already stages) and
        on its two scheduled sweeps.

        ``skip_locked`` is for those sweeps: both tournament-service replicas run
        them, and a room another writer already holds needs no second healer.

        Lock order is the room's everywhere: encounter, then session.
        """
        encounter = await _encounters.get_any_owner(session, encounter_id)
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
                        await self.games.ensure_next_game(session, encounter)
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
        """Open the map room if it is owed, grow its rounds with the series,
        settle it, and keep the series' games in step with its picks. Returns
        the map session, if any."""
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
        # A confirmed position is what opens the NEXT map's bans; nothing else
        # calls the append for the map kind, so a progressive veto would stall
        # on round 1 forever without this.
        if await self.sessions._sync_rounds(session, encounter, PickBanKind.MAP, commit=False, encounter_locked=True):
            changed.add(PickBanKind.MAP.value)
        locked = await self.sessions.get_pick_ban_session(session, encounter.id, PickBanKind.MAP, for_update=True)
        if locked is None:
            return None  # a concurrent reset dropped it
        rt = await self._load(session, locked, encounter, refresh=True)
        if await self._settle(session, rt):
            changed.add(PickBanKind.MAP.value)
        await session.flush()
        games, claims = await self._game_snapshot(session, encounter, refresh=True)
        plan, stale = self.games._pick_game_changes(rt.entries, games, claims)
        if plan or stale:
            await self.games.sync_games_with_picks(
                session, encounter, locked, blocked_positions=self._blocked_positions(rt)
            )
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
        if await self.sessions._sync_rounds(session, encounter, PickBanKind.HERO, commit=False, encounter_locked=True):
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
        viewer: int | None = None,
        viewer_member: int | None = None,
    ) -> dict[str, Any]:
        """The room as it stands RIGHT NOW. A pure read: no lock, no write, no
        commit, no signal.

        Healing here would put every viewer's poll behind the encounter's row
        lock -- and so behind the captains and behind each other. Whatever this
        read finds un-healed is owed to :meth:`reconcile_room`, which runs after
        every room write and on a one-second sweep, and which signals the room
        when it lands.
        """
        encounter = await _encounters.get_any_owner(session, encounter_id)
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
                games, _claims = await self._game_snapshot(session, encounter)
                lines = await self.games.lines_by_game(session, games)
                payloads = await self.games.claim_payloads(session, games)
                state["games"] = [
                    self.games.serialize(game, lines.get(game.id, []), payloads[game.id]) for game in games
                ]
                state["series"] = await self._series(session, encounter)
            return state

        rt = await self._load(session, pick_ban, encounter)
        return await self._build_state(
            session, rt, kind, readiness=readiness, viewer=viewer, viewer_member=viewer_member
        )

    async def _series(self, session: AsyncSession, encounter: Encounter) -> dict[str, Any]:
        """What the confirmed games add up to, per participation."""
        standing = await self.games.standing(session, encounter)
        return {
            "ended": standing.ended,
            "games": standing.games,
            "totals": {str(team_id): value for team_id, value in standing.totals.items()},
            "wins": {str(team_id): value for team_id, value in standing.wins.items()},
            "placements": {str(team_id): value for team_id, value in standing.placements.items()},
        }

    async def _build_state(
        self,
        session: AsyncSession,
        rt: _Runtime,
        kind: PickBanKind,
        *,
        readiness: dict[str, bool],
        viewer: int | None,
        viewer_member: int | None = None,
    ) -> dict[str, Any]:
        """Render ``rt``. Pure: the room is rendered as it is, never as it ought
        to be -- drift is :meth:`reconcile_room`'s to fix."""
        games, claims = await self._game_snapshot(session, rt.encounter)
        lines = await self.games.lines_by_game(session, games)
        blocked_rounds = frozenset(
            game.position for game in games if game.state == EncounterGameState.CONFIRMED or claims.get(game.id)
        )
        step = pbr.current_step(rt.steps, rt.submissions)
        acting: list[int] = []
        acting_members: list[int] = []
        if step is not None:
            progress = pbr.step_progress(step, rt.submissions)
            acting = [actor for actor in step.acting_actors if not progress[actor]["locked"]]
            if step.member == "any":
                # A free-order pick is for any teammate still without a hero this round, whom it names on the act.
                for actor in acting:
                    acting_members.extend(pbr.free_pick_choices(rt.steps, step, actor, rt.members))
            else:
                for actor, member in step.answers:
                    row = pbr.actor_submission(rt.submissions, step.index, actor, member)
                    if member is not None and (row is None or row.state not in (pbr.LOCKED, pbr.REVEALED)):
                        acting_members.append(member)
        team_of = {seat.id: seat.team_id for seat in rt.seats}
        # A ``captains_only`` step leaves a member their own pick only on a team whose lineup crowns nobody.
        crowned = (
            {seat.team_id for seat in rt.seats if seat.is_captain} if step is not None and step.captains_only else set()
        )
        # Whom this viewer may pick for on a member step: themselves first, then -- as captain -- every teammate
        # still owing (spec §11.3, §11.6 R4-9, R4-11). A host picks for anyone through the organizer route.
        viewer_members = sorted(
            (
                member
                for member in acting_members
                if (member == viewer_member and team_of.get(member) not in crowned)
                or (viewer is not None and team_of.get(member) == viewer)
            ),
            key=lambda member: member != viewer_member,
        )
        viewer_can_act = (
            step is not None
            and step.action in _CAPTAIN_ACTIONS
            and str(rt.pick_ban.status) != MapVetoSessionStatus.CANCELLED
            and rt.pick_ban.paused_at is None
            and (bool(viewer_members) if step.member is not None else viewer in acting)
        )

        eligible: dict[str, Any] | None = None
        draft_issues: list[str] = []
        if (
            viewer_can_act
            and step is not None
            and viewer is not None
            and step.action != "side_pick"
            and step.member is None
        ):
            ctx = self._ctx(rt, step)
            eligible = pbr.eligible_items(step, viewer, ctx).to_json()
            row = pbr.actor_submission(rt.submissions, step.index, viewer)
            draft_issues = pbr.validate_items(
                step, viewer, list(row.items_json or []) if row is not None else [], ctx, final=True
            )
        member_eligible: dict[str, list[int]] | None = None
        if step is not None and (step.member is not None or step.action == "assign"):
            ctx = self._ctx(rt, step)
            owing = (
                acting_members if step.member is not None else [seat.id for seat in rt.seats if seat.team_id in acting]
            )
            member_eligible = {
                str(member): list(pbr.eligible_items(step, team_of[member], ctx, member).item_ids) for member in owing
            }

        targets: dict[str, list[dict[str, Any]]] | None = None
        if any(candidate.target is not None for candidate in rt.steps):
            grid = await get_division_grid(session, None, tournament_id=rt.encounter.tournament_id)
            targets = {
                str(team_id): [serialize_target(player, grid) for player in players]
                for team_id, players in rt.rosters.items()
            }

        state: dict[str, Any] = {
            "session": serialize_pick_ban_session(rt.pick_ban),
            "readiness": readiness,
            "sequence": [candidate.to_json() for candidate in rt.steps],
            "pool": [serialize_pick_ban_entry(entry) for entry in rt.entries],
            "submissions": [
                serialize_submission(row) for row in pbr.visible_submissions(rt.steps, rt.submissions, viewer)
            ],
            "viewer_team_id": viewer,
            "viewer_can_act": viewer_can_act,
            "allowed_actions": [step.action] if viewer_can_act and step is not None else [],
            "current_step_index": step.index if step is not None else None,
            "current_step": step.to_json() if step is not None else None,
            "expected_action": step.action if step is not None else None,
            "acting_team_ids": acting,
            #: A mix room's seated members in pick order (spec §11.6 R4-11): who member steps and assignments name;
            #: ``workspace_member_id`` ties each to the lineup seat and the viewer.
            "members": [
                {
                    "id": seat.id,
                    "encounter_team_id": seat.team_id,
                    "name": seat.name,
                    "workspace_member_id": seat.workspace_member_id,
                }
                for seat in rt.seats
            ],
            #: Members who still owe the current member step a hero.
            "acting_member_ids": acting_members,
            #: Of those, whom THIS viewer may pick for: themselves first, then -- as captain -- their teammates.
            "viewer_member_ids": viewer_members,
            #: ``{member: heroes they may take}`` on a member step (each member still owing) or an assignment (every
            #: member of a team still assigning) -- Fearless included; public, like the board.
            "member_eligible": member_eligible,
            "step_progress": (
                {str(team_id): value for team_id, value in pbr.step_progress(step, rt.submissions).items()}
                if step is not None
                else None
            ),
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
            #: The discipline's side codes, in the order a ``side_pick`` indexes
            #: them; empty when the game has no sides.
            "sides": list(side_codes(rt.encounter)),
            "dispute": pbr.dispute_target(
                rt.steps,
                rt.submissions,
                actor=viewer,
                blocked_rounds=blocked_rounds,
            ).to_json(),
            "undo": pick_ban_undo.undo_state(rt.pick_ban, rt.steps, rt.submissions),
            #: Every kind: a hero-only room (a game with no map veto) picks sides too.
            "starting_sides": self._sides_state(rt, games, lines),
        }
        if kind == PickBanKind.MAP:
            payloads = await self.games.claim_payloads(session, games)
            state["games"] = [self.games.serialize(game, lines.get(game.id, []), payloads[game.id]) for game in games]
            state["series"] = await self._series(session, rt.encounter)
        return state


pick_ban_action_service = PickBanActionService()
