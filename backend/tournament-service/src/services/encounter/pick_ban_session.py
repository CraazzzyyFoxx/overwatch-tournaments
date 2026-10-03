"""Pick-ban session lifecycle: creates an encounter's room for one ``kind``
and grows it round by round.

Round 1 resolves the config's ruleset (``shared.domain.pick_ban_rules``) for
the first map of the series and creates that round's candidate entries. Round
N+1 is appended lazily by
:meth:`PickBanSessionService.advance_to_next_round` once map N's result is
known -- compiled from the session's ruleset SNAPSHOT (design D6: an organizer
editing the config mid-series must not change a running room's rules), with
the still-active bans of earlier rounds re-created as fixed ``carried``
entries (``lifetime``) and the rest of the pool filtered through the matched
phase's ``pool_filter``.

Design: docs/plans/2026-09-28-pick-ban-constructor.md §5
"""

from __future__ import annotations

from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core.enums import (
    EncounterFormat,
    EncounterGameState,
    FirstBanRotation,
    MapPickSide,
    MapPoolEntryStatus,
    MapVetoMode,
    MapVetoSessionStatus,
    PickBanKind,
)
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain import pick_ban_engine as engine
from shared.domain import pick_ban_rules as pbr
from shared.domain.pick_ban_config import has_pool, pick_config
from shared.models.catalog.gamemode import Gamemode
from shared.models.catalog.hero import Hero
from shared.models.catalog.map import Map
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.pick_ban import (
    EncounterReadiness,
    PickBanConfig,
    PickBanEntry,
    PickBanSession,
)
from shared.repository import (
    EncounterReadinessRepository,
    PickBanConfigRepository,
    PickBanEntryRepository,
    PickBanSessionRepository,
    PickBanSubmissionRepository,
)
from shared.repository.pick_ban import CONFIG_POOL_LOAD
from shared.services.bracket.usability import is_encounter_live
from src.services.encounter.games import EncounterGameService, encounter_game_service
from src.services.encounter.realtime_commit import emit_pick_ban_update
from src.services.encounter.room_journal import record_room_event
from src.services.encounter.veto_session import (
    REASON_BRACKET_PREVIEW,
    REASON_NOT_CONFIGURED,
    REASON_SLOT_COUNT_MISMATCH,
    REASON_SLOT_UNDERFILLED,
    REASON_TEAMS_UNKNOWN,
    SLOT_CANDIDATE_FLOOR,
    resolve_seeds,
)

# Session-creation blocker distinct from the ``veto_session``-derived
# REASON_* set above: neither side's captain has confirmed readiness yet.
# Not a config/team problem, so checked only once those are known-good --
# see ``both_sides_ready``/``mark_ready`` below.
REASON_NOT_READY = "not_ready"

# The hero phase of a round bans FOR a known map, so it cannot open before the
# map pick-ban has settled that round's map (design §4: both rulebooks ban
# heroes once per map of the series). Not a config problem -- it resolves on
# its own as the map phase progresses -- so it is reported separately from the
# REASON_* set above.
REASON_WAITING_MAP = "waiting_map"


def unavailable_reason_for(
    encounter: Encounter,
    kind: PickBanKind,
    config: PickBanConfig | None,
    *,
    live: bool,
    both_ready: bool,
    map_round_one_settled: bool,
) -> str:
    """Rank the blockers of one room, as a pure function of facts already read.

    Pure so a caller that loaded the facts in BULK -- the pre-game rooms
    overview, which answers dozens of encounters without re-querying each one --
    reports exactly what the room itself would report. Most specific blocker
    first: an unknown team, then a preview bracket, then the config, then
    readiness, then the map phase a hero room waits on.
    """
    if encounter.home_team_id is None or encounter.away_team_id is None:
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
    if not both_ready:
        return REASON_NOT_READY
    if kind == PickBanKind.HERO and not map_round_one_settled:
        return REASON_WAITING_MAP
    return REASON_NOT_CONFIGURED


def rounds_are_progressive(config: PickBanConfig, kind: PickBanKind) -> bool:
    """Whether this config's rounds are created one map at a time.

    Slot mode says so structurally -- one slot IS one map of the series -- and
    every hero config says so by domain: heroes are banned per map, never once
    per series (design §4). A flat ``kind=map`` config is the legacy classic
    veto, one sequence that settles the whole series' map order up front, and
    stays single-round (``PickBanEntry.round IS NULL``).
    """
    return config.mode == MapVetoMode.SLOTS or kind == PickBanKind.HERO


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


