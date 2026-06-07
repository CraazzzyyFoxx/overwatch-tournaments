"""Admin service layer for stage CRUD and bracket generation."""

from collections.abc import Sequence

from fastapi import HTTPException, status
from loguru import logger
from shared.core import enums
from shared.services.bracket.advancement import persist_advancement_edges
from shared.services.bracket.engine import generate_bracket
from shared.services.bracket.swiss import SwissPairingImpossibleError, SwissStanding
from shared.services.bracket.swiss_settings import (
    clear_swiss_byes,
    clear_swiss_scope_stopped,
    mark_swiss_scope_stopped,
    record_swiss_bye,
    swiss_bye_team_ids,
)
from shared.services.bracket.types import BracketSkeleton
from shared.services.encounter_naming import build_encounter_name_from_ids
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models
from src.schemas.admin import stage as admin_schemas
from src.services.standings import recalculation as standings_recalculation
from src.services.standings import service as standings_service
from src.services.standings import swiss_auto_round

GROUPED_GENERATION_STAGE_TYPES = {
    enums.StageType.ROUND_ROBIN,
    enums.StageType.SWISS,
}


async def _publish_tournament_changed(tournament_id: int, reason: str) -> None:
    await standings_recalculation.publish_tournament_changed(tournament_id, reason)


async def get_stage(session: AsyncSession, stage_id: int) -> models.Stage:
    result = await session.execute(
        select(models.Stage)
        .where(models.Stage.id == stage_id)
        .options(
            selectinload(models.Stage.items).selectinload(models.StageItem.inputs)
        )
    )
    stage = result.scalar_one_or_none()
    if not stage:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
    return stage


async def get_stage_item(session: AsyncSession, stage_item_id: int) -> models.StageItem:
    result = await session.execute(
        select(models.StageItem)
        .where(models.StageItem.id == stage_item_id)
        .options(selectinload(models.StageItem.inputs))
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Stage item not found",
        )
    return item


async def get_stages_by_tournament(
    session: AsyncSession, tournament_id: int
) -> list[models.Stage]:
    result = await session.execute(
        select(models.Stage)
        .where(models.Stage.tournament_id == tournament_id)
        .options(
            selectinload(models.Stage.items).selectinload(models.StageItem.inputs)
        )
        .order_by(models.Stage.order)
    )
    return list(result.scalars().all())


async def get_stage_progress(
    session: AsyncSession, tournament_id: int
) -> list[dict]:
    """Return per-stage and per-stage_item progress (completed / total
    encounters). Used by admin UI to render the "Group A — 8/10 done" badge
    and to warn before activating a playoff with pending group matches.
    """
    # Import locally to avoid cyclic module-load with standings service.
    from src.services.standings import service as standings_service  # noqa: WPS433

    stages_result = await session.execute(
        select(models.Stage)
        .where(models.Stage.tournament_id == tournament_id)
        .options(selectinload(models.Stage.items))
        .order_by(models.Stage.order)
    )
    stages_list = list(stages_result.scalars().all())
    if not stages_list:
        return []

    stage_ids = [s.id for s in stages_list]
    counts = await session.execute(
        select(
            models.Encounter.stage_id,
            models.Encounter.stage_item_id,
            models.Encounter.status,
        ).where(models.Encounter.stage_id.in_(stage_ids))
    )
    rows = list(counts)

    # Aggregate: (stage_id, stage_item_id | None) → (total, completed).
    agg: dict[tuple[int, int | None], list[int]] = {}
    for row in rows:
        key = (row.stage_id, row.stage_item_id)
        bucket = agg.setdefault(key, [0, 0])
        bucket[0] += 1
        if row.status == standings_service.enums.EncounterStatus.COMPLETED:
            bucket[1] += 1

    output: list[dict] = []
    for stage in stages_list:
        stage_total = 0
        stage_completed = 0
        item_progress: list[dict] = []
        for item in sorted(stage.items, key=lambda it: it.order):
            total, completed = agg.get((stage.id, item.id), [0, 0])
            stage_total += total
            stage_completed += completed
            item_progress.append(
                {
                    "stage_item_id": item.id,
                    "name": item.name,
                    "total": total,
                    "completed": completed,
                    "is_completed": total > 0 and completed == total,
                }
            )
        # Also include encounters with NULL stage_item_id (shouldn't happen
        # after Phase A backfill, but safe).
        total, completed = agg.get((stage.id, None), [0, 0])
        stage_total += total
        stage_completed += completed

        output.append(
            {
                "stage_id": stage.id,
                "name": stage.name,
                "stage_type": stage.stage_type.value,
                "is_active": stage.is_active,
                "is_completed": stage.is_completed,
                "total": stage_total,
                "completed": stage_completed,
                "items": item_progress,
            }
        )
    return output


async def create_stage(
    session: AsyncSession, tournament_id: int, data: admin_schemas.StageCreate
) -> models.Stage:
    result = await session.execute(
        select(models.Tournament).where(models.Tournament.id == tournament_id)
    )
    tournament = result.scalar_one_or_none()
    if not tournament:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

    stage = models.Stage(tournament_id=tournament_id, **data.model_dump())
    session.add(stage)
    await session.commit()
    await _publish_tournament_changed(tournament_id, "structure_changed")
    return await get_stage(session, stage.id)


async def update_stage(
    session: AsyncSession, stage_id: int, data: admin_schemas.StageUpdate
) -> models.Stage:
    stage = await get_stage(session, stage_id)
    tournament_id = stage.tournament_id
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(stage, field, value)
    await session.commit()
    await _publish_tournament_changed(tournament_id, "structure_changed")
    return await get_stage(session, stage.id)


