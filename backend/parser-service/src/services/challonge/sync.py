"""Bidirectional Challonge sync engine.

Import: Challonge -> Local (upsert encounters from Challonge matches)
Export: Local -> Challonge (push encounter results to Challonge)
Auto-push: triggered when encounter result_status becomes 'confirmed'
"""

import asyncio
import re
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from loguru import logger
from redis import asyncio as redis_async
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import enums
from shared.services.challonge_refs import resolve_encounter_challonge
from shared.services.distributed_lock import distributed_lock
from shared.services.encounter_naming import build_encounter_name
from shared.services.stage_refs import StageRefs, resolve_stage_refs_from_group
from src import models, schemas
from src.core import config
from src.services.challonge import service as challonge_service
from src.services.encounter.finalize import finalize_encounter_score
from src.services.standings import recalculation as standings_recalculation

_AMBIGUOUS = -1
_SCORE_RE = re.compile(r"\s*(-?\d+)\s*-\s*(-?\d+)")


@dataclass(frozen=True)
class _ImportSource:
    challonge_id: int
    source_id: int | None = None
    source_type: str = "tournament"
    stage: models.Stage | None = None
    group: models.TournamentGroup | None = None
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

    def get(self, source: _ImportSource, challonge_match_id: int) -> models.Encounter | None:
        if (encounter := self.by_source_key.get((_source_lookup_key(source), challonge_match_id))) is not None:
            return encounter
        return self.by_challonge_id.get(challonge_match_id)

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
    before: dict | None = None
    after: dict | None = None
    error: str | None = None


@dataclass(frozen=True)
class _ChallongeLinkSpec:
    source_key: int
    source_challonge_id: int
    target_challonge_id: int
    role: enums.EncounterLinkRole
    target_slot: enums.EncounterLinkSlot


SYNC_LOCK_TTL_SECONDS = 5 * 60

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


