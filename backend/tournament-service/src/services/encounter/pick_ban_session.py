"""Pick-ban session lifecycle: creates an encounter's room for one ``kind``
and grows it round by round.

Round 1 resolves the config's ruleset (``shared.domain.pick_ban_rules``) for
the first map of the series and creates that round's candidate entries. Round
N+1 is appended by :meth:`PickBanSessionService.advance_to_next_round` once map
N's result is known -- compiled from the session's ruleset and POOL snapshots
(an organizer editing or deleting the config mid-series must not change a
running room), with the still-active bans of earlier rounds re-created
as fixed ``carried`` entries (``lifetime``) and the rest of the pool filtered
through the matched phase's ``pool_filter``.

Everything the room answers is a PARTICIPATION: readiness is one row
per seat, the resolved sequence names the participations that take each step,
and the opener of a round is a participation id, never a side.

Creating the session and growing it are both WRITES, reached from the room's own
writes and from ``room_reconcile``'s healer -- never from the state read, which
is pure. :meth:`PickBanSessionService.creation_plan` and
:meth:`PickBanSessionService.round_owed` are the healer's unlocked prechecks,
and they are deliberately the same gates the writes themselves apply.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import (
    EncounterGameState,
    FirstBanRotation,
    MapPoolEntryStatus,
    MapVetoMode,
    MapVetoSessionStatus,
    PickBanKind,
)
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import rated_role_codes
from shared.domain import pick_ban_engine as engine
from shared.domain import pick_ban_rules as pbr
from shared.domain.encounter_scoring import GameLine, ScoringRules, resolve_placements
from shared.domain.pick_ban_config import has_pool, pick_config
from shared.models.catalog.entity import CatalogEntity
from shared.models.catalog.role import CatalogRole
from shared.models.encounter.encounter import Encounter
from shared.models.encounter.game import EncounterGame
from shared.models.encounter.pick_ban import PickBanEntry, PickBanSession
from shared.models.encounter.readiness import EncounterReadiness
from shared.models.encounter.team import EncounterTeam, EncounterTeamMember, EncounterTeamMemberRole
from shared.models.tournament.pick_ban import PickBanConfig
from shared.repository import (
    BracketEncounterRepository,
    EncounterReadinessRepository,
    EncounterRepository,
    PickBanConfigRepository,
    PickBanEntryRepository,
    PickBanSessionRepository,
    PickBanSubmissionRepository,
)
from shared.repository.pick_ban import CONFIG_ROOM_LOAD
from shared.services.encounter.participants import active_teams
from src.services.bracket.usability import is_encounter_live
from src.services.encounter.games import (
    EncounterGameService,
    GameResultIn,
    encounter_game_service,
    normalize_results,
)
from src.services.encounter.realtime_commit import emit_pick_ban_update
from src.services.encounter.room_journal import record_room_event
from src.services.encounter.room_owner import mix_ban_config, mix_fearless_exclusions
from src.services.encounter.room_reconcile import request_room_reconcile
from src.services.encounter.veto_session import (
    REASON_BRACKET_PREVIEW,
    REASON_NOT_CONFIGURED,
    REASON_SLOT_COUNT_MISMATCH,
    REASON_SLOT_UNDERFILLED,
    REASON_TEAMS_UNKNOWN,
    ROOM_SLOT_COUNT,
    SLOT_CANDIDATE_FLOOR,
    resolve_seeds,
    rounds_are_progressive,
    side_codes,
)

_encounters = EncounterRepository()
_positions = BracketEncounterRepository()

# Session-creation blocker distinct from the ``veto_session``-derived
# REASON_* set above: not every participation's captain has confirmed
# readiness yet. Not a config/team problem, so checked only once those are
# known-good -- see ``all_ready``/``mark_ready`` below.
REASON_NOT_READY = "not_ready"

# The hero phase of a round bans FOR a known map, so it cannot open before the
# map pick-ban has settled that round's map (both rulebooks ban heroes once per
# map of the series). Not a config problem -- it resolves on its own as the map
# phase progresses -- so it is reported separately from the REASON_* set above.
REASON_WAITING_MAP = "waiting_map"

_RESULT_ROTATIONS = (
    FirstBanRotation.RESULT_WINNER_FIRST,
    FirstBanRotation.RESULT_LOSER_FIRST,
    FirstBanRotation.RESULT_LOSER_CHOICE,
)


def unavailable_reason_for(
    encounter: Encounter,
    kind: PickBanKind,
    config: PickBanConfig | None,
    *,
    seats_complete: bool,
    live: bool,
    all_ready: bool,
    map_round_one_settled: bool,
) -> str:
    """Rank the blockers of one room, as a pure function of facts already read.

    Pure so a caller that loaded the facts in BULK -- the pre-game rooms
    overview, which answers dozens of encounters without re-querying each one --
    reports exactly what the room itself would report. Most specific blocker
    first: an unseated slot, then a preview bracket, then the config, then
    readiness, then the map phase a hero room waits on.
    """
    if not seats_complete:
        return REASON_TEAMS_UNKNOWN
    if not live:
        return REASON_BRACKET_PREVIEW
    if config is None:
        return REASON_NOT_CONFIGURED
    # A rules template is not a configured room: report it as such rather than
    # as a slot-count problem the organizer cannot fix at that scope.
    if not has_pool(config):
        return REASON_NOT_CONFIGURED
    if config.mode == MapVetoMode.SLOTS:
        if not config.slots or encounter.best_of > len(config.slots):
            return REASON_SLOT_COUNT_MISMATCH
        ordered = sorted(config.slots, key=lambda s: s.position)[: encounter.best_of]
        for slot in ordered:
            if len(slot.items) < SLOT_CANDIDATE_FLOOR:
                return REASON_SLOT_UNDERFILLED
    if not all_ready:
        return REASON_NOT_READY
    if kind == PickBanKind.HERO and not map_round_one_settled:
        return REASON_WAITING_MAP
    # Every gate is open and the row is simply not written yet: the healer opens
    # it right after the commit that lifted the last gate. Answer with the screen
    # the captains are already on rather than ``not_configured``, which the room
    # renders as "no pick-ban here" and would flash between "ready" and the board.
    return REASON_NOT_READY


def pool_snapshot(config: PickBanConfig, kind: PickBanKind, *, best_of: int) -> dict[str, Any]:
    """The config's pool and rotation as the session will remember them.

    Taken ONCE, at creation. Every later round reads this instead of the config
    row, so an organizer editing -- or deleting -- the config mid-series cannot
    change, or freeze, a running room.
    """
    ordered = sorted(config.slots, key=lambda slot: slot.position)[:best_of]
    return {
        "mode": str(getattr(config.mode, "value", config.mode)),
        "rotation": str(getattr(config.first_ban_rotation, "value", config.first_ban_rotation)),
        "progressive": rounds_are_progressive(config, kind),
        "items": [item.item_id for item in sorted(config.items, key=lambda item: item.sort_order)],
        "slots": [[item.item_id for item in slot.items] for slot in ordered],
    }


def pool_rotation(pool: dict[str, Any]) -> FirstBanRotation:
    return FirstBanRotation(str(pool.get("rotation") or FirstBanRotation.FIXED.value))


def round_candidates(pool: dict[str, Any], round_number: int | None) -> list[int] | None:
    """The candidates the snapshot offers for ``round_number``.

    ``None`` means the snapshot does not describe that round at all (a slot
    veto whose slots ran out), which is how a round that must not open says so.
    """
    if str(pool.get("mode")) == MapVetoMode.SLOTS.value:
        slots = list(pool.get("slots") or [])
        index = (round_number or 1) - 1
        return list(slots[index]) if 0 <= index < len(slots) else None
    return list(pool.get("items") or [])


def winner_of(rules: ScoringRules, lines: Sequence[GameLine]) -> int | None:
    """The participation one game's lines place first, alone; ``None`` on a draw.

    Pure, so the rotation reads a stored result (``round_result``) and a result
    still being written (``plan_dependent_rounds``) through one rule."""
    first = [team_id for team_id, place in resolve_placements(rules, lines).items() if place == 1]
    return first[0] if len(first) == 1 else None


@dataclass(frozen=True, slots=True)
class DependentRounds:
    """What a result correction owes the rooms whose next round its old result
    opened: rounds to scrap and re-append, and pending choices to re-address."""

    #: The round the corrected position opened.
    round: int
    #: Sessions whose untouched ``round`` is dropped and re-appended.
    drop: tuple[PickBanSession, ...] = ()
    #: ``result_loser_choice`` sessions still waiting on the OLD loser's call.
    rechoose: tuple[PickBanSession, ...] = ()


def parse_ruleset(data: object) -> pbr.Ruleset:
    """The config's/session's ruleset as a parsed document, or a 422.

    The engine raises ``RulesetError``; ``_run`` would turn that into a 500 on
    the state read that lazily creates or grows a session, which is exactly the
    path an organizer hits after saving a broken ruleset.
    """
    try:
        return pbr.parse_ruleset(data)
    except pbr.RulesetError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"This pick-ban ruleset cannot be played: {exc}",
        ) from exc


def resolved_steps(pick_ban: PickBanSession, teams: Sequence[EncounterTeam]) -> list[pbr.ResolvedStep]:
    """``resolved_sequence_json`` as engine objects.

    ``teams`` are the encounter's live seats in slot order: a stored sequence
    may name ``home``/``away`` instead of participations, and those mean slots
    1 and 2.
    """
    return pbr.resolved_steps_from_json(
        list(pick_ban.resolved_sequence_json or []),
        actors_by_slot={team.slot: team.id for team in teams},
    )


def assert_not_paused(pick_ban: PickBanSession) -> None:
    """Refuse a CAPTAIN write on a room an organizer has frozen.

    Lives here next to the session row every write path already loads, so the
    three of them (act/submit/dispute, undo, elect-opener) share one answer and
    one message instead of each deciding what a pause means.
    """
    if pick_ban.paused_at is not None:
        raise HTTPException(status_code=409, detail="Pick-ban session is paused")


def step_clock(pick_ban: PickBanSession) -> datetime:
    """The instant a step that opens NOW starts its timer.

    ``datetime.now`` on a running room, ``paused_at`` on a frozen one. Resume
    moves ``current_step_started_at`` forward by the whole pause, so a step that
    opened during it must start at the pause's beginning to come back with its
    full timer -- and an extension granted while frozen, which also moves that
    column, survives the resume instead of reading as a step that opened late.
    """
    if pick_ban.paused_at is None:
        return datetime.now(UTC)
    paused = pick_ban.paused_at
    return paused if paused.tzinfo is not None else paused.replace(tzinfo=UTC)


async def load_item_groups(
    session: AsyncSession, kind: PickBanKind, item_ids: list[int], discipline: str
) -> dict[int, str | None]:
    """``{item_id: group}`` for the ``item_group``/``target_role_match`` leaves:
    a character's class, a map's gamemode slug -- read in the encounter's own
    ``discipline`` (immutable once the encounter exists), so an id of another
    game is simply not in the pool and carries no group.

    Two flat selects rather than one join for the map kind: the projection a
    join would return is not what any repository exposes, and the second query
    only ever runs for a map room (a handful of gamemodes).
    """
    if not item_ids:
        return {}
    if kind == PickBanKind.HERO:
        rows = await session.execute(
            select(CatalogEntity.id, CatalogEntity.attrs["class"].astext).where(
                CatalogEntity.id.in_(item_ids),
                CatalogEntity.kind == "character",
                CatalogEntity.discipline == discipline,
            )
        )
        return {row[0]: row[1] for row in rows.all()}
    maps = (
        await session.execute(
            select(CatalogEntity.id, CatalogEntity.parent_id).where(
                CatalogEntity.id.in_(item_ids),
                CatalogEntity.kind == "map",
                CatalogEntity.discipline == discipline,
            )
        )
    ).all()
    gamemode_ids = sorted({row[1] for row in maps if row[1] is not None})
    slugs: dict[int, str] = {}
    if gamemode_ids:
        rows = await session.execute(
            select(CatalogEntity.id, CatalogEntity.slug).where(
                CatalogEntity.id.in_(gamemode_ids),
                CatalogEntity.kind == "mode",
                CatalogEntity.discipline == discipline,
            )
        )
        slugs = {row[0]: row[1] for row in rows.all()}
    return {row[0]: slugs.get(row[1]) for row in maps}


@dataclass(frozen=True, slots=True)
class MemberSeat:
    """One seated member of a mix match as a member step names it (``encounter.team_member``)."""

    id: int
    team_id: int
    name: str
    workspace_member_id: int
    #: The lineup's crown: whom a ``captains_only`` member step lets pick for the team.
    is_captain: bool = False


async def load_member_seats(session: AsyncSession, encounter: Encounter) -> list[MemberSeat]:
    """A mix match's seated members in pick order (spec §11.6 R4-2): the rated role's declaration order (LoL top,
    jungle, mid, bot, support under ``positions_5v5``), then the lineup's seat order -- the order the snapshot was
    written in. Empty for a tournament encounter: member steps are a mix's only (R4-6)."""
    if encounter.custom_game_id is None:
        return []
    role_order = {code: index for index, code in enumerate(rated_role_codes(encounter.discipline))}
    rows = await session.execute(
        select(
            EncounterTeamMember.id,
            EncounterTeamMember.encounter_team_id,
            EncounterTeamMember.display_name_snapshot,
            EncounterTeamMember.workspace_member_id,
            EncounterTeamMember.is_captain,
            CatalogRole.code,
        )
        .outerjoin(EncounterTeamMemberRole, EncounterTeamMemberRole.team_member_id == EncounterTeamMember.id)
        .outerjoin(CatalogRole, CatalogRole.id == EncounterTeamMemberRole.role_id)
        .where(EncounterTeamMember.encounter_id == encounter.id, EncounterTeamMember.active.is_(True))
    )
    best: dict[int, tuple[int, int, str, int, bool]] = {}
    for member_id, team_id, name, workspace_member_id, is_captain, role in rows.all():
        order = role_order.get(role, len(role_order))
        if member_id not in best or order < best[member_id][0]:
            best[member_id] = (order, team_id, name, workspace_member_id, bool(is_captain))
    ordered = sorted(best.items(), key=lambda item: (item[1][0], item[0]))
    return [
        MemberSeat(member_id, team_id, name, wm_id, is_captain)
        for member_id, (_order, team_id, name, wm_id, is_captain) in ordered
    ]