async def delete_stage(session: AsyncSession, stage_id: int) -> None:
    stage = await get_stage(session, stage_id)
    tournament_id = stage.tournament_id
    # Encounter.stage_id and Standing.stage_id reference Stage with ON DELETE
    # SET NULL, so deleting the stage alone would orphan its matches and
    # standings rather than remove them. Delete that derived data explicitly
    # first; the encounter's dependents (maps, match rows, links, mappings)
    # cascade from the encounter delete.
    await session.execute(delete(models.Encounter).where(models.Encounter.stage_id == stage_id))
    await session.execute(delete(models.Standing).where(models.Standing.stage_id == stage_id))
    await session.delete(stage)
    await session.commit()
    await _publish_tournament_changed(tournament_id, "structure_changed")


def _map_veto_signature(config: models.MapVetoConfig) -> tuple[tuple, tuple]:
    return (
        tuple(config.veto_sequence_json or []),
        tuple(config.map_pool_ids or []),
    )


async def _merge_map_veto_configs(
    session: AsyncSession,
    *,
    target_stage: models.Stage,
    source_stage_ids: list[int],
) -> None:
    target_result = await session.execute(
        select(models.MapVetoConfig).where(
            models.MapVetoConfig.tournament_id == target_stage.tournament_id,
            models.MapVetoConfig.stage_id == target_stage.id,
        )
    )
    target_configs = list(target_result.scalars().all())
    if len(target_configs) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Target stage has multiple map veto configs; resolve them before merging",
        )

    source_result = await session.execute(
        select(models.MapVetoConfig).where(
            models.MapVetoConfig.tournament_id == target_stage.tournament_id,
            models.MapVetoConfig.stage_id.in_(source_stage_ids),
        )
    )
    source_configs = list(source_result.scalars().all())
    if not source_configs:
        return

    if target_configs:
        for config in source_configs:
            await session.delete(config)
        return

    signatures = {_map_veto_signature(config) for config in source_configs}
    if len(signatures) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Source stages have different map veto configs; keep one "
                "target config before merging"
            ),
        )

    keeper = source_configs[0]
    keeper.stage_id = target_stage.id
    for config in source_configs[1:]:
        await session.delete(config)


async def _retarget_stage_rows(
    session: AsyncSession,
    model,
    *,
    source_stage_ids: list[int],
    target_stage_id: int,
) -> None:
    result = await session.execute(
        select(model).where(model.stage_id.in_(source_stage_ids))
    )
    for row in result.scalars().all():
        row.stage_id = target_stage_id


async def _reindex_tournament_stages(
    session: AsyncSession,
    *,
    tournament_id: int,
    removed_stage_ids: set[int],
) -> None:
    result = await session.execute(
        select(models.Stage)
        .where(
            models.Stage.tournament_id == tournament_id,
            ~models.Stage.id.in_(removed_stage_ids),
        )
        .order_by(models.Stage.order.asc(), models.Stage.id.asc())
    )
    for index, stage in enumerate(result.scalars().all()):
        stage.order = index


async def merge_group_stages(
    session: AsyncSession,
    *,
    target_stage_id: int,
    source_stage_ids: list[int],
    target_name: str | None = None,
) -> models.Stage:
    """Merge old one-group stages into one grouped stage.

    Old tournaments were migrated as A/B/C/D separate Stage rows. The modern
    shape is one grouped Stage with A/B/C/D as StageItem rows, so this moves
    source items and all stage-scoped references to the selected target stage.
    """
    target_stage = await get_stage(session, target_stage_id)
    if target_stage.stage_type not in GROUPED_GENERATION_STAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target stage must be ROUND_ROBIN or SWISS",
        )

    unique_source_stage_ids = list(dict.fromkeys(source_stage_ids))
    if len(unique_source_stage_ids) != len(source_stage_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_stage_ids must not contain duplicates",
        )
    if target_stage_id in unique_source_stage_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target stage cannot be included in source_stage_ids",
        )

    stages_result = await session.execute(
        select(models.Stage).where(models.Stage.id.in_(unique_source_stage_ids))
    )
    source_by_id = {stage.id: stage for stage in stages_result.scalars().all()}
    missing = [stage_id for stage_id in unique_source_stage_ids if stage_id not in source_by_id]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source stages not found: {missing}",
        )

    source_stages = [source_by_id[stage_id] for stage_id in unique_source_stage_ids]
    for source_stage in source_stages:
        if source_stage.tournament_id != target_stage.tournament_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="All source stages must belong to the target tournament",
            )
        if source_stage.stage_type != target_stage.stage_type:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="All merged group stages must have the same stage type",
            )

    items_result = await session.execute(
        select(models.StageItem)
        .join(models.Stage, models.StageItem.stage_id == models.Stage.id)
        .where(models.StageItem.stage_id.in_(unique_source_stage_ids))
        .order_by(
            models.Stage.order.asc(),
            models.Stage.id.asc(),
            models.StageItem.order.asc(),
            models.StageItem.id.asc(),
        )
    )
    source_items = list(items_result.scalars().all())
    if not source_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source stages have no stage items to merge",
        )

    all_items = [
        *sorted(target_stage.items, key=lambda item: (item.order, item.id)),
        *source_items,
    ]
    if any(item.type != enums.StageItemType.GROUP for item in all_items):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only group stage items can be merged",
        )

    seen_names: set[str] = set()
    for item in all_items:
        normalized_name = item.name.strip().lower()
        if normalized_name in seen_names:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f'Duplicate group name "{item.name}" would be created',
            )
        seen_names.add(normalized_name)

    await _merge_map_veto_configs(
        session,
        target_stage=target_stage,
        source_stage_ids=unique_source_stage_ids,
    )

    for model in (
        models.TournamentGroup,
        models.Encounter,
        models.Standing,
        models.ChallongeSource,
    ):
        await _retarget_stage_rows(
            session,
            model,
            source_stage_ids=unique_source_stage_ids,
            target_stage_id=target_stage.id,
        )

    target_items = sorted(target_stage.items, key=lambda item: (item.order, item.id))
    stage_order_by_id = {
        target_stage.id: target_stage.order,
        **{stage.id: stage.order for stage in source_stages},
    }
    ordered_items = sorted(
        [*target_items, *source_items],
        key=lambda item: (stage_order_by_id.get(item.stage_id, 0), item.order, item.id),
    )
    for order, item in enumerate(ordered_items):
        item.stage_id = target_stage.id
        item.order = order

    next_target_name = target_name.strip() if target_name else ""
    if next_target_name:
        target_stage.name = next_target_name
    target_stage.is_active = target_stage.is_active or any(stage.is_active for stage in source_stages)
    target_stage.is_completed = target_stage.is_completed and all(
        stage.is_completed for stage in source_stages
    )

    await session.flush()
    for source_stage in source_stages:
        await session.delete(source_stage)

    await _reindex_tournament_stages(
        session,
        tournament_id=target_stage.tournament_id,
        removed_stage_ids=set(unique_source_stage_ids),
    )
    await session.commit()
    await standings_service.recalculate_for_tournament(session, target_stage.tournament_id)
    await _publish_tournament_changed(target_stage.tournament_id, "structure_changed")

    logger.info(
        "Merged %d source group stages into stage %s for tournament %s",
        len(source_stage_ids),
        target_stage.id,
        target_stage.tournament_id,
    )
    return await get_stage(session, target_stage.id)


