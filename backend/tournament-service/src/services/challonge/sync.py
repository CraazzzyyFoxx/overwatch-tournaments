"""Bidirectional Challonge sync engine.

Import: Challonge -> Local (upsert encounters from Challonge matches)
Export: Local -> Challonge (push encounter results to Challonge)
Auto-push: triggered when encounter result_status becomes 'confirmed'

Four classes, split by responsibility: ``ChallongeSyncLogService`` owns the
``challonge_sync_log`` audit trail, ``ChallongeStructureService`` creates the
local stage/group/stage-item/stage-input rows a Challonge bracket implies,
``ChallongeMappingService`` owns source discovery and the Challonge-id <-> local-id
mapping tables, and ``ChallongeSyncService`` — the exported ``sync_service`` — is
the public orchestration (import, export, push, auto-sync). Everything pure
(the value dataclasses, score parsing, name normalization, the loaded-collection
probes) stays module-level.
"""

import asyncio
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from loguru import logger
from redis import asyncio as redis_async
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_naming import build_encounter_name
from shared.domain.encounter_scoring import WINS_END_FORMULA
from shared.repository import (
    BracketEncounterRepository,
    ChallongeMatchMappingRepository,
    ChallongeParticipantMappingRepository,
    ChallongeSourceRepository,
    ChallongeSyncLogRepository,
    EncounterLinkRepository,
    EncounterRepository,
    ScoringRuleRepository,
    StageItemInputRepository,
    StageItemRepository,
    StageRepository,
    TeamRepository,
    TournamentRepository,
)
from shared.services.challonge_refs import resolve_encounter_challonge
from shared.services.distributed_lock import DistributedLockUnavailable, distributed_lock
from shared.services.encounter.events import enqueue_encounter_completed
from shared.services.encounter.participants import active_teams, place_team, vacate_slot
from shared.services.encounter.result import apply_result, lock_encounter
from shared.services.realtime import Resource
from src import schemas
from src.clients.challonge import challonge_client
from src.core import config, db
from src.services.challonge.stage_refs import StageRefs, resolve_stage_refs_from_group
from src.services.notifications.lifecycle import advance_and_announce, after_encounter_teams_changed
from src.services.team.service import team_service
from src.services.tournament.events import (
    RESULT_RESOURCES,
    STRUCTURE_RESOURCES,
    enqueue_tournament_recalculation,
    publish_tournament_invalidation,
)

_AMBIGUOUS = -1
_SCORE_RE = re.compile(r"\s*(-?\d+)\s*-\s*(-?\d+)")


@dataclass(frozen=True)
class _ImportSource:
    challonge_id: int
    source_id: int | None = None
    source_type: str = "tournament"
    stage: models.Stage | None = None
    stage_item_id: int | None = None
    slug: str | None = None


@dataclass(frozen=True)
class _SourceFetch:
    matches: list[schemas.ChallongeMatch]
    participants: list[schemas.ChallongeParticipant]


@dataclass
class _TeamLookup:
    by_source_key: dict[tuple[int, int], int]
    by_key: dict[tuple[int | None, int], int]
    teams_by_id: dict[int, models.Team]

    def resolve(
        self,
        source: _ImportSource,
        group_id: int | None,
        challonge_id: int | None,
    ) -> int | None:
        if challonge_id is None:
            return None
        if (tid := self.by_source_key.get((_source_lookup_key(source), challonge_id))) is not None:
            return tid
        if (tid := self.by_key.get((group_id, challonge_id))) is not None:
            return tid
        if (tid := self.by_key.get((None, challonge_id))) is not None:
            return tid
        candidates = {tid for (gid, cid), tid in self.by_key.items() if cid == challonge_id}
        return next(iter(candidates)) if len(candidates) == 1 else None


@dataclass
class _MatchLookup:
    by_source_key: dict[tuple[int, int], models.Encounter]
    by_challonge_id: dict[int, models.Encounter]
    mapped_keys: set[tuple[int, int]]
    # Encounters that already occupy a bracket slot (same stage + round + team
    # pair) but carry no ``challonge_match_mapping`` yet -- a bracket generated
    # locally (``StageService.generate_encounters``) before this source was
    # imported. Popped the first time a Challonge match resolves to that slot, so
    # import adopts and links the existing row instead of creating a duplicate.
    unlinked_by_slot: dict[tuple[int | None, int, frozenset[int]], models.Encounter]

    def get(self, source: _ImportSource, challonge_match_id: int) -> models.Encounter | None:
        if (encounter := self.by_source_key.get((_source_lookup_key(source), challonge_match_id))) is not None:
            return encounter
        return self.by_challonge_id.get(challonge_match_id)

    def claim_unlinked(
        self, stage_id: int | None, round_number: int, team_ids: frozenset[int]
    ) -> models.Encounter | None:
        return self.unlinked_by_slot.pop((stage_id, round_number, team_ids), None)

    def set(
        self,
        source: _ImportSource,
        challonge_match_id: int,
        encounter: models.Encounter,
    ) -> None:
        self.by_source_key[(_source_lookup_key(source), challonge_match_id)] = encounter
        self.by_challonge_id[challonge_match_id] = encounter


@dataclass(frozen=True)
class _UpsertResult:
    action: str
    encounter: models.Encounter | None = None
    conflict_type: str | None = None
    # True when THIS upsert moved the encounter into COMPLETED, so import_tournament
    # emits EncounterCompletedEvent (achievement/MVP recalculation) for it.
    newly_completed: bool = False
    before: dict | None = None
    after: dict | None = None
    error: str | None = None
    # The Challonge participant ids that have no local team mapped, when
    # ``action == "error"`` for that reason. Recorded structurally alongside the
    # human message so the admin UI can group "these N participants need mapping"
    # out of one failed row per match, instead of parsing the message back apart.
    missing_participant_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class _UpsertPlan:
    """What ``_plan_upsert`` derived from Challonge for a match that will write. ``encounter`` None means the match
    creates one; ``after`` is the existing encounter's target state. The local state the write is judged on (seats,
    position, result) is re-read by ``_apply_upsert`` under the encounter's row lock, never taken from the plan."""

    encounter: models.Encounter | None
    team_ids: tuple[int | None, int | None]
    scores: tuple[int, int]
    status: enums.EncounterStatus
    refs: StageRefs
    names: dict[int, str]
    teams_mapped: bool
    after: dict | None = None


@dataclass(frozen=True)
class _ChallongeLinkSpec:
    """One Challonge prereq edge, in the encounter layer's terms.

    Challonge's "player1/player2 comes from the winner/loser of match X" is a
    PLACE in that match feeding a SEAT of this one: ``source_position`` 1 is the
    winner and 2 the loser, ``target_slot`` 1 is player1 and 2 player2.
    """

    source_key: int
    source_challonge_id: int
    target_challonge_id: int
    source_position: int
    target_slot: int


SYNC_LOCK_TTL_SECONDS = 5 * 60
#: How long an admin's import or export waits for a run already holding the lock before answering 409.
ADMIN_LOCK_WAIT_SECONDS = 3
#: ``challonge_sync_log`` rows older than this go in the daily purge.
SYNC_LOG_RETENTION = timedelta(days=30)
SYNC_LOG_PURGE_BATCH = 5000

# "Active" = matches are in play.
ACTIVE_TOURNAMENT_STATUSES = (
    enums.TournamentStatus.LIVE,
    enums.TournamentStatus.PLAYOFFS,
)

_redis_client: redis_async.Redis | None = None


def _source_lookup_key(source: _ImportSource) -> int:
    return source.source_id if source.source_id is not None else -source.challonge_id