def members_by_team(seats: Sequence[MemberSeat]) -> dict[int, list[int]]:
    """``{participation: its members in pick order}`` -- what ``resolve_round``/``bind_members`` read."""
    grouped: dict[int, list[int]] = {}
    for seat in seats:
        grouped.setdefault(seat.team_id, []).append(seat.id)
    return grouped


@dataclass(frozen=True, slots=True)
class CreationPlan:
    """What round 1 of a room needs, once every gate on opening it said yes.

    Returned rather than a bare ``bool`` so the unlocked precheck and the
    creation itself run the exact same gates: the precheck throws the plan away,
    the creation builds round 1 out of it."""

    config: PickBanConfig
    #: The encounter's live seats, in slot order.
    teams: list[EncounterTeam]
    #: The snapshot the session will own, pool and rotation together.
    pool: dict[str, Any]
    slot_reserves: dict[str, int] | None


class PickBanSessionService:
    """Create, grow and reset an encounter's ``kind``-scoped pick-ban session.

    Every step-committing path goes through :meth:`get_pick_ban_session` /
    :meth:`lock_pick_ban_session`, which are the only serialization the step
    cursor has -- see their docstrings.
    """

    def __init__(
        self,
        *,
        session_repo: PickBanSessionRepository = PickBanSessionRepository(),
        entry_repo: PickBanEntryRepository = PickBanEntryRepository(),
        config_repo: PickBanConfigRepository = PickBanConfigRepository(),
        readiness_repo: EncounterReadinessRepository = EncounterReadinessRepository(),
        submission_repo: PickBanSubmissionRepository = PickBanSubmissionRepository(),
        games: EncounterGameService = encounter_game_service,
    ) -> None:
        self.session_repo = session_repo
        self.entry_repo = entry_repo
        self.config_repo = config_repo
        self.readiness_repo = readiness_repo
        self.submission_repo = submission_repo
        self.games = games

    async def teams_of(self, session: AsyncSession, encounter_id: int) -> list[EncounterTeam]:
        """The encounter's live seats in slot order -- the actor vocabulary
        every resolved step is written in."""
        return await active_teams(session, encounter_id)

    async def highest_round_of(self, session: AsyncSession, pick_ban: PickBanSession) -> int | None:
        """The highest round `pick_ban` has ever appended, or ``None`` in flat
        mode. Unlike ``pick_ban_engine.current_round`` (which reports the round with
        something still `AVAILABLE`, and so goes ``None`` the instant a round
        finishes), this stays truthful right through the `awaiting_choice` gap —
        exactly the round `elect_opener` needs `advance_to_next_round` to resume
        after, when nothing is `AVAILABLE` because the next round hasn't been
        created yet.

        The steps count as much as the entries: appending a round drops the
        previous round's untouched candidates, so a round that spent none of them
        (a side pick) is left with steps alone once the round after it is
        scrapped by a result correction."""
        rounds = [row for row in await self.entry_repo.list_rounds(session, pick_ban.id) if row is not None]
        rounds += [step["round"] for step in pick_ban.resolved_sequence_json or [] if step.get("round") is not None]
        return max(rounds) if rounds else None

    async def get_pick_ban_session(
        self,
        session: AsyncSession,
        encounter_id: int,
        kind: PickBanKind,
        *,
        for_update: bool = False,
    ) -> PickBanSession | None:
        """The encounter's ``kind``-scoped session, optionally locked for writing.

        ``for_update`` is REQUIRED of every path that commits a step, and it is the
        only thing serializing them. The cursor is derived from a read --
        ``pick_ban_rules.current_step`` walks the submission log -- and written
        back as a new submission. Two unlocked requests overlapping on one step
        therefore both resolve it, both pass the turn check, and both commit: one
        side gets an extra action and the opposite side's step is silently
        swallowed, or the unique ``(step, participation, attempt)`` key rejects the
        second writer with a 500 instead of a turn error.

        ``populate_existing`` matters as much as the lock: the row is usually
        already in the identity map (the read path loaded it before deciding it had
        work to do), and without it SQLAlchemy hands back that pre-lock snapshot --
        which is exactly the stale state the lock was taken to escape. The
        repository applies the two together for exactly that reason.
        """
        return await self.session_repo.get_for_encounter(
            session, encounter_id=encounter_id, kind=kind, for_update=for_update
        )

    async def lock_pick_ban_session(self, session: AsyncSession, pick_ban: PickBanSession) -> PickBanSession | None:
        """Lock an already-loaded session row and refresh it, for a committing path
        that was handed the object rather than fetching it. Returns ``None`` when
        the row is gone (a concurrent reset dropped it)."""
        return await self.session_repo.lock_by_id(session, pick_ban.id)

    async def resolve_config_at_level(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        kind: PickBanKind,
        stage_id: int | None,
        round: int | None,
    ) -> PickBanConfig | None:
        """The config this ``(tournament, kind, stage, round)`` coordinate resolves to.

        The cascade itself, addressed by coordinate rather than by encounter, so a
        caller that has no encounter in hand — the scrim room's "copy this round's
        pool" (``services/scrim/service.py``) — asks the same question the engine
        asks, instead of reimplementing the ranking and drifting from it.

        Ranking, most specific first: an exact stage+round config (2), the stage's
        round-less config (1), the tournament-wide config (0).

        A pool-less row is a rules template: it plays nothing, "as if no row
        existed". So a more specific empty fan-out must not shadow a parent's
        pool -- otherwise saving a stage as a template closes every round's room
        even after maps are authored at the tournament. The pool is the room's
        (``CONFIG_ROOM_LOAD``): a map pool's mode items are not candidates, so a
        pool of only modes is a template here too.

        Stays a service query: this loads every candidate row of the cascade and
        ranks them in Python, where ``PickBanConfigRepository.find_for_stage_round``
        matches ONE exact (stage, round) coordinate.
        """
        result = await session.execute(
            self.config_repo.select()
            .where(
                PickBanConfig.tournament_id == tournament_id,
                PickBanConfig.kind == kind,
                sa.or_(
                    PickBanConfig.stage_id.is_(None),
                    PickBanConfig.stage_id == stage_id,
                ),
            )
            .options(*CONFIG_ROOM_LOAD)
        )
        return pick_config(result.scalars().all(), stage_id=stage_id, round=round)

    async def resolve_config(
        self, session: AsyncSession, encounter: Encounter, kind: PickBanKind
    ) -> PickBanConfig | None:
        """The config this encounter's ``kind`` room plays, from its owner (spec §4.2).

        A mix encounter plays the preset its Start froze (``room_owner.mix_ban_config``). A tournament encounter
        resolves the cascade at its bracket coordinate; one with no position -- a scrim -- against the tournament-wide
        level.
        """
        if encounter.custom_game_id is not None:
            return await mix_ban_config(session, encounter, kind)
        position = await _positions.get_position(session, encounter.id)
        return await self.resolve_config_at_level(
            session,
            tournament_id=encounter.tournament_id,
            kind=kind,
            stage_id=position.stage_id if position is not None else None,
            round=position.round if position is not None else None,
        )

    async def settled_map_rounds(self, session: AsyncSession, encounter_id: int) -> int:
        """How many maps of the series the map pick-ban has settled.

        Mode-agnostic on purpose: rounds resolve in order, so the count of decided
        entries IS the highest settled round for a slot-mode session (one pick per
        round) and for a flat one (the whole order picked up front)
        alike.
        """
        pick_ban = await self.get_pick_ban_session(session, encounter_id, PickBanKind.MAP)
        if pick_ban is None:
            return 0
        # Aggregate COUNT, not a row fetch -- stays in the service rather than
        # loading every settled entry just to take its length.
        settled = await session.scalar(
            select(sa.func.count())
            .select_from(PickBanEntry)
            .where(
                PickBanEntry.session_id == pick_ban.id,
                PickBanEntry.status == MapPoolEntryStatus.PICKED,
            )
        )
        return int(settled or 0)

    async def map_round_settled(self, session: AsyncSession, encounter: Encounter, round_number: int) -> bool:
        """Whether the map that round ``round_number`` will be played on is decided
        -- the precondition for that round's hero bans opening. An encounter with
        no map pick-ban configured -- or one that resolves to a pool-less rules
        template, which opens no room either -- has no map phase to wait on."""
        map_config = await self.resolve_config(session, encounter, PickBanKind.MAP)
        if map_config is None or not has_pool(map_config):
            return True
        return await self.settled_map_rounds(session, encounter.id) >= round_number

    # -- readiness ---------------------------------------------------------
    async def get_readiness(self, session: AsyncSession, encounter_id: int) -> dict[str, bool]:
        """``{participation id (as a string): bool}`` -- whether each seat's
        captain has confirmed readiness to begin this encounter's pre-game
        phase. Keyed by the live seats, so a retired participation's old
        confirmation is not reported and a freshly seated one reads as not
        ready."""
        ready = set(await self.readiness_repo.list_ready_teams(session, encounter_id))
        return {str(team.id): team.id in ready for team in await self.teams_of(session, encounter_id)}

    async def all_ready(self, session: AsyncSession, encounter_id: int) -> bool:
        readiness = await self.get_readiness(session, encounter_id)
        return bool(readiness) and all(readiness.values())

    async def mark_ready(
        self,
        session: AsyncSession,
        encounter: Encounter,
        encounter_team_id: int,
        user_id: int | None,
        *,
        actor_auth_user_id: int | None = None,
        source: str = "captain",
    ) -> dict[str, bool]:
        """Idempotently record one participation's captain confirming readiness.
        Returns the resulting readiness map.

        ``user_id`` is the PLAYER identity stored on the row;
        ``actor_auth_user_id``/``source`` name whoever caused it for the journal
        -- an organizer forcing readiness has an auth account but no player one.

        The INSERT signals the room before it commits. It has to: until every
        seat is ready no session exists, and the room polls nothing while that
        is true -- so without the signal the OTHER captains' screens sit on
        "waiting for them" until they reload. ``kind="map"`` carries it for both
        kinds: the room's single ``encounter:{id}:map-veto`` subscription
        refetches map and hero state together.
        """
        existing = await self.readiness_repo.get_for_team(
            session, encounter_id=encounter.id, encounter_team_id=encounter_team_id
        )
        if existing is None:
            await self.readiness_repo.create(
                session,
                EncounterReadiness(
                    encounter_id=encounter.id, encounter_team_id=encounter_team_id, ready_user_id=user_id
                ),
            )
            await record_room_event(
                session,
                encounter.id,
                action="ready_marked",
                source=source,
                encounter_team_id=encounter_team_id,
                actor_auth_user_id=actor_auth_user_id,
            )
            await emit_pick_ban_update(session, encounter.id, kind="map")
            await session.commit()
        return await self.get_readiness(session, encounter.id)

    async def clear_ready(
        self,
        session: AsyncSession,
        encounter: Encounter,
        encounter_team_id: int,
        *,
        actor_auth_user_id: int | None = None,
    ) -> dict[str, bool]:
        """Take one participation's readiness back -- the organizer's override of
        a captain who confirmed too early.

        409 once a session of EITHER kind exists: readiness gates session
        CREATION only, so clearing it afterwards would change nothing while
        looking to the organizer like it un-started the room. Resetting the
        session is the action that actually does that.
        """
        for kind in PickBanKind:
            if await self.get_pick_ban_session(session, encounter.id, kind) is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Pick-ban session has already started; reset it instead of clearing readiness",
                )
        await self.readiness_repo.delete_for_team(
            session, encounter_id=encounter.id, encounter_team_id=encounter_team_id
        )
        # Always ``admin``: a captain has no way to take their own readiness back.
        await record_room_event(
            session,
            encounter.id,
            action="ready_cleared",
            source="admin",
            encounter_team_id=encounter_team_id,
            actor_auth_user_id=actor_auth_user_id,
        )
        await emit_pick_ban_update(session, encounter.id, kind="map")
        await session.commit()
        return await self.get_readiness(session, encounter.id)

    async def reset_readiness(self, session: AsyncSession, encounter_id: int) -> None:
        """Clear every seat's readiness -- called whenever a slot changes hands
        (a confirmation made against one opponent must not carry over to a
        different one)."""
        # Read first so the journal records a reset that actually took something
        # back: the seat-change hook runs on every bracket propagation, and most
        # of them touch an encounter nobody has confirmed readiness for yet.
        had_readiness = bool(await self.readiness_repo.list_ready_teams(session, encounter_id))
        await self.readiness_repo.delete_for_encounter(session, encounter_id)
        if had_readiness:
            await record_room_event(session, encounter_id, action="readiness_reset", source="system")

    async def unavailable_reason(self, session: AsyncSession, encounter: Encounter, kind: PickBanKind) -> str:
        """Why ``ensure_pick_ban_session`` returned ``None`` for this
        encounter/kind.

        The ranking itself is :func:`unavailable_reason_for`; this gathers the
        facts that answer it. The cheap ones are read unconditionally -- this
        runs on a room that cannot open, and a second copy of the ranking would
        cost correctness. The map-phase fact is read only when it can change
        the answer: asking the map session for a hero room that is blocked on
        its seats or its readiness anyway would be a query with no effect.
        """
        config = await self.resolve_config(session, encounter, kind)
        live = await is_encounter_live(session, encounter)
        teams = await self.teams_of(session, encounter.id)
        ready = await self.all_ready(session, encounter.id)

        def rank(map_round_one_settled: bool) -> str:
            return unavailable_reason_for(
                encounter,
                kind,
                config,
                seats_complete=len(teams) == encounter.slot_count,
                live=live,
                all_ready=ready,
                map_round_one_settled=map_round_one_settled,
            )

        if rank(True) == rank(False):
            return rank(True)
        return rank(await self.map_round_settled(session, encounter, 1))

    async def ensure_pick_ban_session(
        self,
        session: AsyncSession,
        encounter: Encounter,
        kind: PickBanKind,
        *,
        commit: bool = True,
    ) -> PickBanSession | None:
        """Idempotently create the FIRST round of the encounter's pick-ban session.

        Round 1 resolves the cascade-resolved config (seed resolution, slot
        validation) through the ruleset: the phase whose ``when`` matches map 1
        supplies both the steps and the ``pool_filter`` its candidates must pass.
        The parsed ruleset AND the config's pool are SNAPSHOTTED onto the session
        -- every later round compiles from those copies, never from the config's
        live rows.

        When the rounds are progressive (``rounds_are_progressive``) the session
        gets round 1 and nothing else, and every later round is appended one at a
        time by ``advance_to_next_round`` as the series is played -- so round 2's
        bans cannot be taken before round 1's map has been played. A flat
        ``kind=map`` config is untouched: one round (``round IS NULL``) whose
        sequence settles the whole series, because that IS the classic veto.
        """
        return await self._ensure_pick_ban_session(session, encounter, kind, commit=commit)

    async def _select_encounter_locked(
        self, session: AsyncSession, encounter_id: int, *, skip_locked: bool
    ) -> Encounter | None:
        return await _encounters.get_any_owner_for_update(session, encounter_id, skip_locked=skip_locked)

    async def _lock_encounter(self, session: AsyncSession, encounter_id: int) -> Encounter:
        """Room mutation lock; discard the pre-lock encounter snapshot."""
        encounter = await self._select_encounter_locked(session, encounter_id, skip_locked=False)
        if encounter is None:
            raise HTTPException(status_code=404, detail="Encounter not found")
        return encounter

    async def try_lock_encounter(self, session: AsyncSession, encounter_id: int) -> Encounter | None:
        """:meth:`_lock_encounter` with SKIP LOCKED: ``None`` when another writer
        already holds the row.

        For the scheduled healers, which run on every replica at once and must
        never queue: whoever holds the lock is mid-write on this very room, so
        there is nothing a second healer could add by waiting for them.
        """
        return await self._select_encounter_locked(session, encounter_id, skip_locked=True)

    async def creation_plan(
        self, session: AsyncSession, encounter: Encounter, kind: PickBanKind
    ) -> CreationPlan | None:
        """Whether every gate on opening this room is open, and what round 1 needs.

        One copy of the gates, because two callers ask them: creation itself and
        the write-side healer's UNLOCKED precheck
        (``PickBanActionService.room_owes_write``). A second copy would drift and
        make the healer lock the encounter on every pass for a room creation then
        refuses to open.
        """
        # Not an error: this is the "is there a veto here" query the room polls,
        # and a lobby has no two seats to veto between.
        if encounter.slot_count != ROOM_SLOT_COUNT:
            return None
        teams = await self.teams_of(session, encounter.id)
        if len(teams) != encounter.slot_count:
            return None
        if not await is_encounter_live(session, encounter):
            return None
        config = await self.resolve_config(session, encounter, kind)
        if config is None or not has_pool(config):
            return None

        slot_reserves: dict[str, int] | None = None
        if config.mode == MapVetoMode.SLOTS:
            if not config.slots or encounter.best_of > len(config.slots):
                return None
            ordered = sorted(config.slots, key=lambda s: s.position)[: encounter.best_of]
            for slot in ordered:
                if len(slot.items) < SLOT_CANDIDATE_FLOOR:
                    return None
            # String-keyed by 1-based slot position, reserve-less slots omitted --
            # the room reads this snapshot off the session, never the config, so a
            # later config edit cannot move a running session's reserve labels.
            slot_reserves = {
                str(slot.position): slot.reserve_item_id for slot in ordered if slot.reserve_item_id is not None
            }

        if not await self.all_ready(session, encounter.id):
            return None

        # Heroes are banned FOR a map, so a hero session cannot open before the map
        # pick-ban has settled round 1's map. `_sync_rounds` keeps every later hero
        # round behind the same gate.
        if kind == PickBanKind.HERO and not await self.map_round_settled(session, encounter, 1):
            return None
        return CreationPlan(
            config=config,
            teams=teams,
            pool=pool_snapshot(config, kind, best_of=encounter.best_of),
            slot_reserves=slot_reserves,
        )

    async def _ensure_pick_ban_session(
        self,
        session: AsyncSession,
        encounter: Encounter,
        kind: PickBanKind,
        *,
        commit: bool,
        encounter_locked: bool = False,
    ) -> PickBanSession | None:
        existing = await self.get_pick_ban_session(session, encounter.id, kind)
        if existing is not None:
            return existing
        plan = await self.creation_plan(session, encounter, kind)
        if plan is None:
            return None
        if not encounter_locked:
            # A missing session has no row to lock. Lock its encounter only once
            # creation is actually owed, then repeat ALL gates and the existence
            # check against the refreshed row. Existing/unavailable rooms stay
            # unlocked; initialization and readiness/seat resets serialize.
            encounter = await self._lock_encounter(session, encounter.id)
            return await self._ensure_pick_ban_session(session, encounter, kind, commit=commit, encounter_locked=True)

        config, teams, pool = plan.config, plan.teams, plan.pool
        participants = [team.id for team in teams]
        seats = await load_member_seats(session, encounter)
        if encounter.custom_game_id is not None:
            # Fearless (spec §11.4): taken once, when the room opens -- like the pool, a running room never re-reads it.
            exclusions = await mix_fearless_exclusions(session, encounter)
            pool = {**pool, "exclusions": {str(member): sorted(heroes) for member, heroes in exclusions.items()}}
        seeds = await resolve_seeds(session, encounter, teams)
        now = datetime.now(UTC)
        progressive = bool(pool["progressive"])
        round_number = 1 if progressive else None
        round_one_item_ids = round_candidates(pool, round_number) or []
        pool_size = sum(len(slot) for slot in pool["slots"]) if pool["slots"] else len(pool["items"])

        # Round 1 has no history, so only the absolute leaves of `pool_filter`
        # (`item_in`/`item_group`) can exclude anything here -- but they can, and
        # a candidate the phase refuses must never become an entry.
        ruleset = parse_ruleset(config.ruleset_json)
        groups = await load_item_groups(session, kind, round_one_item_ids, encounter.discipline)
        pool_ctx = pbr.RuntimeCtx(kind=kind.value, round=round_number, best_of=encounter.best_of, groups=groups)
        phase = pbr.select_phase(
            ruleset, pbr.RoundCtx(round=round_number or 1, best_of=max(encounter.best_of, 1), kind=kind.value)
        )
        candidates = (
            pbr.filter_pool(phase.pool_filter, round_one_item_ids, pool_ctx)
            if phase is not None
            else list(round_one_item_ids)
        )
        steps = pbr.resolve_round(
            ruleset,
            kind=kind.value,
            round=round_number,
            start_index=0,
            participants=participants,
            opener=seeds.opener,
            best_of=encounter.best_of,
            pool_size=pool_size,
            candidate_count=len(candidates),
            members=members_by_team(seats),
        )

        pick_ban = PickBanSession(
            encounter_id=encounter.id,
            kind=kind,
            pool_json=pool,
            first_team_id=seeds.opener,
            seed_source=seeds.seed_source,
            resolved_sequence_json=[step.to_json() for step in steps],
            ruleset_json=ruleset.to_json(),
            slot_reserves_json=plan.slot_reserves,
            # A round whose phase resolved to no steps is already settled; the
            # first read then advances straight to the next one instead of
            # hanging on a cursor that can never move.
            status=MapVetoSessionStatus.ACTIVE if steps else MapVetoSessionStatus.COMPLETED,
            awaiting_choice=False,
            started_at=now,
            current_step_started_at=now,
        )
        self.session_repo.add(session, pick_ban)
        self.entry_repo.add_many(
            session,
            [
                PickBanEntry(
                    session=pick_ban,
                    encounter_id=encounter.id,
                    item_id=item_id,
                    order=offset,
                    round=round_number,
                    status=MapPoolEntryStatus.AVAILABLE,
                )
                for offset, item_id in enumerate(candidates)
            ],
        )

        await record_room_event(
            session,
            encounter.id,
            action="session_opened",
            source="system",
            kind=kind.value,
            encounter_team_id=seeds.opener,
            data={
                "first_team_id": seeds.opener,
                "seed_source": str(getattr(seeds.seed_source, "value", seeds.seed_source)),
                "seeds": {str(team_id): seed for team_id, seed in seeds.seeds.items()},
            },
        )

        await emit_pick_ban_update(session, encounter.id, kind=kind.value)
        if commit:
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                return await self.get_pick_ban_session(session, encounter.id, kind)
        else:
            await session.flush()
        return pick_ban

    async def reset_pick_ban_session(
        self,
        session: AsyncSession,
        encounter: Encounter,
        kind: PickBanKind,
        *,
        commit: bool = True,
        actor_auth_user_id: int | None = None,
        source: str = "admin",
    ) -> PickBanSession | None:
        """Hard reset: delete this encounter's `kind`-scoped pick-ban session and
        recreate round 1 from scratch. Its entries AND its submission log -- the
        cross-round memory every `banned_by` condition reads -- cascade with it
        via the DB FK, so a from-scratch reset genuinely forgets what the
        scrapped session banned.

        A MAP reset also retires the series' live games: they were opened by the
        picks this is about to scrap, so leaving them would let a position of the
        OLD veto keep collecting claims (and counting into the live score) under
        a pool that no longer names it.

        A reset also takes back the sides of every position nobody has played
        yet, whichever room handed them out -- the room is being redone, and a
        side left behind would satisfy ``side_pick_required`` for a game whose
        side is about to be picked again. A played position keeps its sides
        (history).

        ``source`` defaults to the organizer who normally asks for this; the
        seat-change hook passes ``system``, having no human behind it."""
        if kind == PickBanKind.MAP:
            await self.games.cancel_games(
                session,
                encounter,
                await self.games.list_games(session, encounter.id),
                actor_user_id=None,
                reason="map_session_reset",
            )
        if side_codes(encounter):
            live = {game.position for game in await self.games.list_games(session, encounter.id)}
            await self.games.clear_sides(
                session, encounter.id, live - await self.games.played_positions(session, encounter.id)
            )
        existing = await self.get_pick_ban_session(session, encounter.id, kind)
        if existing is not None:
            await self.session_repo.delete_by_id(session, existing.id)
            # Only when there WAS a session: the journal records what was
            # scrapped, and resetting a room that never opened scrapped nothing.
            await record_room_event(
                session,
                encounter.id,
                action="session_reset",
                source=source,
                kind=kind.value,
                actor_auth_user_id=actor_auth_user_id,
            )
        await session.flush()
        # Unconditional even if the re-ensure below no-ops: the room just lost its
        # session.
        await emit_pick_ban_update(session, encounter.id, kind=kind.value)
        pick_ban = await self.ensure_pick_ban_session(session, encounter, kind, commit=False)
        if commit:
            await session.commit()
        return pick_ban

    async def sync_pick_ban_session_after_team_change(
        self,
        session: AsyncSession,
        encounter: Encounter,
        kind: PickBanKind,
    ) -> None:
        """Seat-assignment hook (bracket propagation / admin encounter edits).

        Called after an encounter's participations changed. Every seat now
        filled with no session -> ensure one. Session already exists -> the
        snapshot names participations that may be gone, so reset it -- UNLESS a
        game of the series is already CONFIRMED (a map really was played; an
        admin untangles that by hand). Runs inside the caller's
        transaction (no commit).

        The series SCORE is not consulted: a cascade reset cancels the old
        pairing's games before this hook runs, so nothing confirmed survives it,
        and a drawn first map — which scores 0:0 — is still a played map that
        must not be silently re-vetoed.
        """
        pick_ban = await self.get_pick_ban_session(session, encounter.id, kind)
        if pick_ban is None:
            if len(await self.teams_of(session, encounter.id)) == encounter.slot_count:
                await self.ensure_pick_ban_session(session, encounter, kind, commit=False)
            return
        games = await self.games.list_games(session, encounter.id)
        if any(game.state == EncounterGameState.CONFIRMED for game in games):
            return
        await self.reset_pick_ban_session(session, encounter, kind, commit=False, source="system")

    async def sync_all_pick_ban_sessions_after_team_change(self, session: AsyncSession, encounter: Encounter) -> None:
        """``sync_pick_ban_session_after_team_change`` for every kind, in the
        two-arg shape (``session``, ``encounter``) that ``admin/encounter.py``,
        ``challonge/sync.py`` and the bracket advancement callback all call.
        Also clears ``EncounterReadiness`` -- a confirmation made against one
        opponent must not carry over once a slot changes hands."""
        await self.reset_readiness(session, encounter.id)
        for kind in (PickBanKind.MAP, PickBanKind.HERO):
            await self.sync_pick_ban_session_after_team_change(session, encounter, kind)
        # A pairing that only just became complete emits nothing above (there was
        # no session to reset), yet now owes one; the state read is pure and
        # never opens it.
        request_room_reconcile(session, encounter.id)

    # -- growing the session ----------------------------------------------
    async def advance_to_next_round(
        self,
        session: AsyncSession,
        pick_ban: PickBanSession,
        *,
        completed_round: int,
        winner: int | None,
        decided: bool = True,
        loser_choice: int | None = None,
        commit: bool = True,
    ) -> PickBanSession:
        """Append the round after ``completed_round``: its resolved steps, the
        earlier rounds' still-active bans as carried entries, and its candidates.

        This is the barrier between two maps of a series. It
        is a no-op, returning ``pick_ban`` unchanged, unless all of:

        - the session's rounds are progressive (``pool_json['progressive']``) — a
          flat ``kind=map`` veto settles the whole series at once and has no later
          round to open;
        - the round currently in play is fully resolved — a new round is never
          stacked on top of an unfinished one;
        - the next round has not been appended already (idempotent re-entry);
        - the snapshot still describes that round (slot count) and the series
          still has that many maps (``best_of``).

        Both the steps and the POOL come from the session's snapshots, never from
        the config: an organizer editing or deleting the config mid-series
        changes nothing about a running room.

        ``decided`` is whether the previous position has an accepted result at
        all; ``winner`` is the participation that won it outright, and ``None``
        for a DRAW -- which is decided and names nobody. The two are separate
        because they mean opposite things here: a drawn map falls back to the
        session's established opener and the round opens NOW, while an undecided
        one owes the round until the result lands (opening it would have to
        invent an opener).

        Raises ``pick_ban_engine.RotationNeedsChoice`` when the rotation is
        ``result_loser_choice`` and ``loser_choice`` was not supplied — the caller
        must catch this, set ``awaiting_choice=True`` and wait for an explicit
        ``elect_opener`` call instead of resolving an actor here.

        Takes the session lock itself rather than trusting its caller: it is
        reached from a result, from the healer and from ``elect_opener``, and the
        idempotency check below ("has round N+1 already been appended") is a read
        the appending INSERT depends on -- two unlocked appenders would both pass
        it and both write the round's candidates.
        """
        locked = await self.lock_pick_ban_session(session, pick_ban)
        if locked is None:
            return pick_ban  # a concurrent reset dropped the session
        pick_ban = locked
        pool = dict(pick_ban.pool_json or {})
        if not pool.get("progressive"):
            return pick_ban

        # `populate_existing` is load-bearing: this same session may have read
        # these entries before taking the lock above, and the identity map would
        # otherwise serve that pre-lock snapshot back.
        entries = list(await self.entry_repo.list_by_session(session, pick_ban.id, populate_existing=True))
        teams = await self.teams_of(session, pick_ban.encounter_id)
        steps = resolved_steps(pick_ban, teams)
        submissions = list(await self.submission_repo.list_by_session(session, pick_ban.id, populate_existing=True))
        if pbr.current_step(steps, submissions) is not None:
            return pick_ban  # the round in play still has steps left to take

        next_round = completed_round + 1
        if any(entry.round == next_round for entry in entries):
            return pick_ban  # already appended (idempotent re-entry)

        encounter = await _encounters.get_any_owner(session, pick_ban.encounter_id)
        if encounter is None or next_round > encounter.best_of:
            return pick_ban
        candidate_item_ids = round_candidates(pool, next_round)
        if candidate_item_ids is None:
            return pick_ban  # the series is longer than the snapshot's slots

        participants = [team.id for team in teams]
        rotation = pool_rotation(pool)
        # PENDING, not drawn: a confirmed draw names no winner and falls back to
        # the session's opener (``resolve_round_opener``), while a position with
        # no accepted result yet owes the round until it has one. Collapsing the
        # two would leave a drawn map stalling the room forever.
        if not decided and next_round > 1 and rotation in _RESULT_ROTATIONS:
            return pick_ban  # the round is owed until the previous position is confirmed
        opener = engine.resolve_round_opener(
            rotation=rotation,
            round_number=next_round,
            participants=participants,
            session_opener=pick_ban.first_team_id or participants[0],
            previous_round_winner=winner,
            previous_round_loser_choice=loser_choice,
        )

        ruleset = parse_ruleset(pick_ban.ruleset_json)
        round_ctx = pbr.RoundCtx(round=next_round, best_of=max(encounter.best_of, 1), kind=str(pick_ban.kind))
        phase = pbr.select_phase(ruleset, round_ctx)

        # Bans of earlier rounds whose `lifetime` still covers this one. They are
        # created as FIXED entries (never re-projected) so the board shows them
        # banned with their origin map, and they are excluded from the round's
        # own candidates rather than competing with them.
        carried = pbr.carried_bans(steps, submissions, next_round)
        carried_ids = {ban.item_id for ban in carried}

        groups = await load_item_groups(session, PickBanKind(pick_ban.kind), candidate_item_ids, encounter.discipline)
        pool_ctx = pbr.RuntimeCtx(
            kind=str(pick_ban.kind),
            round=next_round,
            best_of=encounter.best_of,
            groups=groups,
            history=pbr.history_of(steps, submissions),
        )
        filtered = (
            pbr.filter_pool(phase.pool_filter, candidate_item_ids, pool_ctx)
            if phase is not None
            else list(candidate_item_ids)
        )
        candidates = [item_id for item_id in filtered if item_id not in carried_ids]

        new_steps = pbr.resolve_round(
            ruleset,
            kind=str(pick_ban.kind),
            round=next_round,
            start_index=len(steps),
            participants=participants,
            opener=opener,
            prev_winner=winner,
            best_of=encounter.best_of,
            pool_size=len(candidate_item_ids),
            candidate_count=len(candidates),
        )
        if pick_ban.kind == PickBanKind.MAP:
            self._assert_round_playable(pick_ban, pool, next_round, candidates, new_steps)

        # Closing the finished round drops the candidates nobody acted on: an
        # untouched candidate carries no state, and leaving a hero round's 30
        # unbanned heroes behind would keep the board showing a finished map's
        # pool next to the new one.
        await self.entry_repo.delete_round_by_status(
            session,
            session_id=pick_ban.id,
            round=completed_round,
            statuses=(MapPoolEntryStatus.AVAILABLE,),
        )

        pick_ban.resolved_sequence_json = [*pick_ban.resolved_sequence_json, *(step.to_json() for step in new_steps)]
        pick_ban.awaiting_choice = False
        pick_ban.pending_chooser_team_id = None
        # ``first_team_id`` stays the SEED opener: ``resolve_round_opener`` reads
        # it as the session's immutable baseline (``alternate`` counts rounds off
        # it), so writing this round's opener back would make round 3 repeat
        # round 2. Who opens THIS round is the journal row below and the step's
        # own actors.
        pick_ban.current_step_started_at = step_clock(pick_ban)
        if pick_ban.status == MapVetoSessionStatus.COMPLETED and new_steps:
            pick_ban.status = MapVetoSessionStatus.ACTIVE

        base_order = next_round * 1000  # generous per-round spacing; order is a display/tiebreak field only
        new_entries = [
            PickBanEntry(
                session=pick_ban,
                encounter_id=pick_ban.encounter_id,
                item_id=item_id,
                order=base_order + offset,
                round=next_round,
                status=MapPoolEntryStatus.AVAILABLE,
            )
            for offset, item_id in enumerate(candidates)
        ]
        for offset, ban in enumerate(carried, start=len(candidates)):
            kind_value, team_id = pbr.actor_columns(ban.actor)
            new_entries.append(
                PickBanEntry(
                    session=pick_ban,
                    encounter_id=pick_ban.encounter_id,
                    item_id=ban.item_id,
                    order=base_order + offset,
                    round=next_round,
                    status=MapPoolEntryStatus.BANNED,
                    picked_by_kind=kind_value,
                    picked_by_team_id=team_id,
                    carried_from_round=ban.from_round,
                )
            )
        await self.entry_repo.create_many(session, new_entries)

        await record_room_event(
            session,
            pick_ban.encounter_id,
            action="round_opened",
            source="system",
            kind=str(pick_ban.kind),
            encounter_team_id=opener,
            data={"round": next_round, "first_team_id": opener},
        )

        await emit_pick_ban_update(session, pick_ban.encounter_id, kind=str(pick_ban.kind))
        if commit:
            await session.commit()
        else:
            await session.flush()
        return pick_ban

    @staticmethod
    def _assert_round_playable(
        pick_ban: PickBanSession,
        pool: dict[str, Any],
        next_round: int,
        candidates: list[int],
        new_steps: list[pbr.ResolvedStep],
    ) -> None:
        """Map rounds must END on a decided map, so a round that cannot spend its
        steps is a config error the organizer has to see NOW, at round creation,
        not as an opaque stall on the room's next read. A hero round has no such
        floor: it leaves the unbanned pool playable, and `effective_min` already
        caps a lock against what is left."""
        if str(pool.get("mode")) == MapVetoMode.SLOTS.value and len(candidates) < SLOT_CANDIDATE_FLOOR:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Round {next_round} of the {pick_ban.kind} pick-ban has only {len(candidates)} "
                    f"candidate(s) left after the phase's pool filter (needs >= {SLOT_CANDIDATE_FLOOR}) "
                    "-- fix this tournament's pick-ban config (slot candidates or pool_filter)."
                ),
            )
        needed = sum(step.count * max(len(step.actors), 1) for step in new_steps if step.action != "side_pick")
        if len(candidates) < needed:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"Round {next_round} of the {pick_ban.kind} pick-ban has {len(candidates)} "
                    f"candidate(s) for {needed} item(s) of steps -- fix this tournament's pick-ban config "
                    "(pool size, step counts or pool_filter)."
                ),
            )

    async def elect_round_opener(
        self,
        session: AsyncSession,
        pick_ban: PickBanSession,
        *,
        first_team_id: int,
        acting_team_id: int | None,
        actor_auth_user_id: int | None = None,
    ) -> PickBanSession:
        """Resolve an ``awaiting_choice`` round by naming who opens it, then append
        it (``advance_to_next_round`` with the choice supplied).

        ``acting_team_id`` is the participation making the call. ``None`` is the
        ADMIN override: `result_loser_choice` is the one rotation whose next round
        cannot open without a human, so an unreachable losing captain would
        otherwise freeze the room with nothing on screen to act on and nothing but
        a session-wiping reset to reach for.
        """
        await session.execute(
            select(Encounter)
            .where(Encounter.id == pick_ban.encounter_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        locked = await self.lock_pick_ban_session(session, pick_ban)
        if locked is None:
            raise HTTPException(status_code=400, detail="No round is awaiting an opener choice")
        pick_ban = locked
        if not pick_ban.awaiting_choice:
            raise HTTPException(status_code=400, detail="No round is awaiting an opener choice")
        teams = await self.teams_of(session, pick_ban.encounter_id)
        participants = [team.id for team in teams]
        if first_team_id not in participants:
            raise HTTPException(status_code=422, detail="That team does not play in this encounter")
        if acting_team_id is not None:
            # A pause freezes the captains, never the organizer override below.
            assert_not_paused(pick_ban)
            # Only the loser of the round that triggered the choice may elect --
            # otherwise either captain could dictate who opens the next round.
            if acting_team_id != pick_ban.pending_chooser_team_id:
                raise HTTPException(
                    status_code=403, detail="Only the losing captain may choose who opens the next round"
                )
        # The participation that did NOT lose is the outcome this rotation was
        # suspended on; a draw never suspends it (`resolve_round_opener` falls back).
        winner = next(
            (team_id for team_id in participants if team_id != pick_ban.pending_chooser_team_id),
            None,
        )
        completed_round = await self.highest_round_of(session, pick_ban) or 0
        await record_room_event(
            session,
            pick_ban.encounter_id,
            action="opener_elected",
            # ``acting_team_id is None`` IS the admin override -- see the docstring.
            source="captain" if acting_team_id is not None else "admin",
            kind=str(pick_ban.kind),
            encounter_team_id=acting_team_id,
            actor_auth_user_id=actor_auth_user_id,
            data={"round": completed_round + 1, "first_team_id": first_team_id},
        )
        return await self.advance_to_next_round(
            session,
            pick_ban,
            completed_round=completed_round,
            winner=winner,
            loser_choice=first_team_id,
        )

    async def round_result(
        self, session: AsyncSession, encounter: Encounter, round_number: int
    ) -> tuple[bool, int | None]:
        """``(decided, winner)`` for series position ``round_number``.

        ``decided`` is False while the position is pending or cancelled;
        ``winner`` is ``None`` on a DRAW, which IS decided and names nobody. The
        two are reported together because conflating them would stall the room
        on every drawn map.

        The position's ``EncounterGame`` is the authority: a parsed
        ``Match`` is an observation, and a claim nobody agreed with is not a
        result at all. "Won" is the game's own placement under the encounter's
        scoring rule, so a duel and a lobby answer it the same way.
        """
        if round_number < 1:
            return False, None
        game = next(
            (game for game in await self.games.list_games(session, encounter.id) if game.position == round_number),
            None,
        )
        if game is None or game.state != EncounterGameState.CONFIRMED:
            return False, None
        lines = (await self.games.lines_by_game(session, [game])).get(game.id) or []
        return True, winner_of(
            await self.games.rules(session, encounter),
            [
                GameLine(
                    encounter_team_id=row.encounter_team_id,
                    score=row.score,
                    placement=row.placement,
                    values=dict(row.column_values or {}),
                )
                for row in lines
            ],
        )

    # -- a corrected result's next round -----------------------------------
    async def plan_dependent_rounds(
        self,
        session: AsyncSession,
        encounter: Encounter,
        game: EncounterGame,
        results: Sequence[GameResultIn],
    ) -> DependentRounds:
        """What correcting ``game`` to ``results`` owes the rooms. Read-only.

        A result rotation opened round ``position + 1`` off the OLD result (the
        session's own rotation snapshot decides, never the config's). When the
        correction changes who opens it, the round is rebuilt -- provided nobody
        has used it yet. Once it was used (a live submission on one of its steps;
        its game confirmed, claimed or given a side) the correction refuses with
        409 ``dependent_round_started``, before anything is written: the captains
        undo that round, or the organizer resets the room, first.

        Run by the caller under the encounter lock; :meth:`apply_dependent_rounds`
        is the write.
        """
        next_round = game.position + 1
        rooms: list[PickBanSession] = []
        for kind in (PickBanKind.MAP, PickBanKind.HERO):
            pick_ban = await self.get_pick_ban_session(session, encounter.id, kind, for_update=True)
            if pick_ban is None or pick_ban.status == MapVetoSessionStatus.CANCELLED:
                continue
            pool = dict(pick_ban.pool_json or {})
            if pool.get("progressive") and pool_rotation(pool) in _RESULT_ROTATIONS:
                rooms.append(pick_ban)
        if not rooms:
            return DependentRounds(round=next_round)

        rules = await self.games.rules(session, encounter)
        participants = [team.id for team in await self.teams_of(session, encounter.id)]
        old_winner = (await self.round_result(session, encounter, game.position))[1]
        new_winner = winner_of(rules, normalize_results(results, participants, rules))
        drop: list[PickBanSession] = []
        rechoose: list[PickBanSession] = []
        for pick_ban in rooms:
            rotation = pool_rotation(dict(pick_ban.pool_json or {}))
            if rotation == FirstBanRotation.RESULT_LOSER_CHOICE:
                # The loser elects: a different winner is a different elector.
                changed = old_winner != new_winner
            else:
                changed = (
                    len(
                        {
                            engine.resolve_round_opener(
                                rotation=rotation,
                                round_number=next_round,
                                participants=participants,
                                session_opener=pick_ban.first_team_id or participants[0],
                                previous_round_winner=winner,
                                previous_round_loser_choice=None,
                            )
                            for winner in (old_winner, new_winner)
                        }
                    )
                    > 1
                )
            if not changed:
                continue
            highest = await self.highest_round_of(session, pick_ban) or 0
            if highest < next_round:
                if pick_ban.awaiting_choice and highest == game.position:
                    rechoose.append(pick_ban)
                continue
            if await self._round_touched(session, encounter, pick_ban, next_round):
                raise HTTPException(
                    status_code=409,
                    detail=[
                        ApiExc(
                            code="dependent_round_started",
                            msg=(
                                f"Game {next_round}'s pick-ban already started on the old result; "
                                "undo that round or reset the room before correcting"
                            ),
                        )
                    ],
                )
            drop.append(pick_ban)
        return DependentRounds(round=next_round, drop=tuple(drop), rechoose=tuple(rechoose))

    async def _round_touched(
        self, session: AsyncSession, encounter: Encounter, pick_ban: PickBanSession, round_number: int
    ) -> bool:
        """Whether anybody already used ``round_number`` of ``pick_ban``: a live
        submission on one of its steps, or its position's game confirmed,
        claimed or given a side. A map named on the game is not use of a hero
        round (a map room's pick IS its own round's submission)."""
        indices = {step["index"] for step in pick_ban.resolved_sequence_json or [] if step.get("round") == round_number}
        submissions = await self.submission_repo.list_by_session(session, pick_ban.id)
        if any(row.step_index in indices and row.state != pbr.VOIDED for row in submissions):
            return True
        game = next(
            (game for game in await self.games.list_games(session, encounter.id) if game.position == round_number),
            None,
        )
        if game is None:
            return False
        if game.state == EncounterGameState.CONFIRMED or (await self.games.claims_by_game(session, [game]))[game.id]:
            return True
        return any(row.starting_side is not None for row in (await self.games.lines_by_game(session, [game]))[game.id])

    async def apply_dependent_rounds(self, session: AsyncSession, plan: DependentRounds) -> tuple[PickBanKind, ...]:
        """Scrap what :meth:`plan_dependent_rounds` found, and name the kinds the
        caller must re-grow (``_sync_rounds``) once the corrected result is
        written: the dropped round re-appends with the new opener (its own
        ``round_opened`` row), and a pending choice re-raises for the new loser."""
        for pick_ban in plan.rechoose:
            pick_ban.awaiting_choice = False
            pick_ban.pending_chooser_team_id = None
        for pick_ban in plan.drop:
            sequence = list(pick_ban.resolved_sequence_json or [])
            kept = [step for step in sequence if (step.get("round") or 0) < plan.round]
            scrapped = [step["index"] for step in sequence if (step.get("round") or 0) >= plan.round]
            if scrapped:
                # Only VOIDED rows can be left on an untouched round.
                await self.submission_repo.delete_for_steps_from(
                    session, session_id=pick_ban.id, step_index=min(scrapped)
                )
            await self.entry_repo.delete_for_round(session, session_id=pick_ban.id, round=plan.round)
            pick_ban.resolved_sequence_json = kept
            # Back to "ran out of sequence": the re-append flips it to ACTIVE.
            pick_ban.status = MapVetoSessionStatus.COMPLETED
            # ``pick_ban_undo.clear_undo_request``, which imports this module: a
            # consent given against a scrapped step must not survive it.
            pick_ban.undo_requested_by_team_id = None
            pick_ban.undo_target_index = None
        await session.flush()
        return tuple(PickBanKind(pick_ban.kind) for pick_ban in (*plan.drop, *plan.rechoose))

    async def round_target(
        self, session: AsyncSession, encounter: Encounter, kind: PickBanKind, *, encounter_locked: bool = False
    ) -> int:
        """How many rounds the series currently ALLOWS this kind.

        The series' own ceiling is "confirmed positions + 1", capped by
        ``best_of`` and closed entirely once the encounter is decided: round N+1
        of a map veto opens on position N's result, which is exactly what makes
        the next map's bans wait for the map before it to be played.

        A HERO room is additionally bounded by the maps the veto has picked:
        picking map N+1 early (a decider can settle it the moment round N's bans
        end) must not hand out its hero bans before map N has a result.

        Its own method because the healer's unlocked precheck and the append
        itself must agree on the ceiling to the round -- a precheck that said
        "owed" where the append says "no" would lock the encounter forever.
        """
        standing = await self.games.standing(session, encounter)
        if standing.ended:
            return 0
        allowed = min(standing.games + 1, int(encounter.best_of))
        if kind != PickBanKind.HERO:
            return allowed
        map_config = await self.resolve_config(session, encounter, PickBanKind.MAP)
        map_session = await self.get_pick_ban_session(
            session, encounter.id, PickBanKind.MAP, for_update=encounter_locked
        )
        if (
            map_config is not None
            and has_pool(map_config)
            # A cancelled map session names no further maps, so its settled count
            # would freeze the hero rounds for the rest of a series the captains
            # now pick maps for themselves.
            and (map_session is None or map_session.status != MapVetoSessionStatus.CANCELLED)
        ):
            return min(await self.settled_map_rounds(session, encounter.id), allowed)
        return allowed

    async def round_owed(self, session: AsyncSession, encounter: Encounter, kind: PickBanKind) -> bool:
        """Whether a round is owed AND ``advance_to_next_round`` would open it.

        Deliberately as strict as the append itself: this is the healer's
        UNLOCKED precheck, and a room that owes a round the append then declines
        (its current round unfinished, the snapshot exhausted, the rotation still
        waiting on a result) would otherwise take the encounter lock on every
        single pass, forever, and change nothing.
        """
        pick_ban = await self.get_pick_ban_session(session, encounter.id, kind)
        if pick_ban is None or pick_ban.status == MapVetoSessionStatus.CANCELLED or pick_ban.awaiting_choice:
            return False
        pool = dict(pick_ban.pool_json or {})
        if not pool.get("progressive"):
            return False
        highest = await self.highest_round_of(session, pick_ban) or 0
        if highest >= await self.round_target(session, encounter, kind):
            return False
        teams = await self.teams_of(session, encounter.id)
        submissions = list(await self.submission_repo.list_by_session(session, pick_ban.id))
        if pbr.current_step(resolved_steps(pick_ban, teams), submissions) is not None:
            return False  # the round in play still has steps left to take
        next_round = highest + 1
        if next_round > encounter.best_of or round_candidates(pool, next_round) is None:
            return False
        if (
            next_round > 1
            and pool_rotation(pool) in _RESULT_ROTATIONS
            and not (await self.round_result(session, encounter, highest))[0]
        ):
            return False  # owed until the previous position is confirmed
        return True

    async def _sync_rounds(
        self,
        session: AsyncSession,
        encounter: Encounter,
        kind: PickBanKind,
        *,
        commit: bool,
        encounter_locked: bool = False,
    ) -> bool:
        """Keep one kind's rounds in lockstep with the series. Returns whether
        anything was appended.

        A MAP round N+1 opens once position N is confirmed; a HERO round N opens
        once map N is picked AND position N-1 is confirmed, because heroes are
        banned for a KNOWN map that is actually next. The
        ceiling for both is :meth:`round_target`.

        One round per call in practice — ``advance_to_next_round`` refuses to
        open round N+1 while round N is unfinished, which is exactly the loop's
        own barrier.

        WRITE-side only: there is no event for "a map just got picked", so this
        runs from the room's own writes and from the reconciler that follows
        every room commit (``room_reconcile``). The room's state READ never calls
        it -- a viewer's poll must not take the encounter lock.

        Double-checked: the unlocked read below only answers "is a round owed at
        all", and the append itself runs under the session lock. Unlocked, two
        simultaneous callers would both see the round missing and both insert
        its candidates -- the round would then offer every item twice.
        """
        pick_ban = await self.get_pick_ban_session(session, encounter.id, kind)
        if pick_ban is None or pick_ban.status == MapVetoSessionStatus.CANCELLED:
            return False
        if not dict(pick_ban.pool_json or {}).get("progressive"):
            return False
        target = await self.round_target(session, encounter, kind, encounter_locked=encounter_locked)
        if (await self.highest_round_of(session, pick_ban) or 0) >= target:
            return False
        if not encounter_locked:
            # Append/journal writes must use encounter -> session, just like
            # the action paths. Repeat the series/map ceiling after waiting:
            # a result correction or a reset may have removed the round owed.
            encounter = await self._lock_encounter(session, encounter.id)
            await session.execute(
                self.games.game_repo.select()
                .where(EncounterGame.encounter_id == encounter.id)
                .execution_options(populate_existing=True)
            )
            return await self._sync_rounds(session, encounter, kind, commit=commit, encounter_locked=True)

        pick_ban = await self.get_pick_ban_session(session, encounter.id, kind, for_update=True)
        if pick_ban is None or pick_ban.status == MapVetoSessionStatus.CANCELLED:
            return False
        changed = False
        highest = await self.highest_round_of(session, pick_ban) or 0
        while highest < target:
            decided, winner = await self.round_result(session, encounter, highest)
            try:
                await self.advance_to_next_round(
                    session, pick_ban, completed_round=highest, winner=winner, decided=decided, commit=False
                )
            except engine.RotationNeedsChoice:
                # `result_loser_choice`: the round waits for the losing captain's
                # `elect_opener` call, which resumes this same append.
                teams = await self.teams_of(session, encounter.id)
                pick_ban.awaiting_choice = True
                pick_ban.pending_chooser_team_id = next((team.id for team in teams if team.id != winner), None)
                await session.flush()
                changed = True
                break
            appended = await self.highest_round_of(session, pick_ban) or 0
            if appended <= highest:
                break  # the append declined (round unfinished, or the snapshot/series ran out)
            highest = appended
            changed = True
        if commit:
            await session.commit()
        return changed


pick_ban_session_service = PickBanSessionService()
