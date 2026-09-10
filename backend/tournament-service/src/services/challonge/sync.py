"""Bidirectional Challonge sync engine.

Import: Challonge -> Local (upsert encounters from Challonge matches)
Export: Local -> Challonge (push encounter results to Challonge)
Auto-push: triggered when encounter result_status becomes 'confirmed'

Four classes rather than one, split by responsibility (the "split by feature"
case in ``backend/ARCHITECTURE.md``): ``ChallongeSyncLogService`` owns the
``challonge_sync_log`` audit trail, ``ChallongeStructureService`` creates the
local stage/group/stage-item/stage-input rows a Challonge bracket implies,
``ChallongeMappingService`` owns source discovery and the Challonge-id <-> local-id
mapping tables, and ``ChallongeSyncService`` — the exported ``sync_service`` — is
the public orchestration (import, export, push, auto-sync). Everything pure
(the value dataclasses, score parsing, name normalization, the loaded-collection
probes) stays module-level; forcing a class onto it is the anti-pattern the
app-service correction pass walked back.
"""

import asyncio
import re
import traceback
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime

import sqlalchemy as sa
from loguru import logger
from redis import asyncio as redis_async
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from shared.core import enums
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import (
    ChallongeMatchMappingRepository,
    ChallongeParticipantMappingRepository,
    ChallongeSourceRepository,
    ChallongeSyncLogRepository,
    EncounterLinkRepository,
    EncounterRepository,
    StageItemInputRepository,
    StageItemRepository,
    StageRepository,
    TeamRepository,
    TournamentRepository,
)
from shared.services.challonge_refs import resolve_encounter_challonge
from shared.services.distributed_lock import distributed_lock
from shared.services.encounter.result_audit import record_result_transition
from shared.services.encounter_naming import build_encounter_name
from shared.services.realtime import Resource
from shared.services.stage_refs import StageRefs, resolve_stage_refs_from_group
from src import models, schemas
from src.clients.challonge import challonge_client
from src.core import config
from src.services.encounter.finalize import finalize_service
from src.services.encounter.pick_ban_session import pick_ban_session_service
from src.services.team.service import team_service
from src.services.tournament.events import (
    RESULT_RESOURCES,
    STRUCTURE_RESOURCES,
    enqueue_encounter_completed,
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
    # locally (``StageService.generate_encounters``) before this Challonge
    # source was ever imported. Keyed by (stage_id, round, {home, away}); claimed
    # (popped) the first time a Challonge match resolves to that same slot, so
    # import adopts and links the existing row instead of creating a duplicate
    # sibling next to it.
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
    # can emit EncounterCompletedEvent — which the import used to skip entirely,
    # leaving imported results without achievement/MVP recalculation.
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
class _ChallongeLinkSpec:
    source_key: int
    source_challonge_id: int
    target_challonge_id: int
    role: enums.EncounterLinkRole
    target_slot: enums.EncounterLinkSlot


SYNC_LOCK_TTL_SECONDS = 5 * 60

# "Active" = matches are in play. Kept as a module constant so the set is easy to widen.
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
async def _sync_job_lock(tournament_id: int, direction: str) -> AsyncIterator[str]:
    redis = await _get_redis()
    key = f"challonge:sync:{tournament_id}:{direction}"
    async with distributed_lock(redis, key, ttl_seconds=SYNC_LOCK_TTL_SECONDS) as token:
        yield token.value


def _encounter_status_from_challonge(state: str) -> enums.EncounterStatus:
    if state == "complete":
        return enums.EncounterStatus.COMPLETED
    if state == "pending":
        return enums.EncounterStatus.PENDING
    return enums.EncounterStatus.OPEN


def _parse_scores(scores_csv: str | None) -> tuple[int, int]:
    match = _SCORE_RE.search(scores_csv or "")
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


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
    """Find the stage that owns a Challonge group, by its `settings_json` marker.

    `settings_json["challonge_group_id"]` is the ONLY link: the `tournament.group`
    table this used to fall back to (`tournament.groups`, matched on
    `group.challonge_id`) was dropped with its ORM model, so that fallback raised
    `AttributeError` instead of returning None -- and it ran on the very first
    import of a grouped bracket, before any stage carries the marker, i.e. exactly
    when the caller was about to create the missing group stage.
    """
    for stage in tournament.stages or []:
        if (stage.settings_json or {}).get("challonge_group_id") == challonge_group_id:
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


def _encounter_sync_snapshot(encounter: models.Encounter) -> dict:
    return {
        "id": encounter.id,
        "home_team_id": encounter.home_team_id,
        "away_team_id": encounter.away_team_id,
        "home_score": encounter.home_score,
        "away_score": encounter.away_score,
        "round": encounter.round,
        "status": encounter.status.value if hasattr(encounter.status, "value") else encounter.status,
        "stage_id": encounter.stage_id,
        "stage_item_id": encounter.stage_item_id,
    }


def _has_local_decision(encounter: models.Encounter) -> bool:
    """Whether a local result outranks whatever Challonge is reporting.

    Keyed on ``result_status``, not just ``status``: a dispute or a half-reported
    result is a decision in progress, and silently overwriting it destroyed the
    captains' evidence and the admin's pending call.
    """
    return encounter.status == enums.EncounterStatus.COMPLETED or encounter.result_status in (
        enums.EncounterResultStatus.CONFIRMED,
        enums.EncounterResultStatus.DISPUTED,
        enums.EncounterResultStatus.PENDING_CONFIRMATION,
    )


def _iter_challonge_link_specs(
    source: _ImportSource,
    match: schemas.ChallongeMatch,
) -> list[_ChallongeLinkSpec]:
    specs: list[_ChallongeLinkSpec] = []
    source_key = _source_lookup_key(source)
    for prereq_id, is_loser, slot in (
        (
            match.player1_prereq_match_id,
            match.player1_is_prereq_match_loser,
            enums.EncounterLinkSlot.HOME,
        ),
        (
            match.player2_prereq_match_id,
            match.player2_is_prereq_match_loser,
            enums.EncounterLinkSlot.AWAY,
        ),
    ):
        if prereq_id is None or prereq_id == match.id:
            continue
        specs.append(
            _ChallongeLinkSpec(
                source_key=source_key,
                source_challonge_id=prereq_id,
                target_challonge_id=match.id,
                role=(enums.EncounterLinkRole.LOSER if is_loser else enums.EncounterLinkRole.WINNER),
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


def _source_matches_encounter(source: _ImportSource, encounter: models.Encounter) -> bool:
    if source.stage_item_id is not None and encounter.stage_item_id == source.stage_item_id:
        return True
    if source.stage is not None and encounter.stage_id == source.stage.id:
        return True
    return source.source_type == "tournament"


class ChallongeSyncLogService:
    """The ``challonge_sync_log`` audit trail: every import/export attempt.

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
    ) -> None:
        self.stage_repo = stage_repo
        self.stage_item_repo = stage_item_repo
        self.stage_item_input_repo = stage_item_input_repo

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
        # Stage-level Challonge identity now lives in ``challonge_source`` (derived at
        # read time), so the deprecated ``stage.challonge_id``/``challonge_slug``
        # columns are no longer written here.
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
            stage.settings_json = {**(stage.settings_json or {}), "challonge_group_id": challonge_id}
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
                existing_id = (source.stage.settings_json or {}).get("challonge_group_id")
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
                if (stage.settings_json or {}).get("challonge_group_id") != group_id:
                    stage.settings_json = {**(stage.settings_json or {}), "challonge_group_id": group_id}
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
        return await self._ensure_stage_item_team_inputs(
            session,
            tournament,
            stage_item_id=encounter.stage_item_id,
            team_ids=[encounter.home_team_id, encounter.away_team_id],
        )


structure_service = ChallongeStructureService()


class ChallongeMappingService:
    """Source discovery plus the Challonge-id <-> local-id mapping tables.

    ``challonge_source`` is the single source of truth for "this tournament is
    mirrored on Challonge"; ``challonge_participant_mapping`` and
    ``challonge_match_mapping`` translate Challonge's participant/match ids to
    local team/encounter ids under one source. The legacy ``challonge_team``
    table and the deprecated ``*.challonge_id`` columns are no longer consulted.
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

    async def discover_sources(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        *,
        dry_run: bool = False,
    ) -> list[_ImportSource]:
        """Discover Challonge sources from the normalized ``challonge_source`` table.

        Reads exclusively from ``challonge_source`` — the deprecated
        ``tournament``/``stage``/``group`` ``challonge_id`` columns are no longer
        consulted. Stage already comes from ``ChallongeSource.stage``.
        ``dry_run`` is accepted for signature compatibility; no rows are ever
        written here now (the admin link entry-point owns source creation).
        """
        del dry_run  # sources are no longer lazily created from legacy columns
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

        The mapping table is now the SOLE persistence target (the legacy
        ``challonge_team`` table is no longer written). Existing mappings always win;
        ambiguous name matches are skipped. Both the participant id and every
        ``group_player_id`` alias are mapped, scoped to the source.
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
        # ``source_ids`` is every discovered source of this tournament, so this is
        # the same row set the old ChallongeSource join produced — including
        # sources whose fetch failed, whose mappings still feed the cross-source
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
        # Filtering on the discovered source ids directly is the same row set the
        # old ChallongeSource join produced, one table lighter.
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

        # A bracket generated locally (StageService.generate_encounters) before this
        # source was ever imported already has real Encounter rows occupying the
        # bracket's slots -- with no challonge_match_mapping, since nothing has
        # linked them to a Challonge match yet. Without this index the create-path
        # below cannot see them and lays a second, competing Encounter over the
        # same slot every run. Matched by (stage, round, team pair) once both teams
        # are known; TBD slots are left for the create-path, there is nothing to
        # match yet.
        unlinked_by_slot: dict[tuple[int | None, int, frozenset[int]], models.Encounter] = {}
        encounters_result = await session.execute(
            sa.select(models.Encounter).where(
                models.Encounter.tournament_id == tournament_id,
                models.Encounter.home_team_id.is_not(None),
                models.Encounter.away_team_id.is_not(None),
            )
        )
        for encounter in encounters_result.scalars().all():
            if encounter.id in mapped_encounter_ids:
                continue
            key = (
                encounter.stage_id,
                encounter.round,
                frozenset({encounter.home_team_id, encounter.away_team_id}),
            )
            unlinked_by_slot.setdefault(key, encounter)

        # Existing encounters are located via challonge_match_mapping (by_source_key)
        # only — the deprecated encounter.challonge_id column is no longer consulted.
        # by_challonge_id stays as an in-run cache populated by _MatchLookup.set for
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
            # Map every alias here too, or matches never resolve a team even
            # though the admin explicitly picked one for this participant --
            # mirrors `_auto_map_participants`, which already does this for
            # name-matched rows.
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
        if encounter is None:
            initial_status = enums.EncounterStatus.OPEN if status == enums.EncounterStatus.COMPLETED else status
            encounter = models.Encounter(
                name=build_encounter_name(
                    home_team.name if home_team is not None else None,
                    away_team.name if away_team is not None else None,
                ),
                home_team_id=home_team_id,
                away_team_id=away_team_id,
                home_score=home_score,
                away_score=away_score,
                round=match.round,
                tournament_id=tournament.id,
                stage_id=refs.stage_id,
                stage_item_id=refs.stage_item_id,
                status=initial_status,
            )
            await self.encounter_repo.create(session, encounter)
            match_lookup.set(source, match.id, encounter)
            # challonge_match_mapping is the sole persistence of the encounter↔match
            # link now (the legacy encounter.challonge_id column is no longer written).
            await self.mapping._ensure_match_mapping(session, source, match.id, encounter, match_lookup)

            newly_completed = status == enums.EncounterStatus.COMPLETED
            if newly_completed:
                # A match can already be complete on the Challonge side the first
                # time we see it (e.g. importing a finished tournament) — route it
                # through the same finalize+audit path as a live completion so
                # ``result_status``/``confirmed_at`` and bracket advancement stay in
                # sync with ``status`` (ck_encounter_result_status_matches_status).
                await finalize_service.finalize_encounter_score(
                    session,
                    encounter.id,
                    encounter=encounter,
                    home_score=home_score,
                    away_score=away_score,
                    source="challonge",
                    result_status=enums.EncounterResultStatus.CONFIRMED,
                    confirmed_at=datetime.now(UTC),
                )
                record_result_transition(
                    session,
                    encounter,
                    action=enums.EncounterResultAuditAction.IMPORT,
                    source="challonge",
                    actor_user_id=None,
                    from_result_status=enums.EncounterResultStatus.NONE,
                    home_score_before=None,
                    away_score_before=None,
                )
            return _UpsertResult(action="created", encounter=encounter, newly_completed=newly_completed)

        was_completed = encounter.status == enums.EncounterStatus.COMPLETED
        has_local_decision = _has_local_decision(encounter)
        before = _encounter_sync_snapshot(encounter)
        after = {
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "home_score": home_score,
            "away_score": away_score,
            "round": match.round,
            "status": status.value,
            "stage_id": refs.stage_id,
            "stage_item_id": refs.stage_item_id,
        }
        if has_local_decision:
            local_score = (encounter.home_score, encounter.away_score)
            remote_score = (home_score, away_score)
            local_teams = (encounter.home_team_id, encounter.away_team_id)
            remote_teams = (home_team_id, away_team_id)
            if (
                status != enums.EncounterStatus.COMPLETED
                or local_score != remote_score
                or (None not in remote_teams and local_teams != remote_teams)
            ):
                await self.mapping._ensure_match_mapping(session, source, match.id, encounter, match_lookup)
                return _UpsertResult(
                    action="conflict",
                    encounter=encounter,
                    conflict_type=(
                        "local_decided_remote_different"
                        if status == enums.EncounterStatus.COMPLETED
                        else "local_decided_remote_not_completed"
                    ),
                    before=before,
                    after=after,
                )

        teams_changed = False
        if not missing_team_mapping and not missing_local_team:
            teams_changed = (encounter.home_team_id, encounter.away_team_id) != (home_team_id, away_team_id)
            encounter.name = build_encounter_name(
                home_team.name if home_team is not None else None,
                away_team.name if away_team is not None else None,
            )
            encounter.home_team_id = home_team_id
            encounter.away_team_id = away_team_id
        encounter.home_score = home_score
        encounter.away_score = away_score
        encounter.round = match.round
        encounter.stage_id = refs.stage_id
        encounter.stage_item_id = refs.stage_item_id
        newly_completed = not was_completed and status == enums.EncounterStatus.COMPLETED
        if not newly_completed:
            encounter.status = status
        await session.flush()
        if teams_changed:
            # Challonge corrected a team slot: sync map/hero pick-ban sessions
            # (ensure when both teams are now known, reset a stale existing one).
            await pick_ban_session_service.sync_all_pick_ban_sessions_after_team_change(session, encounter)
        await self.mapping._ensure_match_mapping(session, source, match.id, encounter, match_lookup)

        if newly_completed:
            from_result_status = encounter.result_status
            home_score_before, away_score_before = before.get("home_score"), before.get("away_score")
            await finalize_service.finalize_encounter_score(
                session,
                encounter.id,
                encounter=encounter,
                home_score=encounter.home_score,
                away_score=encounter.away_score,
                source="challonge",
                result_status=enums.EncounterResultStatus.CONFIRMED,
                confirmed_at=datetime.now(UTC),
            )
            # actor_user_id stays NULL: an external system decided this, and that is
            # exactly what distinguishes it from an admin resolution in the trail.
            record_result_transition(
                session,
                encounter,
                action=enums.EncounterResultAuditAction.IMPORT,
                source="challonge",
                actor_user_id=None,
                from_result_status=from_result_status,
                home_score_before=home_score_before,
                away_score_before=away_score_before,
            )

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
        specs_by_source_role: dict[
            tuple[int, int, enums.EncounterLinkRole],
            _ChallongeLinkSpec,
        ] = {}
        sources_by_key = {_source_lookup_key(source): source for source, _match in matches}
        for source, match in matches:
            for spec in _iter_challonge_link_specs(source, match):
                specs_by_source_role[(spec.source_key, spec.source_challonge_id, spec.role)] = spec

        if not specs_by_source_role:
            return {"bracket_links_created": 0, "bracket_links_updated": 0}

        source_encounter_ids = [
            encounter.id
            for spec in specs_by_source_role.values()
            if (source := sources_by_key.get(spec.source_key)) is not None
            and (encounter := match_lookup.get(source, spec.source_challonge_id)) is not None
        ]
        if not source_encounter_ids:
            return {"bracket_links_created": 0, "bracket_links_updated": 0}

        existing_by_source_role = {
            (link.source_encounter_id, link.role): link
            for link in await self.encounter_link_repo.list_by_source_ids(session, source_encounter_ids)
        }

        new_links: list[models.EncounterLink] = []
        updated = 0
        for spec in specs_by_source_role.values():
            source_ref = sources_by_key.get(spec.source_key)
            if source_ref is None:
                continue
            source = match_lookup.get(source_ref, spec.source_challonge_id)
            target = match_lookup.get(source_ref, spec.target_challonge_id)
            if source is None or target is None:
                continue

            key = (source.id, spec.role)
            existing = existing_by_source_role.get(key)
            if existing is None:
                link = models.EncounterLink(
                    source_encounter_id=source.id,
                    target_encounter_id=target.id,
                    role=spec.role,
                    target_slot=spec.target_slot,
                )
                new_links.append(link)
                existing_by_source_role[key] = link
                continue

            if existing.target_encounter_id != target.id or existing.target_slot != spec.target_slot:
                existing.target_encounter_id = target.id
                existing.target_slot = spec.target_slot
                updated += 1

        # One flush for both halves, exactly as before: create_many flushes, which
        # also persists the in-place `updated` mutations above.
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
                # Re-fires advancement for every complete match (idempotent), so it
                # must not re-stamp result_status or append a second audit row for
                # an encounter that is already settled.
                already_confirmed = encounter.result_status == enums.EncounterResultStatus.CONFIRMED
                await finalize_service.finalize_encounter_score(
                    session,
                    encounter.id,
                    encounter=encounter,
                    home_score=encounter.home_score,
                    away_score=encounter.away_score,
                    source="challonge",
                    result_status=None if already_confirmed else enums.EncounterResultStatus.CONFIRMED,
                    confirmed_at=None if already_confirmed else datetime.now(UTC),
                )
                if not already_confirmed:
                    record_result_transition(
                        session,
                        encounter,
                        action=enums.EncounterResultAuditAction.IMPORT,
                        source="challonge",
                        actor_user_id=None,
                    )

    async def import_tournament(self, session: AsyncSession, tournament_id: int, *, dry_run: bool = False) -> dict:
        """Full import from Challonge: upsert encounters with scores and status."""
        async with _sync_job_lock(tournament_id, "import") as job_id:
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
                return {"job_id": job_id, "error": "Tournament not found"}

            sources = await self.mapping.discover_sources(session, tournament, dry_run=dry_run)
            if not sources:
                return {"job_id": job_id, "error": "Tournament has no Challonge source"}

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
                            error_message=str(fetch_result),
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
                except Exception:
                    stats["errors"] += 1
                    tb = traceback.format_exc()
                    logger.exception(
                        "Stage structure failed for challonge_id=%s tournament=%s",
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
                            error_message=tb,
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
                        upsert_result = await self._upsert_encounter_from_challonge(
                            session,
                            tournament,
                            source,
                            cm,
                            match_lookup=match_lookup,
                            team_lookup=team_lookup,
                        )
                        if upsert_result.action == "error":
                            stats["errors"] += 1
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
                                    {"missing_participant_ids": list(upsert_result.missing_participant_ids)}
                                    if upsert_result.missing_participant_ids
                                    else None
                                ),
                                error_message=upsert_result.error,
                            )
                            continue
                        if upsert_result.action == "conflict":
                            stats["stage_inputs_created"] += await self.structure._ensure_encounter_stage_inputs(
                                session,
                                tournament,
                                upsert_result.encounter,
                            )
                            stats["conflicts"] += 1
                            stats["matches_skipped"] += 1
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
                            continue
                        if upsert_result.action == "skipped":
                            stats["skipped"] += 1
                            stats["matches_skipped"] += 1
                            continue

                        stats["matches_synced"] += 1
                        stats["stage_inputs_created"] += await self.structure._ensure_encounter_stage_inputs(
                            session,
                            tournament,
                            upsert_result.encounter,
                        )
                        if upsert_result.action == "created":
                            stats["created"] += 1
                            stats["matches_created"] += 1
                        else:
                            stats["updated"] += 1
                            stats["matches_updated"] += 1
                        if upsert_result.newly_completed and upsert_result.encounter is not None:
                            await enqueue_encounter_completed(session, upsert_result.encounter)

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
                    except Exception:
                        stats["errors"] += 1
                        tb = traceback.format_exc()
                        logger.exception(
                            "Match upsert failed challonge_match_id=%s tournament=%s",
                            cm.id,
                            tournament_id,
                        )
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
                            error_message=tb,
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

                # Both halves ride the caller's transaction: the worker process
                # that runs auto-sync configures cashews and the realtime rail
                # itself now, so the local drop lands here, and the outbox row
                # still carries it to every other service that caches this.
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
        # encounter_id — mirrors the import path's _build_match_lookup pattern so
        # the export loop doesn't issue one mapping query per encounter.
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

        # No challonge_match_mapping for this encounter: it is not linked to Challonge
        # (the deprecated encounter.challonge_id fallback is no longer consulted, so
        # there is no match id to resolve). Return the best-guess source with no match
        # id — the caller treats a missing match id as "skip".
        if sources is None:
            sources = await self.mapping.discover_sources(session, tournament)
        candidates = [source for source in sources if _source_matches_encounter(source, encounter)]
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
        """Resolve the winner's Challonge participant id from
        ``challonge_participant_mapping`` (the legacy ``challonge_team`` fallback is
        no longer consulted)."""
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
            # Kept as a two-column filtered read rather than list_by_source(...):
            # the lowest id wins below, so the ORDER BY is part of which participant
            # id a multiply-mapped team exports as.
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
        """Full export: push all completed encounter results to Challonge."""
        async with _sync_job_lock(tournament_id, "export") as job_id:
            tournament = await self.tournament_repo.get(
                session,
                tournament_id,
                options=[
                    selectinload(models.Tournament.stages).selectinload(models.Stage.items),
                ],
            )
            if not tournament:
                return {"job_id": job_id, "error": "Tournament not found"}

            sources = await self.mapping.discover_sources(session, tournament)
            if not sources:
                return {"job_id": job_id, "error": "Tournament has no Challonge source"}

            stats = {"job_id": job_id, "matches_pushed": 0, "errors": 0, "skipped": 0}
            source_ids = [source.source_id for source in sources if source.source_id is not None]

            # "Linked to Challonge" is now derived from challonge_match_mapping (scoped
            # to this tournament's sources), not the deprecated encounter.challonge_id.
            linked_encounter_ids = await self.match_mapping_repo.list_encounter_ids(session, source_ids)
            enc_result = await session.execute(
                self.encounter_repo.select()
                .where(
                    models.Encounter.tournament_id == tournament_id,
                    models.Encounter.status == enums.EncounterStatus.COMPLETED,
                    models.Encounter.id.in_(tuple(linked_encounter_ids)),
                )
                .options(
                    selectinload(models.Encounter.home_team),
                    selectinload(models.Encounter.away_team),
                )
            )
            encounters = enc_result.scalars().all()

            # Bulk prefetch of both mapping tables (same batching pattern as the
            # import path's _build_team_lookup/_build_match_lookup) — the loop below
            # would otherwise issue two lookup queries per encounter.
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
                        error_message=str(e),
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

        winner_team = encounter.home_team if encounter.home_score > encounter.away_score else encounter.away_team
        if not winner_team:
            raise ValueError(f"Encounter {encounter.id} has no winner team")

        winner_challonge_id = await self._resolve_winner_challonge_id(
            session,
            source,
            winner_team.id,
            encounter,
            participant_mappings=participant_mappings,
        )
        if winner_challonge_id is None:
            raise ValueError(
                f"Winner team {winner_team.id} has no Challonge participant mapping for source {source.challonge_id}"
            )

        scores_csv = f"{encounter.home_score}-{encounter.away_score}"

        # Commit (and thereby release the pgBouncer-backed connection) before the
        # external HTTP call: holding a transaction open across a third-party,
        # rate-limited API round-trip pins a pool slot for the whole wait. This also
        # gives export_tournament per-encounter commit granularity — resolve-target
        # mapping writes and prior _log_sync rows land incrementally instead of in
        # one giant end-of-loop transaction. Callers commit before invoking the
        # push flow, so nothing unrelated can be committed here.
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
        """Auto-push to Challonge when an encounter result is confirmed.

        Called from captain.submit_captain_report / set_encounter_result once the
        encounter result becomes confirmed.
        """
        encounter = await self.encounter_repo.get(
            session,
            encounter_id,
            options=[
                selectinload(models.Encounter.tournament),
                selectinload(models.Encounter.tournament)
                .selectinload(models.Tournament.stages)
                .selectinload(models.Stage.items),
                selectinload(models.Encounter.home_team),
                selectinload(models.Encounter.away_team),
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
                error_message=str(e),
            )
            await session.commit()

    # ── Background auto-sync (Challonge -> local) ────────────────────────

    async def list_active_challonge_tournament_ids(self, session: AsyncSession) -> list[int]:
        """Active tournaments that have a Challonge link, i.e. any ``challonge_source`` row.

        The normalized ``challonge_source`` table is the single source of truth for
        the tournament↔Challonge link, so the deprecated ``tournament``/``stage``/
        ``group`` ``challonge_id`` columns are no longer consulted.
        """
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
                    logger.exception("Challonge auto-sync failed for tournament %s", tournament_id)
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
    "SYNC_LOCK_TTL_SECONDS",
    "ChallongeMappingService",
    "ChallongeStructureService",
    "ChallongeSyncLogService",
    "ChallongeSyncService",
    "close_redis",
    "mapping_service",
    "structure_service",
    "sync_log_service",
    "sync_service",
)