async def _ensure_stage_item_compat_group(
    session: AsyncSession,
    stage: models.Stage,
    item: models.StageItem,
) -> None:
    result = await session.execute(
        select(models.TournamentGroup).where(
            models.TournamentGroup.tournament_id == stage.tournament_id,
            models.TournamentGroup.stage_id == stage.id,
            models.TournamentGroup.name == item.name,
        )
    )
    if result.scalar_one_or_none() is not None:
        return

    session.add(
        models.TournamentGroup(
            tournament_id=stage.tournament_id,
            name=item.name,
            description=None,
            is_groups=stage.stage_type in GROUPED_GENERATION_STAGE_TYPES,
            stage_id=stage.id,
        )
    )


async def create_stage_item(
    session: AsyncSession, stage_id: int, data: admin_schemas.StageItemCreate
) -> models.StageItem:
    stage = await get_stage(session, stage_id)
    tournament_id = stage.tournament_id
    item = models.StageItem(stage_id=stage_id, **data.model_dump())
    session.add(item)
    await _ensure_stage_item_compat_group(session, stage, item)
    await session.commit()
    item_id = item.id
    await standings_service.recalculate_for_tournament(session, tournament_id)
    await _publish_tournament_changed(tournament_id, "structure_changed")
    return await get_stage_item(session, item_id)


async def update_stage_item(
    session: AsyncSession,
    stage_item_id: int,
    data: admin_schemas.StageItemUpdate,
) -> models.StageItem:
    item = await get_stage_item(session, stage_item_id)
    stage_result = await session.execute(
        select(models.StageItem)
        .where(models.StageItem.id == stage_item_id)
        .options(selectinload(models.StageItem.stage))
    )
    item_with_stage = stage_result.scalar_one()
    tournament_id = item_with_stage.stage.tournament_id
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(item, field, value)
    await session.commit()
    await _publish_tournament_changed(tournament_id, "structure_changed")
    return await get_stage_item(session, stage_item_id)


async def create_stage_item_input(
    session: AsyncSession,
    stage_item_id: int,
    data: admin_schemas.StageItemInputCreate,
) -> models.StageItemInput:
    result = await session.execute(
        select(models.StageItem)
        .where(models.StageItem.id == stage_item_id)
        .options(selectinload(models.StageItem.stage))
    )
    stage_item = result.scalar_one_or_none()
    if not stage_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Stage item not found"
        )
    tournament_id = stage_item.stage.tournament_id
    inp = models.StageItemInput(stage_item_id=stage_item_id, **data.model_dump())
    session.add(inp)
    await session.commit()
    await session.refresh(inp)
    await standings_service.recalculate_for_tournament(session, tournament_id)
    await _publish_tournament_changed(tournament_id, "structure_changed")
    await session.refresh(inp)
    return inp


