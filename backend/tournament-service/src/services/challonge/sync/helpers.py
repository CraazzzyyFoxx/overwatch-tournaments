"""Pure mapping helpers (Challonge state/score/stage translation, loaded-collection probes) and the Challonge fetch."""

import asyncio
import re
from collections.abc import Sequence

from loguru import logger
from sqlalchemy import inspect as sa_inspect

from shared import models
from shared.core import enums
from shared.services.realtime import Resource
from src import schemas
from src.clients.challonge import challonge_client
from src.services.challonge.sync._types import _ChallongeLinkSpec, _ImportSource, _source_lookup_key, _SourceFetch
from src.services.tournament.events import (
    RESULT_RESOURCES,
    STRUCTURE_RESOURCES,
)

_SCORE_RE = re.compile(r"\s*(-?\d+)\s*-\s*(-?\d+)")


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