async def _get_redis() -> redis_async.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_async.from_url(str(config.settings.redis_url), decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    global _redis_client
    if _redis_client is None:
        return
    await _redis_client.aclose()
    _redis_client = None


@asynccontextmanager
async def _sync_job_lock(tournament_id: int, direction: str, *, wait_seconds: float) -> AsyncIterator[str]:
    """The per-tournament, per-direction sync lock, renewed while held; contention is a 409."""
    redis = await _get_redis()
    key = f"challonge:sync:{tournament_id}:{direction}"
    try:
        async with distributed_lock(
            redis, key, ttl_seconds=SYNC_LOCK_TTL_SECONDS, acquire_timeout_seconds=wait_seconds
        ) as token:
            yield token.value
    except DistributedLockUnavailable as exc:
        raise HTTPException(
            status_code=409, detail=f"A Challonge {direction} of this tournament is already running"
        ) from exc


def _encounter_status_from_challonge(state: str) -> enums.EncounterStatus:
    if state == "complete":
        return enums.EncounterStatus.COMPLETED
    if state == "pending":
        return enums.EncounterStatus.PENDING
    return enums.EncounterStatus.OPEN


def _parse_scores(scores_csv: str | None) -> tuple[int, int]:
    """Series score from a Challonge ``scores_csv``.

    Challonge sends one pair per set ("0-1,1-0,2-1"), so a single pair is the
    series score itself while several pairs are per-set results that have to be
    reduced to sets won. Drawn sets and pairs carrying a negative number
    (Challonge's forfeit encoding) count for neither side.
    """
    pairs = [(int(m.group(1)), int(m.group(2))) for m in _SCORE_RE.finditer(scores_csv or "")]
    if not pairs:
        return 0, 0
    if len(pairs) == 1:
        return pairs[0]
    home = sum(1 for a, b in pairs if a >= 0 and b >= 0 and a > b)
    away = sum(1 for a, b in pairs if a >= 0 and b >= 0 and b > a)
    return home, away


def _default_stage_item_id(
    stage: models.Stage | None,
    match: schemas.ChallongeMatch,
) -> int | None:
    """Return a stage_item_id hint from already-loaded items.

    Returns None (safely) if items are not loaded — the async fallback in
    resolve_stage_refs_from_group will pick the item via a DB query instead.
    """
    if stage is None:
        return None

    try:
        if "items" in sa_inspect(stage).unloaded:
            return None
    except Exception:
        pass

    items = sorted(stage.items or [], key=lambda item: (item.order, item.id))
    if not items:
        return None

    if stage.stage_type == enums.StageType.DOUBLE_ELIMINATION and match.round < 0:
        lower_item = next(
            (item for item in items if item.type == enums.StageItemType.BRACKET_LOWER),
            None,
        )
        if lower_item is not None:
            return lower_item.id

    return items[0].id


def _first_loaded_stage_item_id(stage: models.Stage | None) -> int | None:
    if stage is None:
        return None
    try:
        items = list(stage.items or [])
    except Exception:
        return None
    if not items:
        return None
    return sorted(items, key=lambda item: (item.order, item.id))[0].id


def _next_stage_order(tournament: models.Tournament) -> int:
    orders = [int(getattr(stage, "order", 0) or 0) for stage in (tournament.stages or [])]
    return max(orders, default=-1) + 1


def _playoff_stage_type(matches: list[schemas.ChallongeMatch]) -> enums.StageType:
    if any(match.round < 0 for match in matches):
        return enums.StageType.DOUBLE_ELIMINATION
    return enums.StageType.SINGLE_ELIMINATION


def _stage_item_type_for_stage(stage_type: enums.StageType) -> enums.StageItemType:
    if stage_type == enums.StageType.ROUND_ROBIN:
        return enums.StageItemType.GROUP
    return enums.StageItemType.SINGLE_BRACKET


def _append_once(collection: list | None, item) -> None:
    if collection is None:
        return
    if item not in collection:
        collection.append(item)


def _loaded_collection(obj, attr: str) -> list | None:
    try:
        if attr in sa_inspect(obj).unloaded:
            return None
    except Exception:
        pass
    try:
        value = getattr(obj, attr)
    except Exception:
        return None
    return list(value or [])


def _find_loaded_stage_item(
    tournament: models.Tournament,
    stage_item_id: int,
) -> tuple[models.Stage | None, models.StageItem | None]:
    for stage in _loaded_collection(tournament, "stages") or []:
        for item in _loaded_collection(stage, "items") or []:
            if item.id == stage_item_id:
                return stage, item
    return None, None


def _group_names_for_challonge_ids(group_ids: set[int]) -> dict[int, str]:
    names: dict[int, str] = {}
    for index, group_id in enumerate(sorted(group_ids), start=1):
        codepoint = 64 + index
        names[group_id] = chr(codepoint) if codepoint <= 90 else f"Group {index}"
    return names


def _stage_for_challonge_group(tournament: models.Tournament, challonge_group_id: int) -> models.Stage | None:
    """Find the stage that owns a Challonge group, by ``Stage.challonge_group_id``.

    That column is the only link. None on the first import of a grouped bracket,
    before any stage carries the marker -- the caller then creates the group stage.
    """
    for stage in tournament.stages or []:
        if stage.challonge_group_id == challonge_group_id:
            return stage
    return None


def _find_playoff_stage(tournament: models.Tournament) -> models.Stage | None:
    playoffs = [
        stage
        for stage in tournament.stages or []
        if stage.stage_type in (enums.StageType.SINGLE_ELIMINATION, enums.StageType.DOUBLE_ELIMINATION)
    ]
    return playoffs[0] if len(playoffs) == 1 else None


def _resolve_group_for_match(
    tournament: models.Tournament,
    source: _ImportSource,
    match: schemas.ChallongeMatch,
) -> models.Stage | None:
    if source.stage is not None:
        return source.stage
    if match.group_id is not None:
        return _stage_for_challonge_group(tournament, match.group_id)
    return _find_playoff_stage(tournament)


def _normalize_team_name(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.lower()).strip()


async def _fetch_source_data(source: _ImportSource) -> _SourceFetch:
    """Fetch matches and participants for one Challonge source in parallel."""
    results = await asyncio.gather(
        challonge_client.fetch_matches(source.challonge_id),
        challonge_client.fetch_participants(source.challonge_id),
        return_exceptions=True,
    )
    matches_result, participants_result = results

    if isinstance(matches_result, Exception):
        raise matches_result

    if isinstance(participants_result, Exception):
        logger.warning(
            "Failed to fetch Challonge participants; auto-mapping disabled for this source",
            challonge_id=source.challonge_id,
            error=str(participants_result),
        )
        participants_result = []

    return _SourceFetch(matches=matches_result, participants=participants_result)


async def _fetch_all_sources(
    sources: list[_ImportSource],
) -> list[tuple[_ImportSource, _SourceFetch | Exception]]:
    """Fetch all sources concurrently, returning (source, result_or_exception) pairs."""
    results = await asyncio.gather(
        *[_fetch_source_data(s) for s in sources],
        return_exceptions=True,
    )
    return list(zip(sources, results, strict=True))


def _encounter_sync_snapshot(
    encounter: models.Encounter,
    seats: Sequence[models.EncounterTeam],
    position: models.BracketEncounter | None,
) -> dict:
    """What the sync log records about an encounter before/after a write.

    Seats, not two columns: the log is read by a human comparing an import
    against what stood here, and a lobby's four numbers have to fit in it too.
    """
    return {
        "id": encounter.id,
        "team_ids": [seat.team_id for seat in seats],
        "scores": [seat.score for seat in seats],
        "round": None if position is None else position.round,
        "status": encounter.status.value if hasattr(encounter.status, "value") else encounter.status,
        "stage_id": None if position is None else position.stage_id,
        "stage_item_id": None if position is None else position.stage_item_id,
    }


_HELD_RESULT_STATUSES = (enums.EncounterResultStatus.DISPUTED, enums.EncounterResultStatus.PENDING_CONFIRMATION)


def _has_local_decision(encounter: models.Encounter) -> bool:
    """Whether a local result outranks whatever Challonge is reporting.

    Keyed on ``result_status``, not just ``status``: a dispute or a half-reported
    result is a decision in progress, and silently overwriting it would destroy
    the captains' evidence and the admin's pending call.
    """
    return (
        encounter.status == enums.EncounterStatus.COMPLETED
        or encounter.result_status == enums.EncounterResultStatus.CONFIRMED
        or encounter.result_status in _HELD_RESULT_STATUSES
    )


def _iter_challonge_link_specs(
    source: _ImportSource,
    match: schemas.ChallongeMatch,
) -> list[_ChallongeLinkSpec]:
    specs: list[_ChallongeLinkSpec] = []
    source_key = _source_lookup_key(source)
    for prereq_id, is_loser, slot in (
        (match.player1_prereq_match_id, match.player1_is_prereq_match_loser, 1),
        (match.player2_prereq_match_id, match.player2_is_prereq_match_loser, 2),
    ):
        if prereq_id is None or prereq_id == match.id:
            continue
        specs.append(
            _ChallongeLinkSpec(
                source_key=source_key,
                source_challonge_id=prereq_id,
                target_challonge_id=match.id,
                # Challonge's winner/loser IS a place: first or second.
                source_position=2 if is_loser else 1,
                target_slot=slot,
            )
        )
    return specs


def _import_invalidated_resources(stats: dict) -> tuple[Resource, ...]:
    """What an import actually staled, or an empty tuple for a no-op import.

    Stages/groups/stage-inputs/bracket-links reshape the page itself; a plain
    score or status sync only moves the results. Empty means nothing changed, so
    we publish no event at all rather than a spurious one.
    """
    if (
        stats["stages_created"]
        or stats["groups_created"]
        or stats["stage_inputs_created"]
        or stats["bracket_links_created"]
        or stats["bracket_links_updated"]
    ):
        return STRUCTURE_RESOURCES
    if stats["created"] or stats["updated"] or stats["matches_synced"]:
        return RESULT_RESOURCES
    return ()


def _source_matches_encounter(source: _ImportSource, position: models.BracketEncounter | None) -> bool:
    if position is not None and source.stage_item_id is not None and position.stage_item_id == source.stage_item_id:
        return True
    if position is not None and source.stage is not None and position.stage_id == source.stage.id:
        return True
    return source.source_type == "tournament"


def _places(totals: Mapping[int, float]) -> dict[int, int]:
    """Competition ranking over a scoreline: 2-0 -> 1, 2; 1-1 -> 1, 1."""
    places: dict[int, int] = {}
    place, previous = 0, None
    for index, (key, value) in enumerate(sorted(totals.items(), key=lambda pair: (-pair[1], pair[0])), 1):
        if value != previous:
            place, previous = index, value
        places[key] = place
    return places


async def _reseat(
    session: AsyncSession,
    encounter: models.Encounter,
    team_ids: Sequence[int | None],
    names: Mapping[int, str],
) -> bool:
    """Make the encounter's seats match ``team_ids`` -- index ``i`` is slot ``i + 1``.

    Challonge's participant 1 and 2 ARE slots 1 and 2; there is no orientation
    to preserve. A seat that changes hands is retired and a new participation
    written, never updated in place, so the games the old occupant played
    stay attached to the row that played them. Returns whether anything moved.
    """
    changed = False
    current = {seat.slot: seat for seat in await active_teams(session, encounter.id)}
    for index, team_id in enumerate(team_ids, 1):
        seat = current.get(index)
        if seat is not None and seat.team_id == team_id:
            continue
        if seat is not None:
            await vacate_slot(session, encounter, slot=index)
            changed = True
        if team_id is not None:
            await place_team(
                session,
                encounter,
                slot=index,
                team_id=team_id,
                name=names.get(team_id, "TBD"),
                seed=None,
                members=(),
            )
            changed = True
    return changed


async def _write_import_result(
    session: AsyncSession,
    encounter: models.Encounter,
    scores: Sequence[float],
) -> None:
    """Record Challonge's scoreline as this encounter's standing.

    Source ``import``: a remote system decided it, which is what stops a later
    ``refresh_from_games`` from overwriting it with whatever the local game rows
    add up to. ``actor_user_id`` stays NULL for the same reason.
    """
    seats = await active_teams(session, encounter.id)
    totals = {seat.id: float(score) for seat, score in zip(seats, scores, strict=False)}
    await apply_result(
        session,
        encounter,
        source=enums.EncounterResultSource.IMPORT,
        totals=totals,
        placements=_places(totals),
        action=enums.EncounterResultAuditAction.IMPORT,
        audit_source="challonge",
        actor_user_id=None,
        reason=None,
    )


class ChallongeSyncLogService:
    """The ``challonge_sync_log`` audit trail: every import/export write, conflict and failure.

    An imported match Challonge left unchanged writes no row. Rows older than
    ``SYNC_LOG_RETENTION`` go in ``purge_sync_log``.

    Its own collaborator rather than a method on ``ChallongeSyncService`` because
    ``ChallongeMappingService`` writes to the same trail when it auto-maps
    participants, and injecting the whole orchestration service into the mapping
    service just to reach one write would be circular.
    """

    def __init__(self, *, sync_log_repo: ChallongeSyncLogRepository = ChallongeSyncLogRepository()) -> None:
        self.sync_log_repo = sync_log_repo

    async def _log_sync(
        self,
        session: AsyncSession,
        tournament_id: int,
        direction: str,
        entity_type: str,
        entity_id: int | None,
        challonge_id: int | None,
        status: str,
        *,
        source_id: int | None = None,
        operation: str | None = None,
        payload: dict | None = None,
        conflict_type: str | None = None,
        before: dict | None = None,
        after: dict | None = None,
        error_message: str | None = None,
    ) -> models.ChallongeSyncLog:
        entry = models.ChallongeSyncLog(
            tournament_id=tournament_id,
            source_id=source_id,
            direction=direction,
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
            challonge_id=challonge_id,
            status=status,
            conflict_type=conflict_type,
            payload_json=payload,
            before_json=before,
            after_json=after,
            error_message=error_message,
        )
        return await self.sync_log_repo.create(session, entry)

    async def get_sync_log(
        self, session: AsyncSession, tournament_id: int, limit: int = 50
    ) -> list[models.ChallongeSyncLog]:
        return list(await self.sync_log_repo.list_by_tournament(session, tournament_id, limit=limit))


async def purge_sync_log(session_factory: async_sessionmaker[AsyncSession] = db.async_session_maker) -> int:
    """Delete sync-log rows older than ``SYNC_LOG_RETENTION``; returns how many went.

    Daily scheduler job. ``SYNC_LOG_PURGE_BATCH`` rows per transaction so no single delete holds locks or bloats WAL
    for long.
    """
    cutoff = datetime.now(UTC) - SYNC_LOG_RETENTION
    deleted = 0
    while True:
        async with session_factory() as session:
            count = await sync_log_service.sync_log_repo.delete_older_than(session, cutoff, limit=SYNC_LOG_PURGE_BATCH)
            await session.commit()
        deleted += count
        if count < SYNC_LOG_PURGE_BATCH:
            break
    if deleted:
        logger.info("Purged {} Challonge sync-log rows", deleted)
    return deleted


sync_log_service = ChallongeSyncLogService()


class ChallongeStructureService:
    """Creates the local stage / group / stage-item / stage-item-input rows a
    Challonge bracket implies, before any match can be routed to one."""

    def __init__(
        self,
        *,
        stage_repo: StageRepository = StageRepository(),
        stage_item_repo: StageItemRepository = StageItemRepository(),
        stage_item_input_repo: StageItemInputRepository = StageItemInputRepository(),
        bracket_encounter_repo: BracketEncounterRepository = BracketEncounterRepository(),
    ) -> None:
        self.stage_repo = stage_repo
        self.stage_item_repo = stage_item_repo
        self.stage_item_input_repo = stage_item_input_repo
        self.bracket_encounter_repo = bracket_encounter_repo

    async def _ensure_stage_item(
        self,
        session: AsyncSession,
        stage: models.Stage,
        *,
        name: str,
        item_type: enums.StageItemType,
    ) -> models.StageItem:
        # If items are not loaded in this session state, query them async to avoid
        # triggering a synchronous lazy-load (MissingGreenlet) in an async context.
        try:
            items_unloaded = "items" in sa_inspect(stage).unloaded
        except Exception:
            items_unloaded = False

        if items_unloaded:
            existing = await self.stage_item_repo.list_by_stage(session, stage.id)
        else:
            existing = list(stage.items or [])

        items = existing
        if items:
            return sorted(items, key=lambda item: (item.order, item.id))[0]

        item = models.StageItem(
            stage_id=stage.id,
            name=name,
            type=item_type,
            order=0,
        )
        item.inputs = []
        await self.stage_item_repo.create(session, item)
        if not items_unloaded:
            stage.items.append(item)
        return item

    async def _create_stage_with_item(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        *,
        name: str,
        description: str | None,
        stage_type: enums.StageType,
        item_type: enums.StageItemType,
    ) -> models.Stage:
        # Stage-level Challonge identity lives in ``challonge_source`` (derived at
        # read time), not on the stage row.
        stage = models.Stage(
            tournament_id=tournament.id,
            name=name,
            description=description,
            stage_type=stage_type,
            order=_next_stage_order(tournament),
        )
        # Seeded while the stage is still transient, like ``item.inputs`` below: the
        # flush turns it persistent, and from then on the first touch of a collection
        # nothing ever loaded emits a lazy SELECT -- MissingGreenlet under async
        # SQLAlchemy.
        stage.items = []
        stage.round_best_of = []
        await self.stage_repo.create(session, stage)
        _append_once(tournament.stages, stage)
        item = models.StageItem(
            stage_id=stage.id,
            name=name,
            type=item_type,
            order=0,
        )
        item.inputs = []
        await self.stage_item_repo.create(session, item)
        _append_once(stage.items, item)
        return stage

    async def _ensure_group_stage(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        stage: models.Stage,
        *,
        item_type: enums.StageItemType,
    ) -> None:
        if stage not in (tournament.stages or []):
            _append_once(tournament.stages, stage)
        await self._ensure_stage_item(
            session,
            stage,
            name=stage.name,
            item_type=item_type,
        )

    async def _create_group_with_stage(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        *,
        name: str,
        challonge_id: int | None,
        stage_type: enums.StageType,
    ) -> models.Stage:
        stage = await self._create_stage_with_item(
            session,
            tournament,
            name=name,
            description=None,
            stage_type=stage_type,
            item_type=_stage_item_type_for_stage(stage_type),
        )
        if challonge_id is not None:
            stage.challonge_group_id = challonge_id
            await session.flush()
        return stage

    async def _ensure_stage_structure_for_matches(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        source: _ImportSource,
        matches: list[schemas.ChallongeMatch],
    ) -> dict[str, int]:
        stats = {"stages_created": 0, "groups_created": 0}

        if source.stage is not None:
            await self._ensure_stage_item(
                session,
                source.stage,
                name=source.stage.name,
                item_type=_stage_item_type_for_stage(source.stage.stage_type),
            )

        group_ids = {match.group_id for match in matches if match.group_id is not None}
        names_by_group_id = _group_names_for_challonge_ids(group_ids)
        for group_id in sorted(group_ids):
            stage = _stage_for_challonge_group(tournament, group_id)
            if stage is None and source.stage is not None:
                existing_id = source.stage.challonge_group_id
                if existing_id == group_id or (
                    existing_id is None and source.stage.stage_type == enums.StageType.ROUND_ROBIN
                ):
                    stage = source.stage
            if stage is None:
                await self._create_group_with_stage(
                    session,
                    tournament,
                    name=names_by_group_id[group_id],
                    challonge_id=group_id,
                    stage_type=enums.StageType.ROUND_ROBIN,
                )
                stats["groups_created"] += 1
                stats["stages_created"] += 1
            else:
                if stage.challonge_group_id != group_id:
                    stage.challonge_group_id = group_id
                before_stage_count = len(tournament.stages or [])
                await self._ensure_group_stage(
                    session,
                    tournament,
                    stage,
                    item_type=enums.StageItemType.GROUP,
                )
                stats["stages_created"] += max(0, len(tournament.stages or []) - before_stage_count)

        ungrouped_matches = [match for match in matches if match.group_id is None]
        if not ungrouped_matches:
            return stats

        if source.stage is not None and not group_ids:
            return stats

        playoff_stage = _find_playoff_stage(tournament)
        if playoff_stage is None:
            await self._create_group_with_stage(
                session,
                tournament,
                name="Playoffs",
                challonge_id=None,
                stage_type=_playoff_stage_type(ungrouped_matches),
            )
            stats["groups_created"] += 1
            stats["stages_created"] += 1
        else:
            before_stage_count = len(tournament.stages or [])
            await self._ensure_group_stage(
                session,
                tournament,
                playoff_stage,
                item_type=enums.StageItemType.SINGLE_BRACKET,
            )
            stats["stages_created"] += max(0, len(tournament.stages or []) - before_stage_count)

        return stats

    async def _resolve_stage_refs_for_match(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        source: _ImportSource,
        stage: models.Stage | None,
        match: schemas.ChallongeMatch,
    ) -> StageRefs:
        if stage is None:
            stage = source.stage
        return await resolve_stage_refs_from_group(
            session,
            tournament_id=tournament.id,
            stage_id=stage.id if stage else None,
            stage_item_id=_default_stage_item_id(stage, match),
        )

    async def _load_stage_inputs(
        self,
        session: AsyncSession,
        stage_id: int,
    ) -> list[models.StageItemInput]:
        result = await session.execute(
            self.stage_item_input_repo.select()
            .join(models.StageItem, models.StageItemInput.stage_item_id == models.StageItem.id)
            .where(models.StageItem.stage_id == stage_id)
        )
        return list(result.scalars().all())

    async def _ensure_stage_item_team_inputs(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        *,
        stage_item_id: int | None,
        team_ids: list[int | None],
    ) -> int:
        if stage_item_id is None:
            return 0

        unique_team_ids: list[int] = []
        seen_team_ids: set[int] = set()
        for team_id in team_ids:
            if team_id is None or team_id in seen_team_ids:
                continue
            unique_team_ids.append(team_id)
            seen_team_ids.add(team_id)
        if not unique_team_ids:
            return 0

        stage, item = _find_loaded_stage_item(tournament, stage_item_id)
        if stage is None or item is None:
            return 0

        stage_items = _loaded_collection(stage, "items") or [item]
        stage_inputs: list[models.StageItemInput] = []
        inputs_loaded = True
        for candidate in stage_items:
            candidate_inputs = _loaded_collection(candidate, "inputs")
            if candidate_inputs is None:
                inputs_loaded = False
                break
            stage_inputs.extend(candidate_inputs)

        if not inputs_loaded:
            stage_inputs = await self._load_stage_inputs(session, stage.id)

        existing_team_ids = {stage_input.team_id for stage_input in stage_inputs if stage_input.team_id is not None}
        used_slots = {stage_input.slot for stage_input in stage_inputs if stage_input.stage_item_id == stage_item_id}
        next_slot = 1
        created: list[models.StageItemInput] = []

        for team_id in unique_team_ids:
            if team_id in existing_team_ids:
                continue
            while next_slot in used_slots:
                next_slot += 1
            stage_input = models.StageItemInput(
                stage_item_id=stage_item_id,
                slot=next_slot,
                input_type=enums.StageItemInputType.FINAL,
                team_id=team_id,
            )
            created.append(stage_input)
            existing_team_ids.add(team_id)
            used_slots.add(next_slot)
            next_slot += 1

            item_inputs = _loaded_collection(item, "inputs")
            if item_inputs is not None:
                try:
                    item.inputs.append(stage_input)
                except Exception:
                    pass

        if created:
            await self.stage_item_input_repo.create_many(session, created)
        return len(created)

    async def _ensure_encounter_stage_inputs(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        encounter: models.Encounter | None,
    ) -> int:
        if encounter is None:
            return 0
        position = await self.bracket_encounter_repo.get_position(session, encounter.id)
        if position is None:
            return 0
        return await self._ensure_stage_item_team_inputs(
            session,
            tournament,
            stage_item_id=position.stage_item_id,
            team_ids=[seat.team_id for seat in await active_teams(session, encounter.id)],
        )


structure_service = ChallongeStructureService()


class ChallongeMappingService:
    """Source discovery plus the Challonge-id <-> local-id mapping tables.

    ``challonge_source`` is the single source of truth for "this tournament is
    mirrored on Challonge"; ``challonge_participant_mapping`` and
    ``challonge_match_mapping`` translate Challonge's participant/match ids to
    local team/encounter ids under one source.
    """

    def __init__(
        self,
        *,
        source_repo: ChallongeSourceRepository = ChallongeSourceRepository(),
        participant_mapping_repo: ChallongeParticipantMappingRepository = ChallongeParticipantMappingRepository(),
        match_mapping_repo: ChallongeMatchMappingRepository = ChallongeMatchMappingRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        team_repo: TeamRepository = TeamRepository(),
        sync_log: ChallongeSyncLogService = sync_log_service,
    ) -> None:
        self.source_repo = source_repo
        self.participant_mapping_repo = participant_mapping_repo
        self.match_mapping_repo = match_mapping_repo
        self.tournament_repo = tournament_repo
        self.team_repo = team_repo
        self.sync_log = sync_log

    async def discover_sources(self, session: AsyncSession, tournament: models.Tournament) -> list[_ImportSource]:
        """Discover Challonge sources from the normalized ``challonge_source`` table.

        Stage comes from ``ChallongeSource.stage``. Read-only: the admin link
        entry-point owns source creation.
        """
        # Sorted by id: ``_resolve_export_target`` picks ``candidates[0]`` out of
        # this list, so a stable order is part of which Challonge source an
        # unmapped encounter is attributed to.
        source_rows = sorted(
            await self.source_repo.list_by_tournament(
                session,
                tournament.id,
                options=[
                    selectinload(models.ChallongeSource.stage)
                    .selectinload(models.Stage.items)
                    .selectinload(models.StageItem.inputs),
                    selectinload(models.ChallongeSource.stage_item),
                ],
            ),
            key=lambda row: row.id,
        )
        return [
            _ImportSource(
                challonge_id=row.challonge_tournament_id,
                source_id=row.id,
                source_type=row.source_type,
                stage=row.stage,
                stage_item_id=row.stage_item_id or _first_loaded_stage_item_id(row.stage),
                slug=row.slug,
            )
            for row in source_rows
        ]

    async def _build_team_name_index(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> dict[str, int]:
        """Build a normalized-name → team_id index for auto-mapping.

        Collisions (two teams with the same normalized name) are marked _AMBIGUOUS.
        balancer_name is used as a fallback only when name produces no entry.
        """
        teams = await self.team_repo.list_by_tournament(session, tournament_id)
        index: dict[str, int] = {}

        for team in teams:
            key = _normalize_team_name(team.name)
            if not key:
                continue
            if key in index and index[key] != team.id:
                index[key] = _AMBIGUOUS
                logger.warning(
                    "Ambiguous team name for Challonge auto-mapping",
                    key=key,
                    tournament_id=tournament_id,
                )
            elif key not in index:
                index[key] = team.id

        for team in teams:
            key = _normalize_team_name(getattr(team, "balancer_name", None))
            if not key or key in index:
                continue
            index[key] = team.id

        return index

    async def _auto_map_participants(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        fetches: list[tuple[_ImportSource, _SourceFetch]],
        existing_source_mappings: list[models.ChallongeParticipantMapping],
        name_index: dict[str, int],
        *,
        dry_run: bool = False,
    ) -> list[models.ChallongeParticipantMapping]:
        """Auto-create ``ChallongeParticipantMapping`` rows by matching participant
        names to local teams.

        Existing mappings always win; ambiguous name matches are skipped. Both the
        participant id and every ``group_player_id`` alias are mapped, scoped to
        the source.
        """
        existing_source_keys: set[tuple[int, int]] = {
            (mapping.source_id, mapping.challonge_participant_id) for mapping in existing_source_mappings
        }
        # (mapping, participant_name, source_group_id) — group id only for the sync log.
        created: list[tuple[models.ChallongeParticipantMapping, str, int | None]] = []
        pending: list[models.ChallongeParticipantMapping] = []

        total_participants = sum(len(f.participants) for _, f in fetches)
        logger.info(
            "Auto-mapping participants",
            tournament_id=tournament.id,
            total_participants=total_participants,
            name_index_size=len(name_index),
            existing_mappings=len(existing_source_mappings),
        )

        for source, fetch in fetches:
            if source.source_id is None:
                continue
            source_group_id = None

            for participant in fetch.participants:
                key = _normalize_team_name(participant.name)
                if not key:
                    continue

                team_id = name_index.get(key)
                if team_id is None:
                    logger.debug(
                        "No local team matches Challonge participant",
                        participant_name=participant.name,
                        challonge_id=participant.id,
                        tournament_id=tournament.id,
                    )
                    continue
                if team_id == _AMBIGUOUS:
                    logger.warning(
                        "Ambiguous team name; skipping Challonge auto-map",
                        participant_name=participant.name,
                        challonge_id=participant.id,
                    )
                    continue

                for challonge_participant_id in (participant.id, *participant.group_player_ids):
                    source_key = (source.source_id, challonge_participant_id)
                    if source_key in existing_source_keys:
                        continue
                    mapping = models.ChallongeParticipantMapping(
                        source_id=source.source_id,
                        challonge_participant_id=challonge_participant_id,
                        team_id=team_id,
                    )
                    if not dry_run:
                        pending.append(mapping)
                    created.append((mapping, participant.name, source_group_id))
                    existing_source_keys.add(source_key)

        if dry_run:
            logger.info(
                "Auto-mapping dry-run complete",
                tournament_id=tournament.id,
                auto_mapped=len(created),
            )
            return []

        if created:
            await self.participant_mapping_repo.create_many(session, pending)
            for mapping, participant_name, source_group_id in created:
                await self.sync_log._log_sync(
                    session,
                    tournament.id,
                    "import",
                    "participant",
                    mapping.team_id,
                    mapping.challonge_participant_id,
                    "success",
                    source_id=mapping.source_id,
                    operation="auto_map_participant",
                    payload={
                        "action": "auto_mapped",
                        "participant_name": participant_name,
                        "group_id": source_group_id,
                    },
                )

        logger.info(
            "Auto-mapping complete",
            tournament_id=tournament.id,
            auto_mapped=len(created),
        )
        return [mapping for mapping, _name, _group_id in created]

    async def _build_team_lookup(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        fetches: list[tuple[_ImportSource, _SourceFetch]],
        *,
        source_ids: Sequence[int],
        dry_run: bool = False,
    ) -> _TeamLookup:
        # ``source_ids`` is every discovered source of this tournament, including
        # sources whose fetch failed: their mappings still feed the cross-source
        # (None, participant_id) fallback in _TeamLookup.resolve.
        existing_source_mappings = list(await self.participant_mapping_repo.list_by_source_ids(session, source_ids))

        name_index = await self._build_team_name_index(session, tournament.id)
        created_mappings = await self._auto_map_participants(
            session,
            tournament,
            fetches,
            existing_source_mappings,
            name_index,
            dry_run=dry_run,
        )

        all_mappings = existing_source_mappings + created_mappings

        # Per-source lookup key. Team resolve uses the (None, challonge_id) fallback.
        source_key_by_source_id: dict[int, int] = {}
        for source, _fetch in fetches:
            if source.source_id is not None:
                source_key_by_source_id[source.source_id] = _source_lookup_key(source)

        by_source_key: dict[tuple[int, int], int] = {}
        by_key: dict[tuple[int | None, int], int] = {}
        for mapping in all_mappings:
            source_key = source_key_by_source_id.get(mapping.source_id, mapping.source_id)
            by_source_key[(source_key, mapping.challonge_participant_id)] = mapping.team_id
            by_key.setdefault((None, mapping.challonge_participant_id), mapping.team_id)

        team_ids = sorted({mapping.team_id for mapping in all_mappings})
        teams_by_id = {team.id: team for team in await self.team_repo.bulk_get(session, team_ids)}

        logger.info(
            "Team lookup built",
            tournament_id=tournament.id,
            mapping_count=len(by_key),
            team_count=len(teams_by_id),
        )
        return _TeamLookup(
            by_source_key=by_source_key,
            by_key=by_key,
            teams_by_id=teams_by_id,
        )

    async def _build_match_lookup(
        self,
        session: AsyncSession,
        sources: list[_ImportSource],
        *,
        tournament_id: int,
    ) -> _MatchLookup:
        source_keys_by_source_id = {
            source.source_id: _source_lookup_key(source) for source in sources if source.source_id is not None
        }
        mapping_result = await session.execute(
            self.match_mapping_repo.select()
            .where(models.ChallongeMatchMapping.source_id.in_(tuple(source_keys_by_source_id.keys())))
            .options(selectinload(models.ChallongeMatchMapping.encounter))
        )
        mappings = list(mapping_result.scalars().all())
        by_source_key: dict[tuple[int, int], models.Encounter] = {}
        mapped_keys: set[tuple[int, int]] = set()
        mapped_encounter_ids: set[int] = set()
        for mapping in mappings:
            mapped_keys.add((mapping.source_id, mapping.challonge_match_id))
            if mapping.encounter is None:
                continue
            mapped_encounter_ids.add(mapping.encounter.id)
            source_key = source_keys_by_source_id.get(mapping.source_id, mapping.source_id)
            by_source_key[(source_key, mapping.challonge_match_id)] = mapping.encounter

        # Locally generated bracket rows (StageService.generate_encounters) with no
        # challonge_match_mapping yet, indexed by (stage, round, team pair) so the
        # create-path adopts them instead of laying a second Encounter over the
        # same slot every run.
        unlinked_by_slot: dict[tuple[int | None, int, frozenset[int]], models.Encounter] = {}
        encounters_result = await session.execute(
            sa.select(models.Encounter, models.BracketEncounter)
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(
                models.Encounter.tournament_id == tournament_id,
                # A Challonge match is a duel; a lobby sitting in the same
                # tournament must never be claimed as one of its slots.
                models.Encounter.slot_count == 2,
            )
        )
        rows = encounters_result.tuples().all()
        seats_by_encounter: dict[int, list[int]] = {}
        for seat in (
            await session.execute(
                sa.select(models.EncounterTeam).where(
                    models.EncounterTeam.encounter_id.in_([encounter.id for encounter, _ in rows] or [0]),
                    models.EncounterTeam.active.is_(True),
                    models.EncounterTeam.team_id.is_not(None),
                )
            )
        ).scalars():
            seats_by_encounter.setdefault(seat.encounter_id, []).append(seat.team_id)
        for encounter, position in rows:
            if encounter.id in mapped_encounter_ids:
                continue
            team_ids = seats_by_encounter.get(encounter.id, [])
            # TBD slots are left for the create-path: there is nothing to match yet.
            if len(team_ids) != 2:
                continue
            unlinked_by_slot.setdefault((position.stage_id, position.round, frozenset(team_ids)), encounter)

        # Existing encounters are located via challonge_match_mapping (by_source_key);
        # by_challonge_id is an in-run cache populated by _MatchLookup.set for
        # encounters created/mapped during this import.
        return _MatchLookup(
            by_source_key=by_source_key,
            by_challonge_id={},
            mapped_keys=mapped_keys,
            unlinked_by_slot=unlinked_by_slot,
        )

    async def _ensure_match_mapping(
        self,
        session: AsyncSession,
        source: _ImportSource,
        challonge_match_id: int,
        encounter: models.Encounter,
        match_lookup: _MatchLookup,
    ) -> None:
        if source.source_id is None:
            return
        key = (source.source_id, challonge_match_id)
        if key in match_lookup.mapped_keys:
            return
        mapping = models.ChallongeMatchMapping(
            source_id=source.source_id,
            challonge_match_id=challonge_match_id,
            encounter_id=encounter.id,
        )
        await self.match_mapping_repo.create(session, mapping)
        match_lookup.mapped_keys.add(key)
        match_lookup.set(source, challonge_match_id, encounter)

    async def _existing_participant_mappings(
        self, session: AsyncSession, source_ids: set[int]
    ) -> dict[tuple[int, int], models.ChallongeParticipantMapping]:
        mappings: dict[tuple[int, int], models.ChallongeParticipantMapping] = {}
        for mapping in await self.participant_mapping_repo.list_by_source_ids(session, sorted(source_ids)):
            mappings.setdefault((mapping.source_id, mapping.challonge_participant_id), mapping)
        return mappings

    async def _fetch_team_sync_context(
        self, session: AsyncSession, tournament_id: int
    ) -> tuple[models.Tournament, list[models.Team], list[tuple[_ImportSource, _SourceFetch]]]:
        """Shared setup for preview/apply: the tournament, its teams, and every
        Challonge source's current participant list (matches are irrelevant here,
        but ``_fetch_all_sources`` fetches both in one round-trip per source)."""
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise HTTPException(status_code=404, detail="Tournament not found")

        sources = await self.discover_sources(session, tournament)
        teams = list(await team_service.get_by_tournament(session, tournament, []))
        raw_fetches = await _fetch_all_sources(sources)
        fetches = [(source, fetch) for source, fetch in raw_fetches if not isinstance(fetch, Exception)]
        return tournament, teams, fetches

    async def preview_team_mapping(self, session: AsyncSession, tournament_id: int) -> schemas.ChallongeTeamSyncPreview:
        """Read-only: for every Challonge participant on this tournament's linked
        source(s), suggest a local team by normalized-name match and report any
        mapping already persisted. Counterpart to ``apply_team_mapping``, which
        accepts an admin's explicit overrides for whatever this can't resolve
        (no match, or an ambiguous name shared by two local teams)."""
        _tournament, teams, fetches = await self._fetch_team_sync_context(session, tournament_id)
        name_index = await self._build_team_name_index(session, tournament_id)
        source_ids = {source.source_id for source, _fetch in fetches if source.source_id is not None}
        existing_mappings = await self._existing_participant_mappings(session, source_ids)

        participants: list[schemas.ChallongeTeamPreviewParticipant] = []
        for source, fetch in fetches:
            for participant in fetch.participants:
                suggested_team_id = name_index.get(_normalize_team_name(participant.name))
                if suggested_team_id == _AMBIGUOUS:
                    suggested_team_id = None
                mapped_team_id = (
                    existing_mappings[(source.source_id, participant.id)].team_id
                    if source.source_id is not None and (source.source_id, participant.id) in existing_mappings
                    else None
                )
                participants.append(
                    schemas.ChallongeTeamPreviewParticipant(
                        participant_id=participant.id,
                        challonge_id=participant.id,
                        group_id=None,
                        group_name=None,
                        challonge_tournament_id=source.challonge_id,
                        name=participant.name,
                        active=participant.active,
                        suggested_team_id=suggested_team_id,
                        mapped_team_id=mapped_team_id,
                    )
                )

        return schemas.ChallongeTeamSyncPreview(
            teams=[
                schemas.ChallongeTeamPreviewTeam(id=team.id, name=team.name, balancer_name=team.balancer_name)
                for team in teams
            ],
            participants=participants,
        )

    async def apply_team_mapping(
        self, session: AsyncSession, tournament_id: int, mappings: list[schemas.ChallongeTeamMapping]
    ) -> schemas.ChallongeTeamSyncResult:
        """Persist an admin's explicit Challonge participant -> team mappings.

        Every ``(participant_id, group_id)`` in ``mappings`` must resolve against
        this tournament's currently fetched Challonge participants, and every
        ``team_id`` must belong to this tournament -- both checked up front so a bad
        entry fails the whole request rather than silently skipping it."""
        _tournament, teams, fetches = await self._fetch_team_sync_context(session, tournament_id)
        team_ids = {team.id for team in teams}

        rows_by_request_key: dict[tuple[int, int | None], tuple[_ImportSource, schemas.ChallongeParticipant]] = {}
        for source, fetch in fetches:
            group_id = None
            for participant in fetch.participants:
                rows_by_request_key[(participant.id, group_id)] = (source, participant)

        validation_errors: list[str] = []
        for mapping in mappings:
            if (mapping.participant_id, mapping.group_id) not in rows_by_request_key:
                validation_errors.append(f"Challonge participant {mapping.participant_id} not found on this tournament")
            elif mapping.team_id not in team_ids:
                validation_errors.append(f"Team {mapping.team_id} not found on this tournament")
        if validation_errors:
            raise HTTPException(status_code=400, detail=validation_errors)

        source_ids = {
            source.source_id for source, _participant in rows_by_request_key.values() if source.source_id is not None
        }
        existing_mappings = await self._existing_participant_mappings(session, source_ids)

        created = updated = unchanged = 0
        new_rows: list[models.ChallongeParticipantMapping] = []
        for mapping in mappings:
            source, participant = rows_by_request_key[(mapping.participant_id, mapping.group_id)]
            if source.source_id is None:
                continue
            # Challonge's group stages give each participant a separate
            # ``group_player_id`` per group, and group-stage matches reference
            # that id (not the top-level participant id) as player1_id/player2_id.
            # Map every alias here too (as `_auto_map_participants` does), or
            # matches never resolve a team the admin explicitly picked.
            primary_result = "unchanged"
            for challonge_participant_id in (participant.id, *participant.group_player_ids):
                source_key = (source.source_id, challonge_participant_id)
                existing = existing_mappings.get(source_key)
                if existing is None:
                    row = models.ChallongeParticipantMapping(
                        source_id=source.source_id,
                        challonge_participant_id=challonge_participant_id,
                        team_id=mapping.team_id,
                    )
                    new_rows.append(row)
                    existing_mappings[source_key] = row
                    result = "created"
                elif existing.team_id != mapping.team_id:
                    existing.team_id = mapping.team_id
                    result = "updated"
                else:
                    result = "unchanged"
                if challonge_participant_id == participant.id:
                    primary_result = result
            if primary_result == "created":
                created += 1
            elif primary_result == "updated":
                updated += 1
            else:
                unchanged += 1

        if new_rows:
            await self.participant_mapping_repo.create_many(session, new_rows)
        await session.commit()
        mapped_keys = {(mapping.participant_id, mapping.group_id) for mapping in mappings}
        skipped = max(len(rows_by_request_key) - len(mapped_keys), 0)
        return schemas.ChallongeTeamSyncResult(
            success=True,
            count=created + updated + unchanged,
            created=created,
            updated=updated,
            unchanged=unchanged,
            skipped=skipped,
        )


mapping_service = ChallongeMappingService()


class ChallongeSyncService:
    """The public Challonge sync surface: import, export, single-result push,
    auto-push on confirmation, and the periodic worker pull."""

    def __init__(
        self,
        *,
        tournament_repo: TournamentRepository = TournamentRepository(),
        encounter_repo: EncounterRepository = EncounterRepository(),
        encounter_link_repo: EncounterLinkRepository = EncounterLinkRepository(),
        bracket_encounter_repo: BracketEncounterRepository = BracketEncounterRepository(),
        scoring_rule_repo: ScoringRuleRepository = ScoringRuleRepository(),
        source_repo: ChallongeSourceRepository = ChallongeSourceRepository(),
        match_mapping_repo: ChallongeMatchMappingRepository = ChallongeMatchMappingRepository(),
        participant_mapping_repo: ChallongeParticipantMappingRepository = ChallongeParticipantMappingRepository(),
        structure: ChallongeStructureService = structure_service,
        mapping: ChallongeMappingService = mapping_service,
        sync_log: ChallongeSyncLogService = sync_log_service,
    ) -> None:
        self.tournament_repo = tournament_repo
        self.encounter_repo = encounter_repo
        self.encounter_link_repo = encounter_link_repo
        self.bracket_encounter_repo = bracket_encounter_repo
        self.scoring_rule_repo = scoring_rule_repo
        self.source_repo = source_repo
        self.match_mapping_repo = match_mapping_repo
        self.participant_mapping_repo = participant_mapping_repo
        self.structure = structure
        self.mapping = mapping
        self.sync_log = sync_log

    async def get_sync_log(
        self, session: AsyncSession, tournament_id: int, limit: int = 50
    ) -> list[models.ChallongeSyncLog]:
        return await self.sync_log.get_sync_log(session, tournament_id, limit)

    async def preview_team_mapping(self, session: AsyncSession, tournament_id: int) -> schemas.ChallongeTeamSyncPreview:
        return await self.mapping.preview_team_mapping(session, tournament_id)

    async def apply_team_mapping(
        self, session: AsyncSession, tournament_id: int, mappings: list[schemas.ChallongeTeamMapping]
    ) -> schemas.ChallongeTeamSyncResult:
        return await self.mapping.apply_team_mapping(session, tournament_id, mappings)

    # ── Import (Challonge -> local) ──────────────────────────────────────

    async def _scoring_rule_id(self, session: AsyncSession, tournament: models.Tournament, refs: StageRefs) -> int:
        """The rule an imported encounter is scored by.

        The stage's own when the match resolved to one -- so an imported bracket
        is scored exactly like a locally generated one. A match with no stage
        gets the tournament's own ``wins`` rule, created once and reused, because
        ``encounter.scoring_rule_id`` is NOT NULL and an import must not invent a
        rule row per match.
        """
        if refs.stage_id is not None:
            rule_id = await session.scalar(
                sa.select(models.Stage.scoring_rule_id).where(models.Stage.id == refs.stage_id)
            )
            if rule_id is not None:
                return rule_id
        # Looked up rather than cached on the service: this is a singleton shared
        # by every workspace, and a rule belongs to exactly one of them.
        existing = await session.scalar(
            sa.select(models.ScoringRule.id)
            .where(
                models.ScoringRule.workspace_id == tournament.workspace_id,
                models.ScoringRule.preset == "wins",
                models.ScoringRule.game_formula == "win",
            )
            .order_by(models.ScoringRule.id)
            .limit(1)
        )
        if existing is not None:
            return existing
        rule = models.ScoringRule(
            workspace_id=tournament.workspace_id,
            preset="wins",
            game_formula="win",
            end_formula=WINS_END_FORMULA,
        )
        await self.scoring_rule_repo.create(session, rule)
        return rule.id

    async def _upsert_encounter_from_challonge(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        source: _ImportSource,
        match: schemas.ChallongeMatch,
        *,
        match_lookup: _MatchLookup,
        team_lookup: _TeamLookup,
    ) -> _UpsertResult:
        """One match, read then written. ``import_tournament`` runs the two halves itself, so a match that changed
        nothing never opens a savepoint."""
        plan = await self._plan_upsert(
            session, tournament, source, match, match_lookup=match_lookup, team_lookup=team_lookup
        )
        if isinstance(plan, _UpsertResult):
            return plan
        return await self._apply_upsert(session, tournament, source, match, plan, match_lookup=match_lookup)

    async def _plan_upsert(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        source: _ImportSource,
        match: schemas.ChallongeMatch,
        *,
        match_lookup: _MatchLookup,
        team_lookup: _TeamLookup,
    ) -> _UpsertResult | _UpsertPlan:
        """Reads only: an ``error`` or ``skipped`` result, or the plan of a match that will write."""
        encounter = match_lookup.get(source, match.id)
        stage = _resolve_group_for_match(tournament, source, match)
        home_team_id = team_lookup.resolve(source, None, match.player1_id)
        away_team_id = team_lookup.resolve(source, None, match.player2_id)
        missing_team_mapping = tuple(
            challonge_id
            for challonge_id, team_id in (
                (match.player1_id, home_team_id),
                (match.player2_id, away_team_id),
            )
            if challonge_id is not None and team_id is None
        )
        if encounter is None and missing_team_mapping:
            return _UpsertResult(
                action="error",
                error=(
                    "Missing Challonge team mapping for participant(s): "
                    + ", ".join(str(challonge_id) for challonge_id in missing_team_mapping)
                ),
                missing_participant_ids=missing_team_mapping,
            )

        home_team = team_lookup.teams_by_id.get(home_team_id) if home_team_id is not None else None
        away_team = team_lookup.teams_by_id.get(away_team_id) if away_team_id is not None else None
        missing_local_team = [
            str(team_id)
            for team_id, team in (
                (home_team_id, home_team),
                (away_team_id, away_team),
            )
            if team_id is not None and team is None
        ]
        if encounter is None and missing_local_team:
            return _UpsertResult(
                action="error",
                error="Mapped local team(s) not found: " + ", ".join(missing_local_team),
            )

        home_score, away_score = _parse_scores(match.scores_csv)
        status = _encounter_status_from_challonge(match.state)
        refs = await self.structure._resolve_stage_refs_for_match(session, tournament, source, stage, match)
        if encounter is None and home_team_id is not None and away_team_id is not None:
            # A locally generated bracket may already have an Encounter sitting in
            # this exact slot (same stage, round, team pair) with no Challonge
            # mapping yet — adopt it instead of creating a sibling next to it.
            encounter = match_lookup.claim_unlinked(refs.stage_id, match.round, frozenset({home_team_id, away_team_id}))
        names = {
            team_id: team.name
            for team_id, team in ((home_team_id, home_team), (away_team_id, away_team))
            if team_id is not None and team is not None
        }
        teams_mapped = not missing_team_mapping and not missing_local_team
        if encounter is None:
            return _UpsertPlan(
                encounter=None,
                team_ids=(home_team_id, away_team_id),
                scores=(home_score, away_score),
                status=status,
                refs=refs,
                names=names,
                teams_mapped=teams_mapped,
            )

        position = await self.bracket_encounter_repo.get_position(session, encounter.id)
        seats = await active_teams(session, encounter.id)
        after = {
            "id": encounter.id,
            "team_ids": [home_team_id, away_team_id],
            "scores": [float(home_score), float(away_score)],
            "round": match.round,
            "status": status.value,
            "stage_id": refs.stage_id,
            "stage_item_id": refs.stage_item_id,
        }
        name = build_encounter_name([names.get(home_team_id), names.get(away_team_id)])
        seat_teams = {seat.slot: seat.team_id for seat in seats}
        # Everything the update would write is already here -- seats, running
        # scores, status, bracket slot, match mapping: no savepoint, no row lock,
        # no flush, no log row, no recompute. A held result still goes on to
        # report its conflict.
        if (
            encounter.result_status not in _HELD_RESULT_STATUSES
            and encounter.status == status
            and position is not None
            and (position.round, position.stage_id, position.stage_item_id)
            == (match.round, refs.stage_id, refs.stage_item_id)
            and [seat.score for seat in seats] == after["scores"][: len(seats)]
            and (
                not teams_mapped
                or ([seat_teams.get(1), seat_teams.get(2)] == after["team_ids"] and encounter.name == name)
            )
            and (source.source_id is None or (source.source_id, match.id) in match_lookup.mapped_keys)
        ):
            return _UpsertResult(action="skipped", encounter=encounter)
        return _UpsertPlan(
            encounter=encounter,
            team_ids=(home_team_id, away_team_id),
            scores=(home_score, away_score),
            status=status,
            refs=refs,
            names=names,
            teams_mapped=teams_mapped,
            after=after,
        )

    async def _apply_upsert(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        source: _ImportSource,
        match: schemas.ChallongeMatch,
        plan: _UpsertPlan,
        *,
        match_lookup: _MatchLookup,
    ) -> _UpsertResult:
        """The writes of one planned match: create its encounter, or update the existing one under its row lock."""
        encounter = plan.encounter
        home_team_id, away_team_id = plan.team_ids
        home_score, away_score = plan.scores
        status, refs, names = plan.status, plan.refs, plan.names
        if encounter is None:
            initial_status = enums.EncounterStatus.OPEN if status == enums.EncounterStatus.COMPLETED else status
            encounter = models.Encounter(
                name=build_encounter_name([names.get(home_team_id), names.get(away_team_id)]),
                workspace_id=tournament.workspace_id,
                discipline=tournament.discipline,
                tournament_id=tournament.id,
                scoring_rule_id=await self._scoring_rule_id(session, tournament, refs),
                slot_count=2,
                status=initial_status,
            )
            await self.encounter_repo.create(session, encounter)
            await self.bracket_encounter_repo.create(
                session,
                models.BracketEncounter(
                    encounter_id=encounter.id,
                    tournament_id=tournament.id,
                    stage_id=refs.stage_id,
                    stage_item_id=refs.stage_item_id,
                    round=match.round,
                ),
            )
            await _reseat(session, encounter, [home_team_id, away_team_id], names)
            match_lookup.set(source, match.id, encounter)
            # challonge_match_mapping is the sole persistence of the encounter↔match link.
            await self.mapping._ensure_match_mapping(session, source, match.id, encounter, match_lookup)

            newly_completed = status == enums.EncounterStatus.COMPLETED
            if newly_completed:
                # A match can already be complete on the Challonge side the first
                # time we see it (e.g. importing a finished tournament) — route it
                # through the single result writer so ``result_status``,
                # ``confirmed_at``, the journal and ``status`` stay in step
                # (ck_encounter_confirmed_completed).
                await _write_import_result(session, encounter, [home_score, away_score])
            return _UpsertResult(action="created", encounter=encounter, newly_completed=newly_completed)

        after, teams_mapped = plan.after, plan.teams_mapped
        name = build_encounter_name([names.get(home_team_id), names.get(away_team_id)])

        # The background sync races captain submits: the row is ours before any
        # decision is read off it or any seat or standing is written. The plan's
        # reads only decided that something changed; a result a captain committed
        # since then is judged here, on the encounter (``lock_encounter`` re-reads
        # it), seats and position read again under the lock -- never on the plan's.
        await lock_encounter(session, encounter.id)
        position = (
            await session.execute(
                sa.select(models.BracketEncounter)
                .where(models.BracketEncounter.encounter_id == encounter.id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        seats = list(
            (
                await session.execute(
                    sa.select(models.EncounterTeam)
                    .where(models.EncounterTeam.encounter_id == encounter.id, models.EncounterTeam.active.is_(True))
                    .order_by(models.EncounterTeam.slot, models.EncounterTeam.id)
                    .execution_options(populate_existing=True)
                )
            ).scalars()
        )
        was_completed = encounter.status == enums.EncounterStatus.COMPLETED
        has_local_decision = _has_local_decision(encounter)
        before = _encounter_sync_snapshot(encounter, seats, position)
        if has_local_decision:
            local_score = tuple(seat.score for seat in seats)
            remote_score = (float(home_score), float(away_score))
            local_teams = tuple(seat.team_id for seat in seats)
            remote_teams = (home_team_id, away_team_id)
            # A dispute or a half-reported series is a decision in progress: the
            # remote scoreline matching the running tally is no proof it is settled.
            held = encounter.result_status in _HELD_RESULT_STATUSES
            if (
                held
                or status != enums.EncounterStatus.COMPLETED
                or local_score != remote_score
                or (None not in remote_teams and local_teams != remote_teams)
            ):
                await self.mapping._ensure_match_mapping(session, source, match.id, encounter, match_lookup)
                return _UpsertResult(
                    action="conflict",
                    encounter=encounter,
                    conflict_type=(
                        "local_result_held"
                        if held
                        else "local_decided_remote_different"
                        if status == enums.EncounterStatus.COMPLETED
                        else "local_decided_remote_not_completed"
                    ),
                    before=before,
                    after=after,
                )

        teams_changed = False
        if teams_mapped:
            teams_changed = await _reseat(session, encounter, [home_team_id, away_team_id], names)
            encounter.name = name
        if position is None:
            await self.bracket_encounter_repo.create(
                session,
                models.BracketEncounter(
                    encounter_id=encounter.id,
                    tournament_id=tournament.id,
                    stage_id=refs.stage_id,
                    stage_item_id=refs.stage_item_id,
                    round=match.round,
                ),
            )
        else:
            position.round = match.round
            position.stage_id = refs.stage_id
            position.stage_item_id = refs.stage_item_id
        newly_completed = not was_completed and status == enums.EncounterStatus.COMPLETED
        if not newly_completed:
            encounter.status = status
        await session.flush()
        if teams_changed:
            # Challonge corrected a team slot: sync map/hero pick-ban sessions
            # (ensure when both teams are now known, reset a stale existing one)
            # and tell the rosters. No channel post: a sync rewrites a whole
            # bracket at once.
            await after_encounter_teams_changed(session, encounter, channel=False)
        await self.mapping._ensure_match_mapping(session, source, match.id, encounter, match_lookup)

        if newly_completed:
            await _write_import_result(session, encounter, [home_score, away_score])
        else:
            # Not complete remotely: the scoreline is the running tally, so it is
            # materialized onto the seats with no standing result behind it.
            for seat, score in zip(await active_teams(session, encounter.id), (home_score, away_score), strict=False):
                seat.score = float(score)
            await session.flush()

        return _UpsertResult(
            action="updated",
            encounter=encounter,
            before=before,
            after=after,
            newly_completed=newly_completed,
        )

    async def _sync_challonge_advancement_links(
        self,
        session: AsyncSession,
        matches: list[tuple[_ImportSource, schemas.ChallongeMatch]],
        *,
        match_lookup: _MatchLookup,
    ) -> dict[str, int]:
        specs_by_source_position: dict[tuple[int, int, int], _ChallongeLinkSpec] = {}
        sources_by_key = {_source_lookup_key(source): source for source, _match in matches}
        for source, match in matches:
            for spec in _iter_challonge_link_specs(source, match):
                specs_by_source_position[(spec.source_key, spec.source_challonge_id, spec.source_position)] = spec

        if not specs_by_source_position:
            return {"bracket_links_created": 0, "bracket_links_updated": 0}

        source_encounter_ids = [
            encounter.id
            for spec in specs_by_source_position.values()
            if (source := sources_by_key.get(spec.source_key)) is not None
            and (encounter := match_lookup.get(source, spec.source_challonge_id)) is not None
        ]
        if not source_encounter_ids:
            return {"bracket_links_created": 0, "bracket_links_updated": 0}

        existing_by_source_position = {
            (link.source_encounter_id, link.source_position): link
            for link in await self.encounter_link_repo.list_by_source_ids(session, source_encounter_ids)
        }

        new_links: list[models.EncounterLink] = []
        updated = 0
        for spec in specs_by_source_position.values():
            source_ref = sources_by_key.get(spec.source_key)
            if source_ref is None:
                continue
            source = match_lookup.get(source_ref, spec.source_challonge_id)
            target = match_lookup.get(source_ref, spec.target_challonge_id)
            if source is None or target is None:
                continue

            key = (source.id, spec.source_position)
            existing = existing_by_source_position.get(key)
            if existing is None:
                link = models.EncounterLink(
                    tournament_id=source.tournament_id,
                    source_encounter_id=source.id,
                    source_position=spec.source_position,
                    target_encounter_id=target.id,
                    target_slot=spec.target_slot,
                )
                new_links.append(link)
                existing_by_source_position[key] = link
                continue

            if existing.target_encounter_id != target.id or existing.target_slot != spec.target_slot:
                existing.target_encounter_id = target.id
                existing.target_slot = spec.target_slot
                updated += 1

        # One flush for both halves: create_many flushes, which also persists the
        # in-place `updated` mutations above.
        if new_links:
            await self.encounter_link_repo.create_many(session, new_links)
        elif updated:
            await session.flush()

        return {
            "bracket_links_created": len(new_links),
            "bracket_links_updated": updated,
        }

    async def _advance_completed_challonge_matches(
        self,
        session: AsyncSession,
        matches: list[tuple[_ImportSource, schemas.ChallongeMatch]],
        *,
        match_lookup: _MatchLookup,
    ) -> None:
        for source, match in matches:
            if match.state != "complete":
                continue
            encounter = match_lookup.get(source, match.id)
            if encounter is not None:
                await lock_encounter(session, encounter.id)
                # Re-fires advancement for every complete match (idempotent), so it
                # must not re-stamp an existing standing nor replace one decided
                # locally (games, a captain's claim, an admin, or a CONFLICT just
                # reported by ``_upsert_encounter_from_challonge``): ``refresh_from_games``
                # never touches an ``import`` result, so converting one here would
                # make the local decision unrecomputable forever.
                if encounter.result_status != enums.EncounterResultStatus.CONFIRMED:
                    if _has_local_decision(encounter):
                        continue
                    seats = await active_teams(session, encounter.id)
                    await _write_import_result(session, encounter, [seat.score for seat in seats])
                await advance_and_announce(session, encounter, channel=False)

    async def import_tournament(
        self, session: AsyncSession, tournament_id: int, *, dry_run: bool = False, lock_wait_seconds: float = 30.0
    ) -> dict:
        """Full import from Challonge: upsert encounters with scores and status.

        ``lock_wait_seconds`` is how long to wait for an import of this tournament already running before the 409;
        an admin's request passes ``ADMIN_LOCK_WAIT_SECONDS``, the auto-sync keeps the default.
        """
        async with _sync_job_lock(tournament_id, "import", wait_seconds=lock_wait_seconds) as job_id:
            tournament = await self.tournament_repo.get(
                session,
                tournament_id,
                options=[
                    selectinload(models.Tournament.stages)
                    .selectinload(models.Stage.items)
                    .selectinload(models.StageItem.inputs),
                ],
            )
            if not tournament:
                raise HTTPException(status_code=404, detail="Tournament not found")

            sources = await self.mapping.discover_sources(session, tournament)
            if not sources:
                raise HTTPException(status_code=422, detail="Tournament has no Challonge source")

            stats = {
                "job_id": job_id,
                "dry_run": dry_run,
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "conflicts": 0,
                "errors": 0,
                "matches_synced": 0,
                "matches_created": 0,
                "matches_updated": 0,
                "matches_skipped": 0,
                "groups_created": 0,
                "stages_created": 0,
                "stage_inputs_created": 0,
                "bracket_links_created": 0,
                "bracket_links_updated": 0,
            }

            # Release the DB connection before the (potentially slow, rate-limited)
            # Challonge HTTP round-trips: under pgBouncer transaction
            # pooling an open transaction pins a scarce backend slot for the whole
            # network wait, and statement_timeout does not bound idle-in-transaction
            # time. expire_on_commit=False keeps the loaded ``tournament`` (and its
            # eager-loaded relationships) fully usable; the writes below open a
            # fresh, short transaction.
            await session.commit()

            raw_fetches = await _fetch_all_sources(sources)
            fetches: list[tuple[_ImportSource, _SourceFetch]] = []
            for source, fetch_result in raw_fetches:
                if isinstance(fetch_result, Exception):
                    stats["errors"] += 1
                    if not dry_run:
                        await self.sync_log._log_sync(
                            session,
                            tournament_id,
                            "import",
                            "tournament",
                            tournament_id,
                            source.challonge_id,
                            "failed",
                            source_id=source.source_id,
                            operation="fetch_snapshot",
                            error_message=f"{type(fetch_result).__name__}: {fetch_result}",
                        )
                    continue
                try:
                    if not dry_run:
                        structure_stats = await self.structure._ensure_stage_structure_for_matches(
                            session,
                            tournament,
                            source,
                            fetch_result.matches,
                        )
                        stats["groups_created"] += structure_stats["groups_created"]
                        stats["stages_created"] += structure_stats["stages_created"]
                    fetches.append((source, fetch_result))
                except Exception as exc:
                    stats["errors"] += 1
                    logger.exception(
                        "Stage structure failed for challonge_id={} tournament={}",
                        source.challonge_id,
                        tournament_id,
                    )
                    if not dry_run:
                        await self.sync_log._log_sync(
                            session,
                            tournament_id,
                            "import",
                            "tournament",
                            tournament_id,
                            source.challonge_id,
                            "failed",
                            source_id=source.source_id,
                            operation="apply_structure",
                            error_message=f"{type(exc).__name__}: {exc}",
                        )

            source_ids = [source.source_id for source in sources if source.source_id is not None]
            team_lookup = await self.mapping._build_team_lookup(
                session, tournament, fetches, source_ids=source_ids, dry_run=dry_run
            )
            match_lookup = await self.mapping._build_match_lookup(session, sources, tournament_id=tournament.id)

            processed_match_keys: set[tuple[int, int]] = set()
            processed_matches: list[tuple[_ImportSource, schemas.ChallongeMatch]] = []

            for source, fetch in fetches:
                for cm in fetch.matches:
                    match_key = (_source_lookup_key(source), cm.id)
                    if match_key in processed_match_keys:
                        continue
                    processed_match_keys.add(match_key)
                    processed_matches.append((source, cm))

                    if dry_run:
                        existing = match_lookup.get(source, cm.id)
                        if existing is None:
                            stats["created"] += 1
                            stats["matches_created"] += 1
                        elif existing.status == enums.EncounterStatus.COMPLETED:
                            stats["skipped"] += 1
                            stats["matches_skipped"] += 1
                        else:
                            stats["updated"] += 1
                            stats["matches_updated"] += 1
                        continue

                    try:
                        # Reads first, outside any savepoint: an unchanged match (every match of a quiet tick)
                        # costs no SAVEPOINT/RELEASE round trips, and a match that cannot be mapped writes only
                        # its failure row.
                        plan = await self._plan_upsert(
                            session, tournament, source, cm, match_lookup=match_lookup, team_lookup=team_lookup
                        )
                        if isinstance(plan, _UpsertResult) and plan.action == "skipped":
                            stats["skipped"] += 1
                            stats["matches_skipped"] += 1
                            continue
                        if isinstance(plan, _UpsertResult):
                            await self.sync_log._log_sync(
                                session,
                                tournament_id,
                                "import",
                                "match",
                                None,
                                cm.id,
                                "failed",
                                source_id=source.source_id,
                                operation="apply_import",
                                payload=(
                                    {"missing_participant_ids": list(plan.missing_participant_ids)}
                                    if plan.missing_participant_ids
                                    else None
                                ),
                                error_message=plan.error,
                            )
                            stats["errors"] += 1
                            continue
                        # One savepoint per match that writes: a row that fails takes back its own writes, never
                        # the matches around it.
                        async with session.begin_nested():
                            upsert_result = await self._apply_upsert(
                                session, tournament, source, cm, plan, match_lookup=match_lookup
                            )
                            stage_inputs_created = await self.structure._ensure_encounter_stage_inputs(
                                session,
                                tournament,
                                upsert_result.encounter,
                            )
                            if upsert_result.action == "conflict":
                                await self.sync_log._log_sync(
                                    session,
                                    tournament_id,
                                    "import",
                                    "match",
                                    upsert_result.encounter.id if upsert_result.encounter else None,
                                    cm.id,
                                    "conflict",
                                    source_id=source.source_id,
                                    operation="apply_import",
                                    conflict_type=upsert_result.conflict_type,
                                    before=upsert_result.before,
                                    after=upsert_result.after,
                                )
                                stats["conflicts"] += 1
                                stats["matches_skipped"] += 1
                            else:
                                if upsert_result.newly_completed and upsert_result.encounter is not None:
                                    await enqueue_encounter_completed(
                                        session, upsert_result.encounter, source_service="tournament-service"
                                    )
                                await self.sync_log._log_sync(
                                    session,
                                    tournament_id,
                                    "import",
                                    "match",
                                    upsert_result.encounter.id if upsert_result.encounter else None,
                                    cm.id,
                                    "success",
                                    source_id=source.source_id,
                                    operation="apply_import",
                                    payload={
                                        "action": upsert_result.action,
                                        "scores_csv": cm.scores_csv,
                                        "state": cm.state,
                                        "challonge_tournament_id": source.challonge_id,
                                    },
                                    before=upsert_result.before,
                                    after=upsert_result.after,
                                )
                                # Only a real write: it is what requests the recompute and the invalidation below.
                                stats["matches_synced"] += 1
                                stats[upsert_result.action] += 1
                                stats[f"matches_{upsert_result.action}"] += 1
                            stats["stage_inputs_created"] += stage_inputs_created
                    except Exception as exc:
                        stats["errors"] += 1
                        logger.exception(
                            "Match upsert failed challonge_match_id={} tournament={}",
                            cm.id,
                            tournament_id,
                        )
                        # The savepoint took this match's writes back: its encounter is gone or expired, so
                        # the link pass below must not reach it, and whatever else the match had touched
                        # (a stage item's inputs) reloads before the next match reads it.
                        match_lookup.by_source_key.pop((_source_lookup_key(source), cm.id), None)
                        match_lookup.by_challonge_id.pop(cm.id, None)
                        for expired in [obj for obj in session.identity_map.values() if sa_inspect(obj).expired]:
                            await session.refresh(expired)
                        await self.sync_log._log_sync(
                            session,
                            tournament_id,
                            "import",
                            "match",
                            None,
                            cm.id,
                            "failed",
                            source_id=source.source_id,
                            operation="apply_import",
                            error_message=f"{type(exc).__name__}: {exc}",
                        )

            if not dry_run:
                link_stats = await self._sync_challonge_advancement_links(
                    session,
                    processed_matches,
                    match_lookup=match_lookup,
                )
                stats["bracket_links_created"] += link_stats["bracket_links_created"]
                stats["bracket_links_updated"] += link_stats["bracket_links_updated"]
                if link_stats["bracket_links_created"] or link_stats["bracket_links_updated"]:
                    await self._advance_completed_challonge_matches(
                        session,
                        processed_matches,
                        match_lookup=match_lookup,
                    )

                if stats["matches_synced"] > 0:
                    await enqueue_tournament_recalculation(session, tournament_id)

                # Both halves ride the caller's transaction: the auto-sync worker
                # configures cashews and the realtime rail itself, so the local drop
                # lands here, and the outbox row carries it to every other service
                # that caches this.
                resources = _import_invalidated_resources(stats)
                if resources:
                    await publish_tournament_invalidation(session, tournament_id, resources)
                await session.commit()
            logger.info(f"Challonge import for tournament {tournament_id}: {stats}")
            return stats

    # ── Export (local -> Challonge) ──────────────────────────────────────

    async def _resolve_export_target(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        encounter: models.Encounter,
        *,
        sources: list[_ImportSource] | None,
        match_mappings: dict[int, models.ChallongeMatchMapping] | None = None,
    ) -> tuple[_ImportSource | None, int | None]:
        # ``match_mappings`` is an optional bulk prefetch (export path) keyed by
        # encounter_id, so the export loop doesn't issue one mapping query per encounter.
        if match_mappings is not None:
            mapping = match_mappings.get(encounter.id)
        else:
            mapping = await self.match_mapping_repo.get_by(
                session,
                options=[selectinload(models.ChallongeMatchMapping.source)],
                encounter_id=encounter.id,
            )
        if mapping is not None and mapping.source is not None:
            source_row = mapping.source
            return (
                _ImportSource(
                    challonge_id=source_row.challonge_tournament_id,
                    source_id=source_row.id,
                    source_type=source_row.source_type,
                    stage_item_id=source_row.stage_item_id,
                ),
                mapping.challonge_match_id,
            )

        # No challonge_match_mapping: the encounter is not linked to Challonge. Return
        # the best-guess source with no match id — the caller treats a missing match
        # id as "skip".
        if sources is None:
            sources = await self.mapping.discover_sources(session, tournament)
        position = await self.bracket_encounter_repo.get_position(session, encounter.id)
        candidates = [source for source in sources if _source_matches_encounter(source, position)]
        source = candidates[0] if candidates else (sources[0] if len(sources) == 1 else None)
        return source, None

    async def _resolve_winner_challonge_id(
        self,
        session: AsyncSession,
        source: _ImportSource,
        winner_team_id: int,
        encounter: models.Encounter,
        *,
        participant_mappings: dict[tuple[int, int], list[models.ChallongeParticipantMapping]] | None = None,
    ) -> int | None:
        """Resolve the winner's Challonge participant id from ``challonge_participant_mapping``."""
        if source.source_id is None:
            return None

        # ``participant_mappings`` is an optional bulk prefetch (export path) keyed by
        # (source_id, team_id); a missing key falls back to the query so stale mappings
        # referencing undiscovered sources still resolve.
        cached = (
            participant_mappings.get((source.source_id, winner_team_id)) if participant_mappings is not None else None
        )
        if cached is not None:
            source_mappings = cached
        else:
            # The lowest id wins below, so the ORDER BY decides which participant id
            # a multiply-mapped team exports as.
            result = await session.execute(
                self.participant_mapping_repo.select()
                .where(
                    models.ChallongeParticipantMapping.source_id == source.source_id,
                    models.ChallongeParticipantMapping.team_id == winner_team_id,
                )
                .order_by(models.ChallongeParticipantMapping.id.asc())
            )
            source_mappings = list(result.scalars().all())
        if source_mappings:
            return source_mappings[0].challonge_participant_id
        return None

    async def export_tournament(self, session: AsyncSession, tournament_id: int) -> dict:
        """Full export: push all completed encounter results to Challonge. Admin-only, so the short lock wait."""
        async with _sync_job_lock(tournament_id, "export", wait_seconds=ADMIN_LOCK_WAIT_SECONDS) as job_id:
            tournament = await self.tournament_repo.get(
                session,
                tournament_id,
                options=[
                    selectinload(models.Tournament.stages).selectinload(models.Stage.items),
                ],
            )
            if not tournament:
                raise HTTPException(status_code=404, detail="Tournament not found")

            sources = await self.mapping.discover_sources(session, tournament)
            if not sources:
                raise HTTPException(status_code=422, detail="Tournament has no Challonge source")

            stats = {"job_id": job_id, "matches_pushed": 0, "errors": 0, "skipped": 0}
            source_ids = [source.source_id for source in sources if source.source_id is not None]

            # "Linked to Challonge" = has a challonge_match_mapping under this
            # tournament's sources.
            linked_encounter_ids = await self.match_mapping_repo.list_encounter_ids(session, source_ids)
            enc_result = await session.execute(
                self.encounter_repo.select()
                .where(
                    models.Encounter.tournament_id == tournament_id,
                    models.Encounter.status == enums.EncounterStatus.COMPLETED,
                    # Challonge matches are two-sided: a completed lobby has no
                    # two-number scoreline to push, so push_single_result would 409
                    # once per export and fill the sync log with it.
                    models.Encounter.slot_count == 2,
                    models.Encounter.id.in_(tuple(linked_encounter_ids)),
                )
                .options(selectinload(models.Encounter.teams))
            )
            encounters = enc_result.scalars().all()

            # Bulk prefetch of both mapping tables — the loop below would otherwise
            # issue two lookup queries per encounter.
            match_mappings: dict[int, models.ChallongeMatchMapping] = {}
            encounter_ids = [encounter.id for encounter in encounters]
            if encounter_ids:
                # Ordered + first-wins on purpose: an encounter mapped under two
                # sources must always export to the same one.
                mapping_rows = await session.execute(
                    self.match_mapping_repo.select()
                    .where(models.ChallongeMatchMapping.encounter_id.in_(encounter_ids))
                    .options(selectinload(models.ChallongeMatchMapping.source))
                    .order_by(models.ChallongeMatchMapping.id.asc())
                )
                for mapping_row in mapping_rows.scalars():
                    match_mappings.setdefault(mapping_row.encounter_id, mapping_row)

            participant_mappings: dict[tuple[int, int], list[models.ChallongeParticipantMapping]] = {}
            participant_rows = await self.participant_mapping_repo.list_by_source_ids(session, source_ids)
            for participant_row in sorted(participant_rows, key=lambda row: row.id):
                participant_mappings.setdefault((participant_row.source_id, participant_row.team_id), []).append(
                    participant_row
                )

            for encounter in encounters:
                try:
                    pushed = await self.push_single_result(
                        session,
                        tournament,
                        encounter,
                        sources=sources,
                        match_mappings=match_mappings,
                        participant_mappings=participant_mappings,
                    )
                    if pushed:
                        stats["matches_pushed"] += 1
                    else:
                        stats["skipped"] += 1
                except Exception as e:
                    stats["errors"] += 1
                    failed_mapping = match_mappings.get(encounter.id)
                    await self.sync_log._log_sync(
                        session,
                        tournament_id,
                        "export",
                        "match",
                        encounter.id,
                        failed_mapping.challonge_match_id if failed_mapping is not None else None,
                        "failed",
                        operation="push_result",
                        error_message=f"{type(e).__name__}: {e}",
                    )

            await session.commit()
            logger.info(f"Challonge export for tournament {tournament_id}: {stats}")
            return stats

    async def push_single_result(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        encounter: models.Encounter,
        *,
        sources: list[_ImportSource] | None = None,
        match_mappings: dict[int, models.ChallongeMatchMapping] | None = None,
        participant_mappings: dict[tuple[int, int], list[models.ChallongeParticipantMapping]] | None = None,
    ) -> bool:
        """Push a single encounter result to Challonge."""
        source, challonge_match_id = await self._resolve_export_target(
            session, tournament, encounter, sources=sources, match_mappings=match_mappings
        )
        # No challonge_match_mapping → the encounter is not linked to Challonge; skip.
        if source is None or challonge_match_id is None:
            return False

        # Slots 1 and 2 ARE Challonge's participants 1 and 2, in that order.
        seats = await active_teams(session, encounter.id)
        if len(seats) != 2:
            raise ValueError(f"Encounter {encounter.id} does not seat two participations to push")
        first, second = seats

        winner_challonge_id: int | str
        if first.score == second.score:
            # Challonge's documented draw encoding (RR/Swiss).
            winner_challonge_id = "tie"
        else:
            winner_seat = first if first.score > second.score else second
            if winner_seat.team_id is None:
                raise ValueError(f"Encounter {encounter.id} has no winner team")

            resolved = await self._resolve_winner_challonge_id(
                session,
                source,
                winner_seat.team_id,
                encounter,
                participant_mappings=participant_mappings,
            )
            if resolved is None:
                raise ValueError(
                    f"Winner team {winner_seat.team_id} has no Challonge participant mapping "
                    f"for source {source.challonge_id}"
                )
            winner_challonge_id = resolved

        scores_csv = f"{int(first.score)}-{int(second.score)}"

        # Commit (releasing the pgBouncer-backed connection) before the external
        # HTTP call: a transaction held across a rate-limited third-party round-trip
        # pins a pool slot for the whole wait. It also lands export_tournament's
        # mapping writes and _log_sync rows per encounter. Callers commit before
        # invoking the push flow, so nothing unrelated is committed here.
        await session.commit()

        await challonge_client.update_match(
            source.challonge_id,
            challonge_match_id,
            scores_csv=scores_csv,
            winner_id=winner_challonge_id,
        )

        await self.sync_log._log_sync(
            session,
            tournament.id,
            "export",
            "match",
            encounter.id,
            challonge_match_id,
            "success",
            source_id=source.source_id,
            operation="push_result",
            payload={"scores_csv": scores_csv, "winner_challonge_id": winner_challonge_id},
        )
        return True

    async def auto_push_on_confirm(self, session: AsyncSession, encounter_id: int) -> None:
        """Push a confirmed encounter result to Challonge; a no-op for an unlinked one.

        Run by the ``tournament_challonge_push`` consumer and the organizer's manual push. A failure is journaled
        in the sync log (committed) and re-raised, so the caller decides between retry and dead-letter.
        """
        encounter = await self.encounter_repo.get(
            session,
            encounter_id,
            options=[
                selectinload(models.Encounter.tournament),
                selectinload(models.Encounter.tournament)
                .selectinload(models.Tournament.stages)
                .selectinload(models.Stage.items),
                selectinload(models.Encounter.teams),
            ],
        )
        if not encounter:
            return
        # "Linked to Challonge" is derived from challonge_match_mapping.
        challonge_match_id = (await resolve_encounter_challonge(session, [encounter.id])).get(encounter.id)
        if challonge_match_id is None:
            return

        tournament = encounter.tournament
        if not tournament:
            return

        try:
            await self.push_single_result(session, tournament, encounter)
            await session.commit()
            logger.info(f"Auto-pushed encounter {encounter_id} to Challonge")
        except Exception as e:
            logger.error(f"Auto-push failed for encounter {encounter_id}: {e}")
            await self.sync_log._log_sync(
                session,
                tournament.id,
                "export",
                "match",
                encounter.id,
                challonge_match_id,
                "failed",
                error_message=f"{type(e).__name__}: {e}",
            )
            await session.commit()
            raise

    # ── Background auto-sync (Challonge -> local) ────────────────────────

    async def list_active_challonge_tournament_ids(self, session: AsyncSession) -> list[int]:
        """Active tournaments that have a Challonge link, i.e. any ``challonge_source`` row."""
        result = await session.execute(
            sa.select(models.Tournament.id)
            .where(
                models.Tournament.status.in_(ACTIVE_TOURNAMENT_STATUSES),
                self.source_repo.linked_tournament_exists(),
            )
            .order_by(models.Tournament.id.asc())
        )
        return list(result.scalars().all())

    async def sync_active_challonge_tournaments(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> list[dict]:
        """Periodic pull: import every active Challonge-linked tournament.

        Runs in the worker. No-ops when disabled or when credentials are missing (otherwise it would
        spam 401s every interval). Each tournament is imported in its own session — ``import_tournament``
        commits and takes its own Redis lock — so one failure never aborts the rest.
        """
        if not config.settings.challonge_auto_sync_enabled:
            return []
        if not (config.settings.challonge_username and config.settings.challonge_api_key):
            logger.warning("Challonge auto-sync skipped: credentials are not configured")
            return []

        async with session_factory() as session:
            tournament_ids = await self.list_active_challonge_tournament_ids(session)

        results: list[dict] = []
        for tournament_id in tournament_ids:
            async with session_factory() as session:
                try:
                    stats = await self.import_tournament(session, tournament_id)
                    results.append(
                        {
                            "tournament_id": tournament_id,
                            "status": "success",
                            "created": stats.get("created", 0),
                            "updated": stats.get("updated", 0),
                            "conflicts": stats.get("conflicts", 0),
                            "errors": stats.get("errors", 0),
                            "matches_synced": stats.get("matches_synced", 0),
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.exception("Challonge auto-sync failed for tournament {}", tournament_id)
                    results.append(
                        {
                            "tournament_id": tournament_id,
                            "status": "failed",
                            "error": str(exc),
                        }
                    )
        return results


sync_service = ChallongeSyncService()


__all__ = (
    "ACTIVE_TOURNAMENT_STATUSES",
    "ADMIN_LOCK_WAIT_SECONDS",
    "SYNC_LOCK_TTL_SECONDS",
    "ChallongeMappingService",
    "ChallongeStructureService",
    "ChallongeSyncLogService",
    "ChallongeSyncService",
    "close_redis",
    "mapping_service",
    "purge_sync_log",
    "structure_service",
    "sync_log_service",
    "sync_service",
)