async def update_stage_item_input(
    session: AsyncSession,
    input_id: int,
    data: admin_schemas.StageItemInputUpdate,
) -> models.StageItemInput:
    result = await session.execute(
        select(models.StageItemInput)
        .where(models.StageItemInput.id == input_id)
        .options(
            selectinload(models.StageItemInput.stage_item).selectinload(
                models.StageItem.stage
            )
        )
    )
    inp = result.scalar_one_or_none()
    if not inp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Stage item input not found"
        )

    tournament_id = inp.stage_item.stage.tournament_id
    stage_id = inp.stage_item.stage_id
    update_data = data.model_dump(exclude_unset=True)
    if not update_data:
        return inp

    next_input_type = update_data.get("input_type", inp.input_type)
    next_team_id = update_data.get("team_id", inp.team_id)
    next_source_stage_item_id = update_data.get(
        "source_stage_item_id", inp.source_stage_item_id
    )
    next_source_position = update_data.get("source_position", inp.source_position)

    if "team_id" in update_data and next_team_id is not None:
        team_result = await session.execute(
            select(models.Team).where(models.Team.id == next_team_id)
        )
        team = team_result.scalar_one_or_none()
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team not found",
            )
        if team.tournament_id != tournament_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Team does not belong to this tournament",
            )

        existing_result = await session.execute(
            select(models.StageItemInput)
            .join(models.StageItem, models.StageItemInput.stage_item_id == models.StageItem.id)
            .where(
                models.StageItem.stage_id == stage_id,
                models.StageItemInput.id != input_id,
                models.StageItemInput.team_id == next_team_id,
            )
        )
        existing_input = existing_result.scalar_one_or_none()
        if existing_input is not None:
            if inp.team_id is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Selected team is already assigned in this stage; "
                        "replace a populated slot to swap teams"
                    ),
                )
            existing_input.team_id = inp.team_id

        next_input_type = enums.StageItemInputType.FINAL
        next_source_stage_item_id = None
        next_source_position = None

    if next_input_type == enums.StageItemInputType.FINAL:
        if next_team_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="FINAL inputs require team_id",
            )
        next_source_stage_item_id = None
        next_source_position = None
    elif next_input_type == enums.StageItemInputType.TENTATIVE:
        if next_source_stage_item_id is None or next_source_position is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "TENTATIVE inputs require source_stage_item_id and "
                    "source_position"
                ),
            )
        if next_team_id is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="TENTATIVE inputs must not have team_id",
            )
    elif next_input_type == enums.StageItemInputType.EMPTY:
        next_team_id = None
        next_source_stage_item_id = None
        next_source_position = None

    inp.input_type = next_input_type
    inp.team_id = next_team_id
    inp.source_stage_item_id = next_source_stage_item_id
    inp.source_position = next_source_position

    await session.commit()
    await standings_service.recalculate_for_tournament(session, tournament_id)
    await _publish_tournament_changed(tournament_id, "structure_changed")
    await session.refresh(inp)
    return inp


async def activate_stage(
    session: AsyncSession, stage_id: int, *, notify: bool = True
) -> models.Stage:
    """Activate a stage, resolving tentative inputs from previous stages."""
    stage = await get_stage(session, stage_id)

    # Deactivate all other stages in this tournament
    other_stages = await get_stages_by_tournament(session, stage.tournament_id)
    for other in other_stages:
        if other.id != stage_id:
            other.is_active = False

    stage.is_active = True

    # Resolve tentative inputs
    for item in stage.items:
        for inp in item.inputs:
            if inp.input_type != enums.StageItemInputType.TENTATIVE:
                continue
            if inp.source_stage_item_id is None or inp.source_position is None:
                continue

            # Look up standings for the source stage item
            standings_result = await session.execute(
                select(models.Standing)
                .where(
                    models.Standing.stage_item_id == inp.source_stage_item_id,
                )
                .order_by(models.Standing.position)
            )
            standings = list(standings_result.scalars().all())

            target_pos = inp.source_position
            if target_pos <= len(standings):
                inp.team_id = standings[target_pos - 1].team_id
                inp.input_type = enums.StageItemInputType.FINAL

    await session.commit()
    if notify:
        await _publish_tournament_changed(stage.tournament_id, "structure_changed")
    return await get_stage(session, stage.id)


def _collect_item_team_ids(item: models.StageItem) -> list[int]:
    return [
        inp.team_id
        for inp in sorted(item.inputs, key=lambda value: value.slot)
        if inp.team_id is not None
    ]


async def _load_team_names(
    session: AsyncSession,
    team_ids: Sequence[int],
) -> dict[int, str]:
    unique_team_ids = sorted({team_id for team_id in team_ids if team_id is not None})
    if not unique_team_ids:
        return {}

    result = await session.execute(
        select(models.Team.id, models.Team.name).where(models.Team.id.in_(unique_team_ids))
    )
    return dict(result.all())


async def _get_swiss_generation_context(
    session: AsyncSession,
    stage_id: int,
    stage_item_id: int | None,
) -> tuple[list[SwissStanding] | None, set[frozenset[int]] | None, int]:
    existing_encounters = await session.execute(
        select(models.Encounter).where(
            models.Encounter.stage_id == stage_id,
            models.Encounter.stage_item_id == stage_item_id,
        )
    )
    existing = list(existing_encounters.scalars().all())
    if not existing:
        return None, None, 1

    swiss_round = max(e.round for e in existing) + 1
    swiss_played_pairs: set[frozenset[int]] = set()
    for encounter in existing:
        if encounter.home_team_id and encounter.away_team_id:
            swiss_played_pairs.add(
                frozenset({encounter.home_team_id, encounter.away_team_id})
            )

    standing_result = await session.execute(
        select(models.Standing).where(
            models.Standing.stage_id == stage_id,
            models.Standing.stage_item_id == stage_item_id,
        ).order_by(models.Standing.position, models.Standing.team_id)
    )
    raw_standings = list(standing_result.scalars().all())
    swiss_standings = [
        SwissStanding(
            team_id=standing.team_id,
            points=standing.points,
            buchholz=standing.buchholz or 0.0,
        )
        for standing in raw_standings
    ]

    return swiss_standings, swiss_played_pairs, swiss_round