def resolved_steps(pick_ban: PickBanSession) -> list[pbr.ResolvedStep]:
    """``resolved_sequence_json`` as engine objects."""
    return pbr.resolved_steps_from_json(list(pick_ban.resolved_sequence_json or []))


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


async def load_item_groups(session: AsyncSession, kind: PickBanKind, item_ids: list[int]) -> dict[int, str | None]:
    """``{item_id: group}`` for the ``item_group``/``target_role_match`` leaves:
    a hero's class, a map's gamemode slug.

    Two flat selects rather than one join for the map kind: the projection a
    join would return is not what any repository exposes, and the second query
    only ever runs for a map room (a handful of gamemodes).
    """
    if not item_ids:
        return {}
    if kind == PickBanKind.HERO:
        rows = await session.execute(select(Hero.id, Hero.type).where(Hero.id.in_(item_ids)))
        # A bare column select can yield the stored string instead of the enum
        # member depending on the result processor -- `.value` on a str raises.
        return {row[0]: getattr(row[1], "value", row[1]) for row in rows.all()}
    maps = (await session.execute(select(Map.id, Map.gamemode_id).where(Map.id.in_(item_ids)))).all()
    gamemode_ids = sorted({row[1] for row in maps if row[1] is not None})
    slugs: dict[int, str] = {}
    if gamemode_ids:
        rows = await session.execute(select(Gamemode.id, Gamemode.slug).where(Gamemode.id.in_(gamemode_ids)))
        slugs = {row[0]: row[1] for row in rows.all()}
    return {row[0]: slugs.get(row[1]) for row in maps}


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

    async def current_round_of(self, session: AsyncSession, pick_ban: PickBanSession) -> int | None:
        """The round `pick_ban` is currently resolving (see
        ``pick_ban_engine.current_round``), or ``None`` in flat mode / once
        complete. Public wrapper so callers outside this module never need to load
        a session's entries themselves just to ask this."""
        entries = await self.entry_repo.list_by_session(session, pick_ban.id)
        return engine.current_round(list(entries))

    async def highest_round_of(self, session: AsyncSession, pick_ban: PickBanSession) -> int | None:
        """The highest round `pick_ban` has ever created entries for, or ``None``
        in flat mode. Unlike `current_round_of` (which reports the round with
        something still `AVAILABLE`, and so goes ``None`` the instant a round
        finishes), this stays truthful right through the `awaiting_choice` gap —
        exactly the round `elect_opener` needs `advance_to_next_round` to resume
        after, when nothing is `AVAILABLE` because the next round hasn't been
        created yet."""
        rounds = [row for row in await self.entry_repo.list_rounds(session, pick_ban.id) if row is not None]
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
        swallowed, or the unique ``(step, side, attempt)`` key rejects the second
        writer with a 500 instead of a turn error.

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

    async def load_config(self, session: AsyncSession, config_id: int) -> PickBanConfig | None:
        """One config by id, pool eagerly loaded.

        A `select` rather than `session.get`: loader options are ignored when the
        row is already in the identity map (which it can be, e.g. after
        `pick_ban_action` fetched it for a scalar flag), and the pool would still
        come back unloaded. ``BaseRepository.get`` is that select.
        """
        return await self.config_repo.get(session, config_id, options=CONFIG_POOL_LOAD)

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
        pool — otherwise saving a stage as a template closes every round's room
        even after maps are authored at the tournament.

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
            .options(*CONFIG_POOL_LOAD)
        )
        return pick_config(result.scalars().all(), stage_id=stage_id, round=round)

    async def _resolve_config(
        self, session: AsyncSession, encounter: Encounter, kind: PickBanKind
    ) -> PickBanConfig | None:
        """Same cascade as ``veto_session.resolve_config``, scoped by ``kind``."""
        return await self.resolve_config_at_level(
            session,
            tournament_id=encounter.tournament_id,
            kind=kind,
            stage_id=encounter.stage_id,
            round=encounter.round,
        )

    async def settled_map_rounds(self, session: AsyncSession, encounter_id: int) -> int:
        """How many maps of the series the map pick-ban has settled.

        Mode-agnostic on purpose: rounds resolve in order, so the count of decided
        entries IS the highest settled round for a slot-mode session (one pick per
        round) and for the legacy flat one (the whole order picked up front)
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
        map_config = await self._resolve_config(session, encounter, PickBanKind.MAP)
        if map_config is None or not has_pool(map_config):
            return True
        return await self.settled_map_rounds(session, encounter.id) >= round_number

    async def get_readiness(self, session: AsyncSession, encounter_id: int) -> dict[str, bool]:
        """``{"home": bool, "away": bool}`` -- whether each side's captain has
        confirmed readiness to begin this encounter's pre-game phase."""
        ready_sides = set(await self.readiness_repo.list_sides(session, encounter_id))
        return {"home": "home" in ready_sides, "away": "away" in ready_sides}

    async def both_sides_ready(self, session: AsyncSession, encounter_id: int) -> bool:
        readiness = await self.get_readiness(session, encounter_id)
        return readiness["home"] and readiness["away"]

    async def mark_ready(
        self,
        session: AsyncSession,
        encounter: Encounter,
        side: str,
        user_id: int | None,
        *,
        actor_auth_user_id: int | None = None,
        source: str = "captain",
    ) -> dict[str, bool]:
        """Idempotently record ``side``'s captain confirming readiness. Returns
        the resulting ``{"home", "away"}`` readiness map.

        ``user_id`` is the PLAYER identity stored on the row;
        ``actor_auth_user_id``/``source`` name whoever caused it for the journal
        -- an organizer forcing readiness has an auth account but no player one.

        The INSERT signals the room before it commits. It has to: until both
        sides are ready no session exists, and the room polls nothing while that
        is true -- so without the signal the OPPOSITE captain's screen sits on
        "waiting for them" until they reload. ``kind="map"`` carries it for both
        kinds: the room's single ``encounter:{id}:map-veto`` subscription
        refetches map and hero state together.
        """
        existing = await self.readiness_repo.get_for_side(session, encounter_id=encounter.id, side=side)
        if existing is None:
            session.add(EncounterReadiness(encounter_id=encounter.id, side=side, ready_user_id=user_id))
            await record_room_event(
                session,
                encounter.id,
                action="ready_marked",
                source=source,
                side=side,
                actor_auth_user_id=actor_auth_user_id,
            )
            await emit_pick_ban_update(session, encounter.id, kind="map")
            await session.commit()
        return await self.get_readiness(session, encounter.id)

    async def clear_ready(
        self, session: AsyncSession, encounter: Encounter, side: str, *, actor_auth_user_id: int | None = None
    ) -> dict[str, bool]:
        """Take ``side``'s readiness back -- the organizer's override of a
        captain who confirmed too early.

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
        await self.readiness_repo.delete_for_side(session, encounter_id=encounter.id, side=side)
        # Always ``admin``: a captain has no way to take their own readiness back.
        await record_room_event(
            session,
            encounter.id,
            action="ready_cleared",
            source="admin",
            side=side,
            actor_auth_user_id=actor_auth_user_id,
        )
        await emit_pick_ban_update(session, encounter.id, kind="map")
        await session.commit()
        return await self.get_readiness(session, encounter.id)

    async def reset_readiness(self, session: AsyncSession, encounter_id: int) -> None:
        """Clear both sides' readiness -- called whenever either team assignment
        changes (a confirmation made against one opponent must not carry over to
        a different one)."""
        # Read first so the journal records a reset that actually took something
        # back: the team-change hook runs on every bracket propagation, and most
        # of them touch an encounter nobody has confirmed readiness for yet.
        had_readiness = bool(await self.readiness_repo.list_sides(session, encounter_id))
        await self.readiness_repo.delete_for_encounter(session, encounter_id)
        if had_readiness:
            await record_room_event(session, encounter_id, action="readiness_reset", source="system")

    async def unavailable_reason(self, session: AsyncSession, encounter: Encounter, kind: PickBanKind) -> str:
        """Why ``ensure_pick_ban_session`` returned ``None`` for this
        encounter/kind. Mirrors ``veto_session.unavailable_reason``'s contract
        (same REASON_* string set, re-derived rather than handed over -- see that
        function's docstring for the rationale) against ``PickBanConfig`` instead
        of the legacy ``MapVetoConfig``, and the same slot-floor check
        ``ensure_pick_ban_session`` itself applies, so the two cannot diverge.

        The ranking itself is :func:`unavailable_reason_for`; this gathers the
        facts that answer it. The cheap ones are read unconditionally -- this
        runs on a room that cannot open, and a second copy of the ranking would
        cost correctness. The map-phase fact is read only when it can change
        the answer: asking the map session for a hero room that is blocked on
        its teams or its readiness anyway would be a query with no effect.
        """
        config = await self._resolve_config(session, encounter, kind)
        live = await is_encounter_live(session, encounter)
        both_ready = await self.both_sides_ready(session, encounter.id)

        def rank(map_round_one_settled: bool) -> str:
            return unavailable_reason_for(
                encounter,
                kind,
                config,
                live=live,
                both_ready=both_ready,
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

        Round 1 resolves the cascade-resolved config the way it always did (same
        seed resolution, same slot validation), but through the ruleset: the
        phase whose ``when`` matches map 1 supplies both the steps and the
        ``pool_filter`` its candidates must pass. The parsed ruleset is
        SNAPSHOTTED onto the session (design D6) -- every later round compiles
        from that copy, never from the config's live document.

        When the rounds are progressive (``rounds_are_progressive``) the session
        gets round 1 and nothing else, and every later round is appended one at a
        time by ``advance_to_next_round`` as the series is played -- so round 2's
        bans cannot be taken before round 1's map has been played. A flat
        ``kind=map`` config is untouched: one round (``round IS NULL``) whose
        sequence settles the whole series, because that IS the classic veto.
        """
        return await self._ensure_pick_ban_session(session, encounter, kind, commit=commit)

    async def _lock_encounter(self, session: AsyncSession, encounter_id: int) -> Encounter:
        """Room mutation lock; discard the pre-lock encounter snapshot."""
        result = await session.execute(
            select(Encounter)
            .where(Encounter.id == encounter_id)
            .options(selectinload(Encounter.stage))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        encounter = result.unique().scalars().first()
        if encounter is None:
            raise HTTPException(status_code=404, detail="Encounter not found")
        return encounter

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
        # Not an error: this is the "is there a veto here" query the room polls,
        # and a lobby has no two sides to veto between.
        if encounter.format == EncounterFormat.FFA:
            return None
        if encounter.home_team_id is None or encounter.away_team_id is None:
            return None
        if not await is_encounter_live(session, encounter):
            return None
        config = await self._resolve_config(session, encounter, kind)
        if config is None or not has_pool(config):
            return None

        slots: list[list[int]] | None = None
        slot_reserves: dict[str, int] | None = None
        if config.mode == MapVetoMode.SLOTS:
            if not config.slots or encounter.best_of > len(config.slots):
                return None
            ordered = sorted(config.slots, key=lambda s: s.position)[: encounter.best_of]
            for slot in ordered:
                if len(slot.items) < SLOT_CANDIDATE_FLOOR:
                    return None
            slots = [[item.item_id for item in slot.items] for slot in ordered]
            # String-keyed by 1-based slot position, reserve-less slots omitted --
            # mirrors veto_session.slot_reserves exactly (Decision 18: the room
            # reads this snapshot off the session, never the config, so a later
            # config edit cannot move a running session's reserve labels).
            slot_reserves = {
                str(slot.position): slot.reserve_item_id for slot in ordered if slot.reserve_item_id is not None
            }

        if not await self.both_sides_ready(session, encounter.id):
            return None

        # Heroes are banned FOR a map, so a hero session cannot open before the map
        # pick-ban has settled round 1's map. `sync_hero_rounds` keeps every later
        # hero round behind the same gate.
        if kind == PickBanKind.HERO and not await self.map_round_settled(session, encounter, 1):
            return None
        if not encounter_locked:
            # A missing session has no row to lock. Lock its encounter only once
            # creation is actually owed, then repeat ALL gates and the existence
            # check against the refreshed row. Existing/unavailable rooms stay
            # unlocked; initialization and readiness/team resets serialize.
            encounter = await self._lock_encounter(session, encounter.id)
            return await self._ensure_pick_ban_session(session, encounter, kind, commit=commit, encounter_locked=True)

        pool_size = sum(len(s) for s in slots) if slots is not None else len(config.items)
        seeds = await resolve_seeds(session, encounter)
        now = datetime.now(UTC)
        flat_item_ids = [item.item_id for item in sorted(config.items, key=lambda item: item.sort_order)]
        progressive = rounds_are_progressive(config, kind)
        ruleset = parse_ruleset(config.ruleset_json)
        # Round 1's candidates: its slot in slot mode, the whole configured pool in
        # a (per-round) flat one.
        round_one_item_ids = slots[0] if slots is not None else flat_item_ids
        round_number = 1 if progressive else None

        # Round 1 has no history, so only the absolute leaves of `pool_filter`
        # (`item_in`/`item_group`) can exclude anything here -- but they can, and
        # a candidate the phase refuses must never become an entry.
        groups = await load_item_groups(session, kind, round_one_item_ids)
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
            opener=seeds.first_side.value,
            best_of=encounter.best_of,
            pool_size=pool_size,
            candidate_count=len(candidates),
        )

        pick_ban = PickBanSession(
            encounter_id=encounter.id,
            kind=kind,
            config_id=config.id,
            first_side=seeds.first_side,
            seed_source=seeds.seed_source,
            home_seed=seeds.home_seed,
            away_seed=seeds.away_seed,
            resolved_sequence_json=[step.to_json() for step in steps],
            ruleset_json=ruleset.to_json(),
            slot_reserves_json=slot_reserves,
            # A round whose phase resolved to no steps is already settled; the
            # first read then advances straight to the next one instead of
            # hanging on a cursor that can never move.
            status=MapVetoSessionStatus.ACTIVE if steps else MapVetoSessionStatus.COMPLETED,
            awaiting_choice=False,
            started_at=now,
            current_step_started_at=now,
        )
        session.add(pick_ban)

        for offset, item_id in enumerate(candidates):
            session.add(
                PickBanEntry(
                    session=pick_ban,
                    item_id=item_id,
                    order=offset,
                    round=round_number,
                    status=MapPoolEntryStatus.AVAILABLE,
                )
            )

        await record_room_event(
            session,
            encounter.id,
            action="session_opened",
            source="system",
            kind=kind.value,
            data={
                "first_side": str(getattr(seeds.first_side, "value", seeds.first_side)),
                "seed_source": str(getattr(seeds.seed_source, "value", seeds.seed_source)),
                "home_seed": seeds.home_seed,
                "away_seed": seeds.away_seed,
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

        ``source`` defaults to the organizer who normally asks for this; the
        team-change hook passes ``system``, having no human behind it."""
        if kind == PickBanKind.MAP:
            await self.games.cancel_games(
                session,
                encounter,
                await self.games.list_games(session, encounter.id),
                actor_user_id=None,
                reason="map_session_reset",
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
        # session (same reasoning as veto_session.reset_veto_session).
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
        """Team-assignment hook (bracket propagation / admin encounter edits).
        Generalizes ``veto_session.sync_veto_session_after_team_change``.

        Called after an encounter's home/away team ids changed. Both teams now
        set with no session -> ensure one. Session already exists -> the snapshot
        is stale, reset it -- UNLESS a game of the series is already CONFIRMED
        (a map really was played; an admin untangles that by hand, spec §6.5).
        Runs inside the caller's transaction (no commit).

        The series SCORE is not consulted: a cascade reset cancels the old
        pairing's games before this hook runs, so nothing confirmed survives it,
        and a drawn first map — which scores 0:0 — is still a played map that
        must not be silently re-vetoed.
        """
        pick_ban = await self.get_pick_ban_session(session, encounter.id, kind)
        if pick_ban is None:
            if encounter.home_team_id is not None and encounter.away_team_id is not None:
                await self.ensure_pick_ban_session(session, encounter, kind, commit=False)
            return
        games = await self.games.list_games(session, encounter.id)
        if any(game.state == EncounterGameState.CONFIRMED for game in games):
            return
        await self.reset_pick_ban_session(session, encounter, kind, commit=False, source="system")

    async def sync_all_pick_ban_sessions_after_team_change(self, session: AsyncSession, encounter: Encounter) -> None:
        """``sync_pick_ban_session_after_team_change`` for every kind, in the
        legacy two-arg shape (``session``, ``encounter``) that
        ``admin/encounter.py``, ``challonge/sync.py`` and
        ``encounter/finalize.py``'s ``post_advance`` callback all call. Replaces
        ``veto_session.sync_veto_session_after_team_change`` at all three call
        sites: map's session/entry storage moved to ``PickBanSession``/
        ``PickBanEntry``, so the legacy hook would now create/reset the wrong
        (dead) tables. Also gives hero bans the SAME team-change resilience map
        veto always had -- a pre-existing gap, since nothing called the legacy
        hook for kind=hero before the generic engine existed. Also clears
        ``EncounterReadiness`` -- a confirmation made against one opponent must
        not carry over once the assignment changes."""
        await self.reset_readiness(session, encounter.id)
        for kind in (PickBanKind.MAP, PickBanKind.HERO):
            await self.sync_pick_ban_session_after_team_change(session, encounter, kind)

    async def advance_to_next_round(
        self,
        session: AsyncSession,
        pick_ban: PickBanSession,
        *,
        completed_round: int,
        outcome: engine.MapOutcome | None,
        loser_choice: MapPickSide | None = None,
        commit: bool = True,
    ) -> PickBanSession:
        """Append the round after ``completed_round``: its resolved steps, the
        earlier rounds' still-active bans as carried entries, and its candidates.

        This is the barrier between two maps of a series (design Decision 5). It
        is a no-op, returning ``pick_ban`` unchanged, unless all of:

        - the session's rounds are progressive (``rounds_are_progressive``) — a
          flat ``kind=map`` veto settles the whole series at once and has no later
          round to open;
        - the round currently in play is fully resolved — a new round is never
          stacked on top of an unfinished one;
        - the next round has not been appended already (idempotent re-entry);
        - the config still describes that round (slot count) and the series still
          has that many maps (``best_of``).

        The steps come from the session's ruleset SNAPSHOT, not the config's live
        one (D6); the POOL is still read from the config, which is what lets an
        organizer fix a mis-typed slot mid-series.

        ``outcome`` is the previous position's CONFIRMED result (``"home"``,
        ``"away"`` or ``"draw"``), or ``None`` while it has none. A drawn map
        names no winner, so a result-dependent rotation falls back to the
        session's established opener (Task 2's ``resolve_round_opener``); an
        undecided one simply owes the round, which is appended later, once the
        result lands — opening it now would have to invent an opener.

        Raises ``pick_ban_engine.RotationNeedsChoice`` when the rotation is
        ``result_loser_choice`` and ``loser_choice`` was not supplied — the caller
        must catch this, set ``awaiting_choice=True`` and wait for an explicit
        ``elect_opener`` call instead of resolving a side here.

        Takes the session lock itself rather than trusting its caller: it is
        reached from a state read, from a map result and from ``elect_opener``, and
        the idempotency check below ("has round N+1 already been appended") is a
        read the appending INSERT depends on. Two unlocked appenders both passed it
        and both wrote the round's candidates.
        """
        locked = await self.lock_pick_ban_session(session, pick_ban)
        if locked is None:
            return pick_ban  # a concurrent reset dropped the session
        pick_ban = locked
        # `populate_existing` is load-bearing: this same session may have read
        # these entries before taking the lock above, and the identity map would
        # otherwise serve that pre-lock snapshot back.
        entries = list(await self.entry_repo.list_by_session(session, pick_ban.id, populate_existing=True))

        config = await self.load_config(session, pick_ban.config_id) if pick_ban.config_id else None
        if config is None:
            # `PickBanSession.config_id` is `ondelete=SET NULL`, so a config deleted
            # mid-series leaves a session that can never open another round. Declining
            # silently froze the room on a finished round with nothing to click and
            # nothing on screen naming why; a flat (round-less) session is genuinely
            # done and has no later round to owe, so it still just returns.
            if any(entry.round is not None for entry in entries):
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"The {pick_ban.kind} pick-ban config this session was created from no longer "
                        "exists, so round "
                        f"{completed_round + 1} cannot be opened -- re-create the config, then reset the session."
                    ),
                )
            return pick_ban
        if not rounds_are_progressive(config, pick_ban.kind):
            return pick_ban

        steps = resolved_steps(pick_ban)
        submissions = list(await self.submission_repo.list_by_session(session, pick_ban.id, populate_existing=True))
        if pbr.current_step(steps, submissions) is not None:
            return pick_ban  # the round in play still has steps left to take

        next_round = completed_round + 1
        if any(entry.round == next_round for entry in entries):
            return pick_ban  # already appended (idempotent re-entry)

        encounter = await session.get(Encounter, pick_ban.encounter_id)
        if encounter is None:
            return pick_ban

        if config.mode == MapVetoMode.SLOTS:
            # The bracket owns series length, so the config's tail beyond `best_of`
            # is out of play (same rule `ensure_pick_ban_session` applies).
            ordered_slots = sorted(config.slots, key=lambda s: s.position)[: encounter.best_of]
            if next_round > len(ordered_slots):
                return pick_ban  # series is shorter than the config's slot count
            candidate_item_ids = [item.item_id for item in ordered_slots[next_round - 1].items]
        else:
            if next_round > encounter.best_of:
                return pick_ban  # every map of the series already has its round
            candidate_item_ids = [item.item_id for item in sorted(config.items, key=lambda item: item.sort_order)]

        rotation = config.first_ban_rotation
        if (
            outcome is None
            and next_round > 1
            and rotation
            in (
                FirstBanRotation.RESULT_WINNER_FIRST,
                FirstBanRotation.RESULT_LOSER_FIRST,
                FirstBanRotation.RESULT_LOSER_CHOICE,
            )
        ):
            return pick_ban  # the round is owed until the previous position is confirmed
        opener = engine.resolve_round_opener(
            rotation=rotation,
            round_number=next_round,
            session_first_side=pick_ban.first_side or MapPickSide.HOME.value,
            previous_round_outcome=outcome,
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

        groups = await load_item_groups(session, PickBanKind(pick_ban.kind), candidate_item_ids)
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
            opener=str(getattr(opener, "value", opener)),
            prev_outcome=outcome,
            best_of=encounter.best_of,
            pool_size=len(candidate_item_ids),
            candidate_count=len(candidates),
        )
        if pick_ban.kind == PickBanKind.MAP:
            # Map rounds must END on a decided map, so a round that cannot spend
            # its steps is a config error the organizer has to see NOW, at round
            # creation, not as an opaque stall on the room's next read. A hero
            # round has no such floor: it leaves the unbanned pool playable, and
            # `effective_min` already caps a lock against what is left.
            if config.mode == MapVetoMode.SLOTS and len(candidates) < SLOT_CANDIDATE_FLOOR:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Round {next_round} of the {pick_ban.kind} pick-ban has only {len(candidates)} "
                        f"candidate(s) left after the phase's pool filter (needs >= {SLOT_CANDIDATE_FLOOR}) "
                        "-- fix this tournament's pick-ban config (slot candidates or pool_filter)."
                    ),
                )
            needed = sum(step.count * max(len(step.sides), 1) for step in new_steps)
            if len(candidates) < needed:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        f"Round {next_round} of the {pick_ban.kind} pick-ban has {len(candidates)} "
                        f"candidate(s) for {needed} item(s) of steps -- fix this tournament's pick-ban config "
                        "(pool size, step counts or pool_filter)."
                    ),
                )

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
        pick_ban.pending_loser_side = None
        pick_ban.current_step_started_at = step_clock(pick_ban)
        if pick_ban.status == MapVetoSessionStatus.COMPLETED and new_steps:
            pick_ban.status = MapVetoSessionStatus.ACTIVE

        base_order = next_round * 1000  # generous per-round spacing; order is a display/tiebreak field only
        for offset, item_id in enumerate(candidates):
            session.add(
                PickBanEntry(
                    session=pick_ban,
                    item_id=item_id,
                    order=base_order + offset,
                    round=next_round,
                    status=MapPoolEntryStatus.AVAILABLE,
                )
            )
        for offset, ban in enumerate(carried, start=len(candidates)):
            session.add(
                PickBanEntry(
                    session=pick_ban,
                    item_id=ban.item_id,
                    order=base_order + offset,
                    round=next_round,
                    status=MapPoolEntryStatus.BANNED,
                    picked_by=ban.side,
                    carried_from_round=ban.from_round,
                )
            )

        await record_room_event(
            session,
            pick_ban.encounter_id,
            action="round_opened",
            source="system",
            kind=str(pick_ban.kind),
            data={"round": next_round, "first_side": str(getattr(opener, "value", opener))},
        )

        await emit_pick_ban_update(session, pick_ban.encounter_id, kind=str(pick_ban.kind))
        if commit:
            await session.commit()
        else:
            await session.flush()
        return pick_ban

    async def elect_round_opener(
        self,
        session: AsyncSession,
        pick_ban: PickBanSession,
        *,
        first_side: str,
        acting_side: str | None,
        actor_auth_user_id: int | None = None,
    ) -> PickBanSession:
        """Resolve an ``awaiting_choice`` round by naming who opens it, then append
        it (``advance_to_next_round`` with the choice supplied).

        ``acting_side`` is the captain making the call. ``None`` is the ADMIN
        override: `result_loser_choice` is the one rotation whose next round cannot
        open without a human, so an unreachable losing captain would otherwise
        freeze the room with nothing on screen to act on and nothing but a
        session-wiping reset to reach for (design §7's named escape hatch).
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
        if acting_side is not None:
            # A pause freezes the captains, never the organizer override below.
            assert_not_paused(pick_ban)
            # Only the loser of the round that triggered the choice may elect --
            # otherwise either captain could dictate who opens the next round.
            if acting_side != pick_ban.pending_loser_side:
                raise HTTPException(
                    status_code=403, detail="Only the losing captain may choose who opens the next round"
                )
        # The side that did NOT lose is the outcome this rotation was suspended
        # on; a draw never suspends it (`resolve_round_opener` falls back).
        outcome = (
            MapPickSide.AWAY.value if pick_ban.pending_loser_side == MapPickSide.HOME.value else MapPickSide.HOME.value
        )
        choice = MapPickSide(first_side)
        pick_ban.first_side = choice
        await record_room_event(
            session,
            pick_ban.encounter_id,
            action="opener_elected",
            # ``acting_side is None`` IS the admin override -- see the docstring.
            source="captain" if acting_side is not None else "admin",
            kind=str(pick_ban.kind),
            side=acting_side,
            actor_auth_user_id=actor_auth_user_id,
            data={"round": (await self.highest_round_of(session, pick_ban) or 0) + 1, "first_side": first_side},
        )
        return await self.advance_to_next_round(
            session,
            pick_ban,
            completed_round=await self.highest_round_of(session, pick_ban) or 0,
            outcome=outcome,
            loser_choice=choice,
        )

    async def map_round_outcome(
        self, session: AsyncSession, encounter: Encounter, round_number: int
    ) -> engine.MapOutcome | None:
        """Confirmed outcome of series position ``round_number``; None while pending.

        The position's ``EncounterGame`` is the authority (spec §5.1): a parsed
        ``Match`` is an observation, and a claim nobody agreed with is not a
        result at all.
        """
        if round_number < 1:
            return None
        game = next(
            (game for game in await self.games.list_games(session, encounter.id) if game.position == round_number),
            None,
        )
        if game is None or game.state != EncounterGameState.CONFIRMED:
            return None
        return engine.map_outcome(game.accepted_home_score, game.accepted_away_score)

    async def sync_hero_rounds(self, session: AsyncSession, encounter: Encounter, *, commit: bool = True) -> None:
        """Keep the hero session's rounds in lockstep with the series: hero round
        N opens once map N is picked AND position N-1 is confirmed, because
        heroes are banned for a KNOWN map that is actually next (design §4, spec
        V03).

        With a map pool the ceiling is the lower of "maps the veto has picked"
        and "confirmed positions + 1": picking map N+1 early (a decider can
        settle it the moment round N's bans end) must not hand out its hero bans
        before map N has a result. In freeplay there is no veto to bound it, so
        the confirmed count alone does; a complete series opens nothing.

        Lazy and read-triggered, like the room's other self-healing steps
        (``auto_complete_decider``/``auto_resolve_timeout``): there is no event for
        "a map just got picked", so the hero session catches up the next time
        anyone reads or acts on it. One round per call in practice —
        ``advance_to_next_round`` refuses to open round N+1 while round N is
        unfinished, which is exactly the loop's own barrier.

        Double-checked like the room's other self-healing steps: the unlocked read
        below only answers "is a round owed at all", and the append itself runs
        under the session lock. Unlocked, two simultaneous readers both saw the
        round missing and both inserted its candidates — the round then offered
        every hero twice.
        """
        await self._sync_hero_rounds(session, encounter, commit=commit)

    async def _sync_hero_rounds(
        self,
        session: AsyncSession,
        encounter: Encounter,
        *,
        commit: bool,
        encounter_locked: bool = False,
    ) -> None:
        hero = await self.get_pick_ban_session(session, encounter.id, PickBanKind.HERO)
        if hero is None or hero.status == MapVetoSessionStatus.CANCELLED:
            return
        games = await self.games.list_games(session, encounter.id)
        score = self.games.live_score(games)
        if engine.series_complete(score, encounter.best_of):
            return
        confirmed = score.played
        map_config = await self._resolve_config(session, encounter, PickBanKind.MAP)
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
            target = min(await self.settled_map_rounds(session, encounter.id), confirmed + 1, int(encounter.best_of))
        else:
            target = min(confirmed + 1, int(encounter.best_of))
        if (await self.highest_round_of(session, hero) or 0) >= target:
            return
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
            return await self._sync_hero_rounds(session, encounter, commit=commit, encounter_locked=True)

        hero = await self.get_pick_ban_session(session, encounter.id, PickBanKind.HERO, for_update=True)
        if hero is None or hero.status == MapVetoSessionStatus.CANCELLED:
            return
        highest = await self.highest_round_of(session, hero) or 0
        while highest < target:
            outcome = await self.map_round_outcome(session, encounter, highest)
            try:
                await self.advance_to_next_round(session, hero, completed_round=highest, outcome=outcome, commit=False)
            except engine.RotationNeedsChoice:
                # `result_loser_choice`: the round waits for the losing captain's
                # `elect_opener` call, which resumes this same append.
                hero.awaiting_choice = True
                hero.pending_loser_side = (
                    MapPickSide.AWAY.value if outcome == MapPickSide.HOME.value else MapPickSide.HOME.value
                )
                await session.flush()
                break
            appended = await self.highest_round_of(session, hero) or 0
            if appended <= highest:
                break  # the append declined (round unfinished, or the config/series ran out)
            highest = appended
        if commit:
            await session.commit()


pick_ban_session_service = PickBanSessionService()