async def _log_sync(
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
    session.add(entry)
    await session.flush()
    return entry


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

    from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415

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


async def discover_sources(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    dry_run: bool = False,
) -> list[_ImportSource]:
    """Discover Challonge sources from the normalized ``challonge_source`` table.

    Reads exclusively from ``challonge_source`` — the deprecated
    ``tournament``/``stage`` ``challonge_id`` columns are no longer consulted.
    Group/playoff sources are linked back to their ``TournamentGroup`` via
    ``stage_id`` (the only join available; ``challonge_source`` is scoped by
    ``stage_id``, never ``group_id``) so downstream match-routing keeps working.
    ``dry_run`` is accepted for signature compatibility; no rows are ever written
    here now (the admin link / import entry-points own source creation).
    """
    del dry_run  # sources are no longer lazily created from legacy columns
    result = await session.execute(
        select(models.ChallongeSource)
        .where(models.ChallongeSource.tournament_id == tournament.id)
        .options(
            selectinload(models.ChallongeSource.stage)
            .selectinload(models.Stage.items)
            .selectinload(models.StageItem.inputs),
            selectinload(models.ChallongeSource.stage_item),
        )
        .order_by(models.ChallongeSource.id.asc())
    )
    source_rows = list(result.scalars().all())
    if not source_rows:
        return []

    # Resolve the TournamentGroup for group/playoff sources through stage_id.
    group_stage_ids = [
        row.stage_id for row in source_rows if row.stage_id is not None and row.source_type in ("group", "playoff")
    ]
    groups_by_stage_id: dict[int, models.TournamentGroup] = {}
    if group_stage_ids:
        group_result = await session.execute(
            select(models.TournamentGroup).where(models.TournamentGroup.stage_id.in_(group_stage_ids))
        )
        for group in group_result.scalars().all():
            if group.stage_id is not None:
                groups_by_stage_id.setdefault(group.stage_id, group)

    sources: list[_ImportSource] = []
    for row in source_rows:
        group = (
            groups_by_stage_id.get(row.stage_id)
            if row.source_type in ("group", "playoff") and row.stage_id is not None
            else None
        )
        sources.append(
            _ImportSource(
                challonge_id=row.challonge_tournament_id,
                source_id=row.id,
                source_type=row.source_type,
                stage=row.stage,
                group=group,
                stage_item_id=row.stage_item_id or _first_loaded_stage_item_id(row.stage),
                slug=row.slug,
            )
        )

    return sources


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


async def _ensure_stage_item(
    session: AsyncSession,
    stage: models.Stage,
    *,
    name: str,
    item_type: enums.StageItemType,
) -> models.StageItem:
    from sqlalchemy import inspect as sa_inspect  # noqa: PLC0415

    # If items are not loaded in this session state, query them async to avoid
    # triggering a synchronous lazy-load (MissingGreenlet) in an async context.
    try:
        items_unloaded = "items" in sa_inspect(stage).unloaded
    except Exception:
        items_unloaded = False

    if items_unloaded:
        from sqlalchemy import select as sa_select  # noqa: PLC0415

        result = await session.execute(
            sa_select(models.StageItem)
            .where(models.StageItem.stage_id == stage.id)
            .order_by(models.StageItem.order.asc(), models.StageItem.id.asc())
        )
        existing = result.scalars().all()
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
    session.add(item)
    await session.flush()
    if not items_unloaded:
        stage.items.append(item)
    return item


async def _create_stage_with_item(
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
    session.add(stage)
    await session.flush()
    _append_once(tournament.stages, stage)
    item = models.StageItem(
        stage_id=stage.id,
        name=name,
        type=item_type,
        order=0,
    )
    item.inputs = []
    session.add(item)
    await session.flush()
    try:
        _append_once(stage.items, item)
    except Exception:
        pass
    return stage


async def _ensure_group_stage(
    session: AsyncSession,
    tournament: models.Tournament,
    group: models.TournamentGroup,
    *,
    stage_type: enums.StageType,
    item_type: enums.StageItemType,
) -> None:
    stage = getattr(group, "stage", None)
    group_name = getattr(
        group,
        "name",
        "Group" if getattr(group, "is_groups", False) else "Playoffs",
    )
    if stage is None:
        stage = await _create_stage_with_item(
            session,
            tournament,
            name=group_name,
            description=getattr(group, "description", None),
            stage_type=stage_type,
            item_type=item_type,
        )
        group.stage = stage
        group.stage_id = stage.id
        await session.flush()
        return

    if stage not in (tournament.stages or []):
        _append_once(tournament.stages, stage)
    await _ensure_stage_item(
        session,
        stage,
        name=group_name,
        item_type=item_type,
    )


async def _create_group_with_stage(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    name: str,
    is_groups: bool,
    challonge_id: int | None,
    challonge_slug: str | None,
    stage_type: enums.StageType,
) -> models.TournamentGroup:
    stage = await _create_stage_with_item(
        session,
        tournament,
        name=name,
        description=None,
        stage_type=stage_type,
        item_type=_stage_item_type_for_stage(stage_type),
    )
    # ``group.challonge_id``/``challonge_slug`` are retained deliberately (the
    # group exception): ``challonge_id`` stores Challonge's per-group
    # ``match.group_id`` used to route matches to the local group (see
    # ``_resolve_group_for_match``) and has no ``challonge_source`` equivalent.
    group = models.TournamentGroup(
        tournament_id=tournament.id,
        name=name,
        description=None,
        is_groups=is_groups,
        challonge_id=challonge_id,
        challonge_slug=challonge_slug,
        stage_id=stage.id,
    )
    group.stage = stage
    session.add(group)
    await session.flush()
    _append_once(tournament.groups, group)
    return group


def _group_names_for_challonge_ids(group_ids: set[int]) -> dict[int, str]:
    names: dict[int, str] = {}
    for index, group_id in enumerate(sorted(group_ids), start=1):
        codepoint = 64 + index
        names[group_id] = chr(codepoint) if codepoint <= 90 else f"Group {index}"
    return names


def _find_playoff_group(
    tournament: models.Tournament,
) -> models.TournamentGroup | None:
    return next((group for group in tournament.groups or [] if not group.is_groups), None)


async def _ensure_stage_structure_for_matches(
    session: AsyncSession,
    tournament: models.Tournament,
    source: _ImportSource,
    matches: list[schemas.ChallongeMatch],
) -> dict[str, int]:
    stats = {"stages_created": 0, "groups_created": 0}
    # ``source.slug`` comes from the ``challonge_source`` row (derived in
    # discover_sources); the deprecated legacy-column lookup has been removed.
    challonge_slug = source.slug

    if source.group is not None:
        before_stage_count = len(tournament.stages or [])
        await _ensure_group_stage(
            session,
            tournament,
            source.group,
            stage_type=(enums.StageType.ROUND_ROBIN if source.group.is_groups else _playoff_stage_type(matches)),
            item_type=(enums.StageItemType.GROUP if source.group.is_groups else enums.StageItemType.SINGLE_BRACKET),
        )
        stats["stages_created"] += max(0, len(tournament.stages or []) - before_stage_count)
        return stats

    if source.stage is not None:
        await _ensure_stage_item(
            session,
            source.stage,
            name=source.stage.name,
            item_type=_stage_item_type_for_stage(source.stage.stage_type),
        )

    group_ids = {match.group_id for match in matches if match.group_id is not None}
    names_by_group_id = _group_names_for_challonge_ids(group_ids)
    for group_id in sorted(group_ids):
        group = next(
            (candidate for candidate in tournament.groups or [] if candidate.challonge_id == group_id),
            None,
        )
        if group is None:
            group = await _create_group_with_stage(
                session,
                tournament,
                name=names_by_group_id[group_id],
                is_groups=True,
                challonge_id=group_id,
                challonge_slug=challonge_slug,
                stage_type=enums.StageType.ROUND_ROBIN,
            )
            stats["groups_created"] += 1
            stats["stages_created"] += 1
        else:
            before_stage_count = len(tournament.stages or [])
            await _ensure_group_stage(
                session,
                tournament,
                group,
                stage_type=enums.StageType.ROUND_ROBIN,
                item_type=enums.StageItemType.GROUP,
            )
            stats["stages_created"] += max(0, len(tournament.stages or []) - before_stage_count)

    ungrouped_matches = [match for match in matches if match.group_id is None]
    if not ungrouped_matches:
        return stats

    if source.stage is not None and not group_ids:
        return stats

    playoff_group = _find_playoff_group(tournament)
    if playoff_group is None:
        await _create_group_with_stage(
            session,
            tournament,
            name="Playoffs",
            is_groups=False,
            challonge_id=None,
            challonge_slug=challonge_slug,
            stage_type=_playoff_stage_type(ungrouped_matches),
        )
        stats["groups_created"] += 1
        stats["stages_created"] += 1
    else:
        before_stage_count = len(tournament.stages or [])
        await _ensure_group_stage(
            session,
            tournament,
            playoff_group,
            stage_type=_playoff_stage_type(ungrouped_matches),
            item_type=enums.StageItemType.SINGLE_BRACKET,
        )
        stats["stages_created"] += max(0, len(tournament.stages or []) - before_stage_count)

    return stats


def _resolve_group_for_match(
    tournament: models.Tournament,
    source: _ImportSource,
    match: schemas.ChallongeMatch,
) -> models.TournamentGroup | None:
    if source.group is not None:
        return source.group

    groups = list(tournament.groups or [])
    if match.group_id is not None:
        return next((group for group in groups if group.challonge_id == match.group_id), None)

    playoff_groups = [group for group in groups if not group.is_groups]
    if len(playoff_groups) == 1:
        return playoff_groups[0]

    if len(groups) == 1:
        return groups[0]

    return None


async def _resolve_stage_refs_for_match(
    session: AsyncSession,
    tournament: models.Tournament,
    source: _ImportSource,
    group: models.TournamentGroup | None,
    match: schemas.ChallongeMatch,
) -> StageRefs:
    stage = source.stage
    if stage is None and source.group is not None:
        stage = getattr(source.group, "stage", None)

    return await resolve_stage_refs_from_group(
        session,
        tournament_id=tournament.id,
        tournament_group_id=group.id if group else None,
        stage_id=stage.id if stage else None,
        stage_item_id=_default_stage_item_id(stage, match),
    )


def _normalize_team_name(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"\s+", " ", name.lower()).strip()


async def _build_team_name_index(
    session: AsyncSession,
    tournament_id: int,
) -> dict[str, int]:
    """Build a normalized-name → team_id index for auto-mapping.

    Collisions (two teams with the same normalized name) are marked _AMBIGUOUS.
    balancer_name is used as a fallback only when name produces no entry.
    """
    result = await session.execute(select(models.Team).where(models.Team.tournament_id == tournament_id))
    teams = list(result.scalars().all())
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


async def _fetch_source_data(source: _ImportSource) -> _SourceFetch:
    """Fetch matches and participants for one Challonge source in parallel."""
    results = await asyncio.gather(
        challonge_service.fetch_matches(source.challonge_id),
        challonge_service.fetch_participants(source.challonge_id),
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


async def _auto_map_participants(
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
        source_group_id = source.group.id if source.group is not None else None

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
                    session.add(mapping)
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
        await session.flush()
        for mapping, participant_name, source_group_id in created:
            await _log_sync(
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
    session: AsyncSession,
    tournament: models.Tournament,
    fetches: list[tuple[_ImportSource, _SourceFetch]],
    *,
    dry_run: bool = False,
) -> _TeamLookup:
    source_mapping_result = await session.execute(
        select(models.ChallongeParticipantMapping)
        .join(
            models.ChallongeSource,
            models.ChallongeSource.id == models.ChallongeParticipantMapping.source_id,
        )
        .where(models.ChallongeSource.tournament_id == tournament.id)
    )
    existing_source_mappings = list(source_mapping_result.scalars().all())

    name_index = await _build_team_name_index(session, tournament.id)
    created_mappings = await _auto_map_participants(
        session,
        tournament,
        fetches,
        existing_source_mappings,
        name_index,
        dry_run=dry_run,
    )

    all_mappings = existing_source_mappings + created_mappings

    # Per-source lookup key and the group id (for group/playoff sources) so the
    # legacy (group_id, challonge_id) fallback in _TeamLookup.resolve can be rebuilt
    # purely from participant mappings — no ChallongeTeam rows involved.
    source_key_by_source_id: dict[int, int] = {}
    group_id_by_source_id: dict[int, int | None] = {}
    for source, _fetch in fetches:
        if source.source_id is not None:
            source_key_by_source_id[source.source_id] = _source_lookup_key(source)
            group_id_by_source_id[source.source_id] = source.group.id if source.group is not None else None

    by_source_key: dict[tuple[int, int], int] = {}
    by_key: dict[tuple[int | None, int], int] = {}
    for mapping in all_mappings:
        source_key = source_key_by_source_id.get(mapping.source_id, mapping.source_id)
        by_source_key[(source_key, mapping.challonge_participant_id)] = mapping.team_id
        by_key.setdefault((None, mapping.challonge_participant_id), mapping.team_id)
        group_id = group_id_by_source_id.get(mapping.source_id)
        if group_id is not None:
            by_key[(group_id, mapping.challonge_participant_id)] = mapping.team_id

    team_ids = sorted({mapping.team_id for mapping in all_mappings})
    teams_by_id: dict[int, models.Team] = {}
    if team_ids:
        team_result = await session.execute(select(models.Team).where(models.Team.id.in_(team_ids)))
        teams_by_id = {team.id: team for team in team_result.scalars().all()}

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
        "tournament_group_id": encounter.tournament_group_id,
    }


async def _ensure_match_mapping(
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
    session.add(mapping)
    match_lookup.mapped_keys.add(key)
    match_lookup.set(source, challonge_match_id, encounter)
    await session.flush()


async def _load_stage_inputs(
    session: AsyncSession,
    stage_id: int,
) -> list[models.StageItemInput]:
    result = await session.execute(
        select(models.StageItemInput)
        .join(models.StageItem, models.StageItemInput.stage_item_id == models.StageItem.id)
        .where(models.StageItem.stage_id == stage_id)
    )
    return list(result.scalars().all())


async def _ensure_stage_item_team_inputs(
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
        stage_inputs = await _load_stage_inputs(session, stage.id)

    existing_team_ids = {stage_input.team_id for stage_input in stage_inputs if stage_input.team_id is not None}
    used_slots = {stage_input.slot for stage_input in stage_inputs if stage_input.stage_item_id == stage_item_id}
    next_slot = 1
    created = 0

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
        session.add(stage_input)
        created += 1
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
        await session.flush()
    return created


async def _ensure_encounter_stage_inputs(
    session: AsyncSession,
    tournament: models.Tournament,
    encounter: models.Encounter | None,
) -> int:
    if encounter is None:
        return 0
    return await _ensure_stage_item_team_inputs(
        session,
        tournament,
        stage_item_id=encounter.stage_item_id,
        team_ids=[encounter.home_team_id, encounter.away_team_id],
    )


async def _upsert_encounter_from_challonge(
    session: AsyncSession,
    tournament: models.Tournament,
    source: _ImportSource,
    match: schemas.ChallongeMatch,
    *,
    match_lookup: _MatchLookup,
    team_lookup: _TeamLookup,
) -> _UpsertResult:
    encounter = match_lookup.get(source, match.id)
    group = _resolve_group_for_match(tournament, source, match)
    home_team_id = team_lookup.resolve(source, group.id if group else None, match.player1_id)
    away_team_id = team_lookup.resolve(source, group.id if group else None, match.player2_id)
    missing_team_mapping = [
        str(challonge_id)
        for challonge_id, team_id in (
            (match.player1_id, home_team_id),
            (match.player2_id, away_team_id),
        )
        if challonge_id is not None and team_id is None
    ]
    if encounter is None and missing_team_mapping:
        return _UpsertResult(
            action="error",
            error=("Missing Challonge team mapping for participant(s): " + ", ".join(missing_team_mapping)),
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
    refs = await _resolve_stage_refs_for_match(session, tournament, source, group, match)
    if encounter is None:
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
            tournament_group_id=refs.tournament_group_id,
            stage_id=refs.stage_id,
            stage_item_id=refs.stage_item_id,
            status=status,
        )
        session.add(encounter)
        await session.flush()
        match_lookup.set(source, match.id, encounter)
        # challonge_match_mapping is the sole persistence of the encounter↔match
        # link now (the legacy encounter.challonge_id column is no longer written).
        await _ensure_match_mapping(session, source, match.id, encounter, match_lookup)
        return _UpsertResult(action="created", encounter=encounter)

    was_completed = encounter.status == enums.EncounterStatus.COMPLETED
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
        "tournament_group_id": refs.tournament_group_id,
    }
    if was_completed:
        local_score = (encounter.home_score, encounter.away_score)
        remote_score = (home_score, away_score)
        local_teams = (encounter.home_team_id, encounter.away_team_id)
        remote_teams = (home_team_id, away_team_id)
        if (
            status != enums.EncounterStatus.COMPLETED
            or local_score != remote_score
            or (None not in remote_teams and local_teams != remote_teams)
        ):
            await _ensure_match_mapping(session, source, match.id, encounter, match_lookup)
            return _UpsertResult(
                action="conflict",
                encounter=encounter,
                conflict_type=(
                    "local_completed_remote_different"
                    if status == enums.EncounterStatus.COMPLETED
                    else "local_completed_remote_not_completed"
                ),
                before=before,
                after=after,
            )

    if not missing_team_mapping and not missing_local_team:
        encounter.name = build_encounter_name(
            home_team.name if home_team is not None else None,
            away_team.name if away_team is not None else None,
        )
        encounter.home_team_id = home_team_id
        encounter.away_team_id = away_team_id
    encounter.home_score = home_score
    encounter.away_score = away_score
    encounter.round = match.round
    encounter.tournament_group_id = refs.tournament_group_id
    encounter.stage_id = refs.stage_id
    encounter.stage_item_id = refs.stage_item_id
    encounter.status = status
    await session.flush()
    await _ensure_match_mapping(session, source, match.id, encounter, match_lookup)

    if not was_completed and status == enums.EncounterStatus.COMPLETED:
        await finalize_encounter_score(
            session,
            encounter.id,
            encounter=encounter,
            home_score=encounter.home_score,
            away_score=encounter.away_score,
            source="challonge",
        )

    return _UpsertResult(action="updated", encounter=encounter, before=before, after=after)


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


async def _sync_challonge_advancement_links(
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

    existing_result = await session.execute(
        select(models.EncounterLink).where(models.EncounterLink.source_encounter_id.in_(source_encounter_ids))
    )
    existing_by_source_role = {(link.source_encounter_id, link.role): link for link in existing_result.scalars().all()}

    created = 0
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
            session.add(link)
            existing_by_source_role[key] = link
            created += 1
            continue

        if existing.target_encounter_id != target.id or existing.target_slot != spec.target_slot:
            existing.target_encounter_id = target.id
            existing.target_slot = spec.target_slot
            updated += 1

    if created or updated:
        await session.flush()

    return {
        "bracket_links_created": created,
        "bracket_links_updated": updated,
    }


async def _advance_completed_challonge_matches(
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
            await finalize_encounter_score(
                session,
                encounter.id,
                encounter=encounter,
                home_score=encounter.home_score,
                away_score=encounter.away_score,
                source="challonge",
            )


async def _build_match_lookup(
    session: AsyncSession,
    tournament_id: int,
    sources: list[_ImportSource],
) -> _MatchLookup:
    mapping_result = await session.execute(
        select(models.ChallongeMatchMapping)
        .join(
            models.ChallongeSource,
            models.ChallongeSource.id == models.ChallongeMatchMapping.source_id,
        )
        .where(models.ChallongeSource.tournament_id == tournament_id)
        .options(selectinload(models.ChallongeMatchMapping.encounter))
    )
    mappings = list(mapping_result.scalars().all())
    source_keys_by_source_id = {
        source.source_id: _source_lookup_key(source) for source in sources if source.source_id is not None
    }
    by_source_key: dict[tuple[int, int], models.Encounter] = {}
    mapped_keys: set[tuple[int, int]] = set()
    for mapping in mappings:
        mapped_keys.add((mapping.source_id, mapping.challonge_match_id))
        if mapping.encounter is None:
            continue
        source_key = source_keys_by_source_id.get(mapping.source_id, mapping.source_id)
        by_source_key[(source_key, mapping.challonge_match_id)] = mapping.encounter

    # Existing encounters are located via challonge_match_mapping (by_source_key)
    # only — the deprecated encounter.challonge_id column is no longer consulted.
    # by_challonge_id stays as an in-run cache populated by _MatchLookup.set for
    # encounters created/mapped during this import.
    return _MatchLookup(
        by_source_key=by_source_key,
        by_challonge_id={},
        mapped_keys=mapped_keys,
    )


async def import_tournament(session: AsyncSession, tournament_id: int, *, dry_run: bool = False) -> dict:
    """Full import from Challonge: upsert encounters with scores and status."""
    async with _sync_job_lock(tournament_id, "import") as job_id:
        result = await session.execute(
            select(models.Tournament)
            .where(models.Tournament.id == tournament_id)
            .options(
                selectinload(models.Tournament.groups)
                .selectinload(models.TournamentGroup.stage)
                .selectinload(models.Stage.items)
                .selectinload(models.StageItem.inputs),
                selectinload(models.Tournament.stages)
                .selectinload(models.Stage.items)
                .selectinload(models.StageItem.inputs),
            )
        )
        tournament = result.scalar_one_or_none()
        if not tournament:
            return {"job_id": job_id, "error": "Tournament not found"}

        sources = await discover_sources(session, tournament, dry_run=dry_run)
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

        raw_fetches = await _fetch_all_sources(sources)
        fetches: list[tuple[_ImportSource, _SourceFetch]] = []
        for source, fetch_result in raw_fetches:
            if isinstance(fetch_result, Exception):
                stats["errors"] += 1
                if not dry_run:
                    await _log_sync(
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
                    structure_stats = await _ensure_stage_structure_for_matches(
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
                    await _log_sync(
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

        team_lookup = await _build_team_lookup(session, tournament, fetches, dry_run=dry_run)
        match_lookup = await _build_match_lookup(session, tournament_id, sources)

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
                    upsert_result = await _upsert_encounter_from_challonge(
                        session,
                        tournament,
                        source,
                        cm,
                        match_lookup=match_lookup,
                        team_lookup=team_lookup,
                    )
                    if upsert_result.action == "error":
                        stats["errors"] += 1
                        await _log_sync(
                            session,
                            tournament_id,
                            "import",
                            "match",
                            None,
                            cm.id,
                            "failed",
                            source_id=source.source_id,
                            operation="apply_import",
                            error_message=upsert_result.error,
                        )
                        continue
                    if upsert_result.action == "conflict":
                        stats["stage_inputs_created"] += await _ensure_encounter_stage_inputs(
                            session,
                            tournament,
                            upsert_result.encounter,
                        )
                        stats["conflicts"] += 1
                        stats["matches_skipped"] += 1
                        await _log_sync(
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
                    stats["stage_inputs_created"] += await _ensure_encounter_stage_inputs(
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

                    await _log_sync(
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
                    await _log_sync(
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
            link_stats = await _sync_challonge_advancement_links(
                session,
                processed_matches,
                match_lookup=match_lookup,
            )
            stats["bracket_links_created"] += link_stats["bracket_links_created"]
            stats["bracket_links_updated"] += link_stats["bracket_links_updated"]
            if link_stats["bracket_links_created"] or link_stats["bracket_links_updated"]:
                await _advance_completed_challonge_matches(
                    session,
                    processed_matches,
                    match_lookup=match_lookup,
                )

            await session.commit()
            if stats["matches_synced"] > 0:
                await standings_recalculation.enqueue_tournament_recalculation(tournament_id)
        logger.info(f"Challonge import for tournament {tournament_id}: {stats}")
        return stats


def _source_matches_encounter(source: _ImportSource, encounter: models.Encounter) -> bool:
    if source.stage_item_id is not None and encounter.stage_item_id == source.stage_item_id:
        return True
    if source.stage is not None and encounter.stage_id == source.stage.id:
        return True
    if source.group is not None and encounter.tournament_group_id == source.group.id:
        return True
    return source.source_type == "tournament"


async def _resolve_export_target(
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
        mapping_result = await session.execute(
            select(models.ChallongeMatchMapping)
            .where(models.ChallongeMatchMapping.encounter_id == encounter.id)
            .options(selectinload(models.ChallongeMatchMapping.source))
        )
        mapping = mapping_result.scalars().first()
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
        sources = await discover_sources(session, tournament)
    candidates = [source for source in sources if _source_matches_encounter(source, encounter)]
    source = candidates[0] if candidates else (sources[0] if len(sources) == 1 else None)
    return source, None


async def _resolve_winner_challonge_id(
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
    cached = participant_mappings.get((source.source_id, winner_team_id)) if participant_mappings is not None else None
    if cached is not None:
        source_mappings = cached
    else:
        result = await session.execute(
            select(models.ChallongeParticipantMapping)
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


async def export_tournament(session: AsyncSession, tournament_id: int) -> dict:
    """Full export: push all completed encounter results to Challonge."""
    async with _sync_job_lock(tournament_id, "export") as job_id:
        result = await session.execute(
            select(models.Tournament)
            .where(models.Tournament.id == tournament_id)
            .options(
                selectinload(models.Tournament.groups)
                .selectinload(models.TournamentGroup.stage)
                .selectinload(models.Stage.items),
                selectinload(models.Tournament.stages).selectinload(models.Stage.items),
            )
        )
        tournament = result.scalar_one_or_none()
        if not tournament:
            return {"job_id": job_id, "error": "Tournament not found"}

        sources = await discover_sources(session, tournament)
        if not sources:
            return {"job_id": job_id, "error": "Tournament has no Challonge source"}

        stats = {"job_id": job_id, "matches_pushed": 0, "errors": 0, "skipped": 0}

        # "Linked to Challonge" is now derived from challonge_match_mapping (scoped
        # to this tournament's sources), not the deprecated encounter.challonge_id.
        linked_encounter_ids = (
            select(models.ChallongeMatchMapping.encounter_id)
            .join(
                models.ChallongeSource,
                models.ChallongeSource.id == models.ChallongeMatchMapping.source_id,
            )
            .where(models.ChallongeSource.tournament_id == tournament_id)
        )
        enc_result = await session.execute(
            select(models.Encounter)
            .where(
                models.Encounter.tournament_id == tournament_id,
                models.Encounter.status == enums.EncounterStatus.COMPLETED,
                models.Encounter.id.in_(linked_encounter_ids),
            )
            .options(
                selectinload(models.Encounter.home_team),
                selectinload(models.Encounter.away_team),
            )
        )
        encounters = enc_result.scalars().all()

        # Bulk prefetch of both mapping tables (same batching pattern as the
        # import path) — the loop below would otherwise issue two lookup queries
        # per encounter.
        match_mappings: dict[int, models.ChallongeMatchMapping] = {}
        encounter_ids = [encounter.id for encounter in encounters]
        if encounter_ids:
            mapping_rows = await session.execute(
                select(models.ChallongeMatchMapping)
                .where(models.ChallongeMatchMapping.encounter_id.in_(encounter_ids))
                .options(selectinload(models.ChallongeMatchMapping.source))
                .order_by(models.ChallongeMatchMapping.id.asc())
            )
            for mapping_row in mapping_rows.scalars():
                match_mappings.setdefault(mapping_row.encounter_id, mapping_row)

        participant_mappings: dict[tuple[int, int], list[models.ChallongeParticipantMapping]] = {}
        source_ids = [source.source_id for source in sources if source.source_id is not None]
        if source_ids:
            participant_rows = await session.execute(
                select(models.ChallongeParticipantMapping)
                .where(models.ChallongeParticipantMapping.source_id.in_(source_ids))
                .order_by(models.ChallongeParticipantMapping.id.asc())
            )
            for participant_row in participant_rows.scalars():
                participant_mappings.setdefault((participant_row.source_id, participant_row.team_id), []).append(
                    participant_row
                )

        for encounter in encounters:
            try:
                pushed = await push_single_result(
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
                await _log_sync(
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
    session: AsyncSession,
    tournament: models.Tournament,
    encounter: models.Encounter,
    *,
    sources: list[_ImportSource] | None = None,
    match_mappings: dict[int, models.ChallongeMatchMapping] | None = None,
    participant_mappings: dict[tuple[int, int], list[models.ChallongeParticipantMapping]] | None = None,
) -> bool:
    """Push a single encounter result to Challonge."""
    return await _push_single_result_impl(
        session,
        tournament,
        encounter,
        sources=sources,
        match_mappings=match_mappings,
        participant_mappings=participant_mappings,
    )


async def _push_single_result_impl(
    session: AsyncSession,
    tournament: models.Tournament,
    encounter: models.Encounter,
    *,
    sources: list[_ImportSource] | None,
    match_mappings: dict[int, models.ChallongeMatchMapping] | None = None,
    participant_mappings: dict[tuple[int, int], list[models.ChallongeParticipantMapping]] | None = None,
) -> bool:
    source, challonge_match_id = await _resolve_export_target(
        session, tournament, encounter, sources=sources, match_mappings=match_mappings
    )
    # No challonge_match_mapping → the encounter is not linked to Challonge; skip.
    if source is None or challonge_match_id is None:
        return False

    winner_team = encounter.home_team if encounter.home_score > encounter.away_score else encounter.away_team
    if not winner_team:
        raise ValueError(f"Encounter {encounter.id} has no winner team")

    winner_challonge_id = await _resolve_winner_challonge_id(
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

    await challonge_service.update_match(
        source.challonge_id,
        challonge_match_id,
        scores_csv=scores_csv,
        winner_id=winner_challonge_id,
    )

    await _log_sync(
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


async def auto_push_on_confirm(session: AsyncSession, encounter_id: int) -> None:
    """Auto-push to Challonge when an encounter result is confirmed.

    Called from captain.confirm_result after status -> confirmed.
    """
    enc_result = await session.execute(
        select(models.Encounter)
        .where(models.Encounter.id == encounter_id)
        .options(
            selectinload(models.Encounter.tournament),
            selectinload(models.Encounter.tournament)
            .selectinload(models.Tournament.groups)
            .selectinload(models.TournamentGroup.stage)
            .selectinload(models.Stage.items),
            selectinload(models.Encounter.tournament)
            .selectinload(models.Tournament.stages)
            .selectinload(models.Stage.items),
            selectinload(models.Encounter.home_team),
            selectinload(models.Encounter.away_team),
        )
    )
    encounter = enc_result.scalar_one_or_none()
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
        await push_single_result(session, tournament, encounter)
        await session.commit()
        logger.info(f"Auto-pushed encounter {encounter_id} to Challonge")
    except Exception as e:
        logger.error(f"Auto-push failed for encounter {encounter_id}: {e}")
        await _log_sync(
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


async def get_sync_log(session: AsyncSession, tournament_id: int, limit: int = 50) -> list[models.ChallongeSyncLog]:
    result = await session.execute(
        select(models.ChallongeSyncLog)
        .where(models.ChallongeSyncLog.tournament_id == tournament_id)
        .order_by(models.ChallongeSyncLog.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())