async def _generate_stage_skeleton(
    session: AsyncSession,
    stage: models.Stage,
    team_ids: list[int],
    stage_item_id: int | None,
    *,
    lower_bracket_team_ids: list[int] | None = None,
) -> BracketSkeleton:
    swiss_standings = None
    swiss_played_pairs: set[frozenset[int]] | None = None
    swiss_round = 1
    if stage.stage_type == enums.StageType.SWISS:
        swiss_standings, swiss_played_pairs, swiss_round = (
            await _get_swiss_generation_context(session, stage.id, stage_item_id)
        )
        if swiss_standings is None:
            clear_swiss_byes(stage, stage_item_id)
        if not swiss_auto_round.stage_allows_next_round(stage, swiss_round):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Swiss stage reached max_rounds",
            )

    de_include_reset = (
        stage.stage_type == enums.StageType.DOUBLE_ELIMINATION
        and (stage.settings_json or {}).get("de_grand_final_type") == "with_reset"
    )

    try:
        skeleton = generate_bracket(
            stage.stage_type,
            team_ids,
            swiss_standings=swiss_standings,
            swiss_played_pairs=swiss_played_pairs,
            swiss_round_number=swiss_round,
            swiss_bye_history=set(swiss_bye_team_ids(stage, stage_item_id)),
            de_include_reset=de_include_reset,
            lower_bracket_team_ids=lower_bracket_team_ids,
        )
    except SwissPairingImpossibleError:
        mark_swiss_scope_stopped(stage, stage_item_id)
        logger.info(
            "Swiss scope ended because no complete non-rematch pairing exists",
            stage_id=stage.id,
            stage_item_id=stage_item_id,
            round=swiss_round,
        )
        return BracketSkeleton(pairings=[], total_rounds=0)

    if stage.stage_type == enums.StageType.SWISS:
        clear_swiss_scope_stopped(stage, stage_item_id)
        if skeleton.bye_team_id is not None:
            record_swiss_bye(stage, stage_item_id, skeleton.bye_team_id)
    return skeleton


async def _create_encounters_from_skeleton(
    session: AsyncSession,
    stage: models.Stage,
    skeleton: BracketSkeleton,
    stage_item_id: int | None,
    *,
    team_names_by_id: dict[int, str],
    lb_stage_item_id: int | None = None,
) -> list[models.Encounter]:
    """Persist bracket pairings as Encounter rows and wire up EncounterLink
    records for advancement edges.

    For double-elimination stages, ``lb_stage_item_id`` routes encounters with
    negative round numbers (lower bracket) to a separate stage item.
    """
    encounters: list[models.Encounter] = []
    local_to_encounter: dict[int, models.Encounter] = {}
    for pairing in skeleton.pairings:
        # LB rounds use negative round numbers; route to LB item when present.
        item_id = (
            lb_stage_item_id
            if lb_stage_item_id is not None and pairing.round_number < 0
            else stage_item_id
        )
        encounter = models.Encounter(
            name=build_encounter_name_from_ids(
                pairing.home_team_id,
                pairing.away_team_id,
                team_names_by_id,
            ),
            home_team_id=pairing.home_team_id,
            away_team_id=pairing.away_team_id,
            home_score=0,
            away_score=0,
            round=pairing.round_number,
            tournament_id=stage.tournament_id,
            stage_id=stage.id,
            stage_item_id=item_id,
            status=enums.EncounterStatus.OPEN,
        )
        session.add(encounter)
        encounters.append(encounter)
        local_to_encounter[pairing.local_id] = encounter

    # Flush to obtain encounter.id values before persisting links.
    await session.flush()

    local_to_id = {
        local_id: encounter.id for local_id, encounter in local_to_encounter.items()
    }
    await persist_advancement_edges(
        session,
        edges=skeleton.advancement_edges,
        local_to_encounter_id=local_to_id,
    )
    return encounters


