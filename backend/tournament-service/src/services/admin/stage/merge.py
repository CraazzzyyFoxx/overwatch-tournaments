"""Merging group stages into one, their pick-ban configs included."""

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.tournament.pick_ban import PickBanConfig, PickBanConfigSlot
from src.services.admin.stage.base import StageServiceBase
from src.services.admin.stage_common import (
    GROUPED_GENERATION_STAGE_TYPES,
    _pick_ban_config_signature,
)
from src.services.tournament.events import enqueue_tournament_recalculation


class StageMergeMixin(StageServiceBase):
    async def _merge_pick_ban_configs(
        self,
        session: AsyncSession,
        *,
        target_stage: models.Stage,
        source_stage_ids: list[int],
        kind: enums.PickBanKind,
    ) -> None:
        """Collapse the source stages' ``kind`` pick-ban configs onto ``target_stage``.

        The target's own config wins; otherwise the sources must agree and one
        of them moves over. Called once per kind so a tournament's map and hero
        configs are deduped independently."""
        target_configs = list(
            await self.pick_ban_config_repo.list_for_stages(
                session,
                tournament_id=target_stage.tournament_id,
                kind=kind,
                stage_ids=[target_stage.id],
            )
        )
        if len(target_configs) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Target stage has multiple {kind.value} pick-ban configs; resolve them before merging",
            )

        source_configs = list(
            await self.pick_ban_config_repo.list_for_stages(
                session,
                tournament_id=target_stage.tournament_id,
                kind=kind,
                stage_ids=source_stage_ids,
                options=[
                    selectinload(PickBanConfig.items),
                    selectinload(PickBanConfig.slots).selectinload(PickBanConfigSlot.items),
                ],
            )
        )
        if not source_configs:
            return

        if target_configs:
            for config in source_configs:
                await session.delete(config)
            return

        signatures = {_pick_ban_config_signature(config) for config in source_configs}
        if len(signatures) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Source stages have different {kind.value} pick-ban configs; keep one target config before merging"
                ),
            )

        keeper = source_configs[0]
        keeper.stage_id = target_stage.id
        for config in source_configs[1:]:
            await session.delete(config)

    async def _retarget_stage_rows(
        self,
        session: AsyncSession,
        model,
        *,
        source_stage_ids: list[int],
        target_stage_id: int,
    ) -> None:
        # Generic over Encounter/Standing/ChallongeSource; no single repository
        # can express it.
        result = await session.execute(select(model).where(model.stage_id.in_(source_stage_ids)))
        for row in result.scalars().all():
            row.stage_id = target_stage_id

    async def merge_group_stages(
        self,
        session: AsyncSession,
        *,
        target_stage_id: int,
        source_stage_ids: list[int],
        target_name: str | None = None,
    ) -> models.Stage:
        """Merge one-group stages into one grouped stage.

        Some tournaments carry A/B/C/D as separate Stage rows; the canonical shape
        is one grouped Stage with A/B/C/D as StageItem rows, so this moves source
        items and all stage-scoped references to the selected target stage.
        """
        target_stage = await self.get_stage(session, target_stage_id)
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

        source_by_id = {stage.id: stage for stage in await self.stage_repo.bulk_get(session, unique_source_stage_ids)}
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

        # Analytical: joins Stage purely to order the items by their owning
        # stage's order, so the merged group numbering follows stage order.
        items_result = await session.execute(
            self.stage_item_repo.select()
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

        for kind in (enums.PickBanKind.MAP, enums.PickBanKind.HERO):
            await self._merge_pick_ban_configs(
                session,
                target_stage=target_stage,
                source_stage_ids=unique_source_stage_ids,
                kind=kind,
            )

        for model in (
            # The encounter's stage is its bracket POSITION, so that is the
            # row a merge moves; the encounter itself has no stage.
            models.BracketEncounter,
            models.Standing,
            models.ChallongeSource,
        ):
            await self._retarget_stage_rows(
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
        # A merge retargets the source stages' encounters onto `target_stage`
        # (`_retarget_stage_rows` above); if any source was already published,
        # those encounters must stay reportable under their new stage.
        target_stage.is_published = target_stage.is_published or any(stage.is_published for stage in source_stages)
        target_stage.is_completed = target_stage.is_completed and all(stage.is_completed for stage in source_stages)

        await session.flush()
        for source_stage in source_stages:
            await self.stage_repo.delete(session, source_stage)

        await enqueue_tournament_recalculation(session, target_stage.tournament_id)
        await self._publish_structure_changed(session, target_stage.tournament_id)
        await session.commit()

        logger.info(
            "Merged {} source group stages into stage {} for tournament {}",
            len(source_stage_ids),
            target_stage.id,
            target_stage.tournament_id,
        )
        return await self.get_stage(session, target_stage.id)