async def seed_teams(
    session: AsyncSession,
    stage_id: int,
    team_ids: list[int],
    *,
    mode: str = "snake_sr",
    notify: bool = True,
) -> models.Stage:
    """Auto-distribute teams into the stage's stage_items (groups/brackets).

    Modes:

    - ``snake_sr`` (default): sort teams by ``Team.avg_sr`` descending, then
      deal them out in a snake pattern across stage_items. For 4 groups the
      order becomes A, B, C, D, D, C, B, A, A, B, C, D, ... — this balances
      each group's strength regardless of team count per group.
    - ``random``: deterministic shuffle based on ``Team.id``; distribute
      round-robin across stage_items.
    - ``by_total_sr``: same as ``snake_sr`` but sorts by ``total_sr`` (useful
      when ``avg_sr`` can be skewed by player count differences).

    Idempotent: any existing FINAL inputs in target stage_items are REMOVED
    before seeding — this is a "reset and reseed" operation. TENTATIVE inputs
    are preserved (they point to upstream stage outputs, not team assignments).

    Raises HTTPException if:
    - stage has no stage_items
    - team count is zero
    - teams don't all belong to the same tournament as the stage
    """
    stage = await get_stage(session, stage_id)
    if not stage.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stage has no stage_items to seed into",
        )
    if not team_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="team_ids must be non-empty"
        )
    if len(set(team_ids)) != len(team_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="team_ids contain duplicates"
        )

    teams_result = await session.execute(
        select(models.Team).where(models.Team.id.in_(team_ids))
    )
    teams = list(teams_result.scalars().all())
    if len(teams) != len(team_ids):
        found_ids = {team.id for team in teams}
        missing = [tid for tid in team_ids if tid not in found_ids]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Teams not found: {missing}",
        )
    foreign = [t for t in teams if t.tournament_id != stage.tournament_id]
    if foreign:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Teams {[t.id for t in foreign]} do not belong to this tournament",
        )

    # Sort teams according to the requested mode.
    if mode == "snake_sr":
        teams_sorted = sorted(
            teams, key=lambda t: (t.avg_sr or 0.0, t.id), reverse=True
        )
    elif mode == "by_total_sr":
        teams_sorted = sorted(
            teams, key=lambda t: (t.total_sr or 0, t.id), reverse=True
        )
    elif mode == "random":
        # Deterministic shuffle based on team.id — two calls with the same
        # inputs produce identical seeding, useful for reproducibility and
        # tests. Uses a simple hash to scramble order.
        teams_sorted = sorted(teams, key=lambda t: hash((t.id, stage.id)))
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown seeding mode: {mode!r}",
        )

    stage_items = sorted(stage.items, key=lambda item: (item.order, item.id))
    num_groups = len(stage_items)

    # Wipe existing FINAL inputs. We keep TENTATIVE (advance-from-stage) and
    # EMPTY inputs — only manually-assigned team slots are reset.
    for item in stage_items:
        for inp in list(item.inputs):
            if inp.input_type == enums.StageItemInputType.FINAL:
                await session.delete(inp)

    # Track next free slot per stage_item so we don't collide with preserved
    # TENTATIVE inputs.
    next_slot: dict[int, int] = {}
    for item in stage_items:
        used_slots = {inp.slot for inp in item.inputs if inp.input_type != enums.StageItemInputType.FINAL}
        candidate = 1
        while candidate in used_slots:
            candidate += 1
        next_slot[item.id] = candidate

    # Snake distribution: team index i → group i % num_groups on even rows,
    # reverse on odd rows. This minimises imbalance between groups.
    if mode == "random":
        # round-robin is sufficient for random — no need to "snake".
        def target_group_index(team_idx: int) -> int:
            return team_idx % num_groups
    else:
        def target_group_index(team_idx: int) -> int:
            row = team_idx // num_groups
            column = team_idx % num_groups
            return column if row % 2 == 0 else (num_groups - 1 - column)

    for team_idx, team in enumerate(teams_sorted):
        group_idx = target_group_index(team_idx)
        target_item = stage_items[group_idx]
        slot = next_slot[target_item.id]
        next_slot[target_item.id] = slot + 1

        session.add(
            models.StageItemInput(
                stage_item_id=target_item.id,
                slot=slot,
                input_type=enums.StageItemInputType.FINAL,
                team_id=team.id,
            )
        )

    await session.commit()
    await standings_service.recalculate_for_tournament(session, stage.tournament_id)
    if notify:
        await _publish_tournament_changed(stage.tournament_id, "structure_changed")

    logger.info(
        "Seeded %d teams into stage %s across %d groups (mode=%s)",
        len(teams_sorted),
        stage.id,
        num_groups,
        mode,
    )
    return await get_stage(session, stage_id)


def _build_seeding(
    source_items: list,
    top: int,
    mode: str,
    position_offset: int = 0,
) -> list[tuple[int, int]]:
    """Build ordered (source_item_id, position) pairs for seeding.

    ``position_offset`` shifts which positions are selected — used to pick
    LB positions that follow UB ones (e.g. offset=2 yields positions 3, 4, ...).
    """
    seeding: list[tuple[int, int]] = []
    if mode == "snake":
        for col in range(top):
            position = position_offset + col + 1
            for item in source_items:
                seeding.append((item.id, position))
    else:  # "cross" — default
        for col in range(top):
            position = position_offset + col + 1
            # Flip every odd column so group A's 1st doesn't meet A's 2nd.
            ordered = list(source_items) if col % 2 == 0 else list(reversed(source_items))
            for item in ordered:
                seeding.append((item.id, position))
    return seeding


def _apply_seeding(
    session,
    seeding: list[tuple[int, int]],
    target_item,
) -> None:
    """Write TENTATIVE inputs from ``seeding`` into ``target_item``.

    Preserves existing FINAL inputs; overwrites existing TENTATIVE inputs.
    """
    existing_inputs = {inp.slot: inp for inp in target_item.inputs}
    for idx, (source_item_id, source_position) in enumerate(seeding, start=1):
        existing = existing_inputs.get(idx)
        if existing is not None and existing.input_type == enums.StageItemInputType.FINAL:
            continue
        if existing is not None:
            existing.input_type = enums.StageItemInputType.TENTATIVE
            existing.source_stage_item_id = source_item_id
            existing.source_position = source_position
            existing.team_id = None
        else:
            session.add(
                models.StageItemInput(
                    stage_item_id=target_item.id,
                    slot=idx,
                    input_type=enums.StageItemInputType.TENTATIVE,
                    source_stage_item_id=source_item_id,
                    source_position=source_position,
                    team_id=None,
                )
            )


async def wire_from_groups(
    session: AsyncSession,
    target_stage_id: int,
    source_stage_id: int,
    top: int,
    *,
    top_lb: int = 0,
    mode: str = "cross",
    notify: bool = True,
) -> models.Stage:
    """Wire TENTATIVE inputs in ``target_stage`` pointing to top-N of each group in
    ``source_stage``.

    Supports two seeding modes:

    - ``cross`` (default): standard cross-group seeding that avoids same-group
      rematches in the first playoff round. Given groups A, B, C, ... and
      ``top=2``, slots are arranged as:
          A1, B2, C1, D2, ...  A2, B1, C2, D1
      i.e. every slot ``i`` uses group ``i % G`` and position ``1 + (i // G) % top``
      with odd "columns" flipped. This guarantees group A's 1st-seed does not
      meet group A's 2nd-seed in round 1.
    - ``snake``: simple top-down (all 1st-seeds first, then all 2nd-seeds, ...).

    When ``top_lb > 0`` the target stage must be DOUBLE_ELIMINATION and must
    have a BRACKET_LOWER stage item. Teams at positions ``top+1 … top+top_lb``
    from each group are seeded into that item.

    Idempotent: existing FINAL inputs are preserved; existing TENTATIVE inputs
    with the same slot are overwritten.
    """
    target_stage = await get_stage(session, target_stage_id)
    source_stage = await get_stage(session, source_stage_id)

    if target_stage.tournament_id != source_stage.tournament_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and target stages must belong to the same tournament",
        )
    if source_stage.stage_type not in GROUPED_GENERATION_STAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source stage must be ROUND_ROBIN or SWISS",
        )
    if target_stage.stage_type not in {
        enums.StageType.SINGLE_ELIMINATION,
        enums.StageType.DOUBLE_ELIMINATION,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target stage must be a bracket (single_elimination or double_elimination)",
        )
    if top <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="`top` must be positive"
        )
    if top_lb < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="`top_lb` must be non-negative"
        )
    if not target_stage.items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Target stage has no stage items; create one before wiring",
        )

    lb_item = None
    if top_lb > 0:
        if target_stage.stage_type != enums.StageType.DOUBLE_ELIMINATION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="`top_lb` requires a double_elimination target stage",
            )
        lb_item = next(
            (i for i in target_stage.items if i.type == enums.StageItemType.BRACKET_LOWER),
            None,
        )
        if lb_item is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Target stage has no BRACKET_LOWER stage item; "
                    "create one before using top_lb"
                ),
            )

    source_items = sorted(source_stage.items, key=lambda item: (item.order, item.id))
    if not source_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source stage has no stage items",
        )

    num_groups = len(source_items)

    # UB: first stage_item by order.
    ub_item = sorted(target_stage.items, key=lambda item: (item.order, item.id))[0]
    ub_seeding = _build_seeding(source_items, top=top, mode=mode, position_offset=0)
    _apply_seeding(session, ub_seeding, ub_item)

    if top_lb > 0 and lb_item is not None:
        lb_seeding = _build_seeding(source_items, top=top_lb, mode=mode, position_offset=top)
        _apply_seeding(session, lb_seeding, lb_item)

    await session.commit()
    if notify:
        await _publish_tournament_changed(target_stage.tournament_id, "structure_changed")

    logger.info(
        "Wired TENTATIVE inputs from stage %s (%d groups × top %d, top_lb %d) "
        "into stage %s (%s)",
        source_stage.id,
        num_groups,
        top,
        top_lb,
        target_stage.id,
        mode,
    )
    return await get_stage(session, target_stage_id)


async def _check_upstream_stages_completed(
    session: AsyncSession, stage: models.Stage
) -> list[int]:
    """Return ids of upstream stages that feed into ``stage`` via TENTATIVE
    inputs but are NOT yet marked ``is_completed``. Empty list means safe
    to activate. Used by /activate-and-generate to prevent admins from
    freezing playoff seeds before groups finish.
    """
    source_stage_ids: set[int] = set()
    for item in stage.items:
        for inp in item.inputs:
            if inp.input_type != enums.StageItemInputType.TENTATIVE:
                continue
            if inp.source_stage_item_id is None:
                continue
            source_item = await session.get(models.StageItem, inp.source_stage_item_id)
            if source_item is not None and source_item.stage_id is not None:
                source_stage_ids.add(source_item.stage_id)

    if not source_stage_ids:
        return []

    result = await session.execute(
        select(models.Stage).where(models.Stage.id.in_(source_stage_ids))
    )
    return [s.id for s in result.scalars().all() if not s.is_completed]


async def _preceding_group_stage(session: AsyncSession, stage: models.Stage) -> models.Stage | None:
    """The group stage immediately before ``stage`` in stage order — the source
    used for auto-wiring playoff seeds."""
    result = await session.execute(
        select(models.Stage)
        .where(
            models.Stage.tournament_id == stage.tournament_id,
            models.Stage.stage_type.in_(GROUPED_GENERATION_STAGE_TYPES),
            models.Stage.order < stage.order,
        )
        .order_by(models.Stage.order.desc())
    )
    return result.scalars().first()


async def _auto_wire_from_groups(session: AsyncSession, stage: models.Stage) -> None:
    """Derive playoff seeding from the preceding group stage's ``advance_count``
    and this stage's ``split_lower_bracket`` flag, then wire TENTATIVE inputs
    (cross seeding). Replaces the manual Automation block.

    No-op when the stage is not a bracket, has no preceding group stage, or the
    source group stage has no ``advance_count`` configured — keeping manually
    wired playoffs working unchanged.
    """
    if stage.stage_type not in {
        enums.StageType.SINGLE_ELIMINATION,
        enums.StageType.DOUBLE_ELIMINATION,
    }:
        return
    source = await _preceding_group_stage(session, stage)
    if source is None or not source.advance_count or source.advance_count <= 0:
        return

    advance = source.advance_count
    # Only seed a separate lower bracket when the stage actually has a
    # BRACKET_LOWER item. A "single bracket" double-elimination (one
    # SINGLE_BRACKET item) holds the whole UB+LB structure, so all advancing
    # teams seed that one item — the DE engine builds the rounds internally.
    has_lower_bracket = any(
        item.type == enums.StageItemType.BRACKET_LOWER for item in stage.items
    )
    if (
        stage.split_lower_bracket
        and stage.stage_type == enums.StageType.DOUBLE_ELIMINATION
        and has_lower_bracket
    ):
        top_lb = advance // 2
        top = advance - top_lb  # odd count → extra team to the Upper bracket
    else:
        top = advance
        top_lb = 0

    await wire_from_groups(
        session,
        stage.id,
        source.id,
        top,
        top_lb=top_lb,
        mode="cross",
        notify=False,
    )


async def activate_and_generate(
    session: AsyncSession,
    stage_id: int,
    *,
    force: bool = False,
    notify: bool = True,
) -> tuple[models.Stage, list[models.Encounter]]:
    """Combined endpoint: activate a stage (resolving TENTATIVE inputs) and
    immediately generate bracket encounters. Single click for the admin.

    Unless ``force=True``, raises HTTP 409 when any upstream (source) stage
    still has pending encounters — prevents freezing playoff seeds before
    groups are actually finished.
    """
    stage = await get_stage(session, stage_id)
    # Auto-wire playoff seeds from the preceding group stage (replaces the manual
    # Automation block). Runs BEFORE the upstream-completion check so that check
    # sees the freshly created TENTATIVE inputs.
    await _auto_wire_from_groups(session, stage)
    stage = await get_stage(session, stage_id)
    if not force:
        pending = await _check_upstream_stages_completed(session, stage)
        if pending:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "upstream_stages_not_completed",
                    "message": (
                        "Upstream stages still have pending encounters. "
                        "Finish them first or pass force=true to proceed anyway."
                    ),
                    "pending_stage_ids": pending,
                },
            )

    stage = await activate_stage(session, stage_id, notify=False)
    encounters = await generate_encounters(session, stage_id, notify=False)
    if notify:
        await _publish_tournament_changed(stage.tournament_id, "structure_changed")
    return stage, encounters


async def generate_encounters(
    session: AsyncSession, stage_id: int, *, notify: bool = True
) -> list[models.Encounter]:
    """Generate bracket encounters for a stage based on its type and team inputs."""
    stage = await get_stage(session, stage_id)

    should_generate_by_item = (
        stage.stage_type in GROUPED_GENERATION_STAGE_TYPES and len(stage.items) > 1
    )

    if should_generate_by_item:
        encounters: list[models.Encounter] = []
        for item in stage.items:
            team_ids = _collect_item_team_ids(item)
            if len(team_ids) < 2:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Each group needs at least 2 teams to generate a bracket",
                )

            skeleton = await _generate_stage_skeleton(session, stage, team_ids, item.id)
            team_names_by_id = await _load_team_names(session, team_ids)
            encounters.extend(
                await _create_encounters_from_skeleton(
                    session,
                    stage,
                    skeleton,
                    item.id,
                    team_names_by_id=team_names_by_id,
                )
            )

        await session.commit()
        await standings_service.recalculate_for_tournament(session, stage.tournament_id)
        if notify:
            await _publish_tournament_changed(stage.tournament_id, "structure_changed")
        return encounters

    sorted_items = sorted(stage.items, key=lambda it: (it.order, it.id))
    primary_item_id = sorted_items[0].id if sorted_items else None

    # For DE stages: route LB encounters (negative round numbers) to the
    # BRACKET_LOWER stage item when one exists.
    lb_item = None
    if stage.stage_type == enums.StageType.DOUBLE_ELIMINATION:
        lb_item = next(
            (it for it in sorted_items if it.type == enums.StageItemType.BRACKET_LOWER),
            None,
        )
    lb_stage_item_id = lb_item.id if lb_item is not None else None

    # Decide which advancing teams start in the upper vs the lower bracket.
    lower_bracket_team_ids: list[int] = []
    if stage.stage_type == enums.StageType.DOUBLE_ELIMINATION and getattr(
        stage, "split_lower_bracket", False
    ):
        if lb_item is not None:
            # Separate Upper + Lower bracket items: the lower item's teams
            # start in the lower bracket.
            lower_bracket_team_ids = _collect_item_team_ids(lb_item)
            team_ids = [
                tid
                for item in sorted_items
                if item is not lb_item
                for tid in _collect_item_team_ids(item)
            ]
        else:
            # Single bracket item: seeds are ordered winners-first, so the first
            # half start in the upper bracket and the second half in the lower.
            all_ids: list[int] = []
            for item in sorted_items:
                all_ids.extend(_collect_item_team_ids(item))
            half = len(all_ids) // 2
            team_ids = all_ids[:half]
            lower_bracket_team_ids = all_ids[half:]
    else:
        team_ids = []
        for item in sorted_items:
            team_ids.extend(_collect_item_team_ids(item))

    if len(team_ids) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Need at least 2 teams to generate a bracket",
        )

    skeleton = await _generate_stage_skeleton(
        session,
        stage,
        team_ids,
        primary_item_id,
        lower_bracket_team_ids=lower_bracket_team_ids,
    )
    team_names_by_id = await _load_team_names(session, team_ids + lower_bracket_team_ids)
    encounters = await _create_encounters_from_skeleton(
        session,
        stage,
        skeleton,
        primary_item_id,
        team_names_by_id=team_names_by_id,
        lb_stage_item_id=lb_stage_item_id,
    )

    await session.commit()
    await standings_service.recalculate_for_tournament(session, stage.tournament_id)
    if notify:
        await _publish_tournament_changed(stage.tournament_id, "structure_changed")
    return encounters
