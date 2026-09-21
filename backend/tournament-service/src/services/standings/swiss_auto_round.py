"""Auto-generate the next Swiss round after standings recompute.

``generate_ready_rounds`` runs in the standings worker and materialises the
next round in the same transaction. ``generate_next_swiss_round`` re-checks
the same gates so a leftover bracket job is a no-op.

A Swiss stage can be temporarily marked completed when the current round
is closed but the next round has not been generated yet, so stage
completion is not used as a candidate filter here.
"""

from __future__ import annotations

from collections import defaultdict

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import enums
from shared.repository import EncounterRepository, StageRepository
from shared.domain.tournament_utils import (
    completed_encounters_in_finished_rounds,
    has_incomplete_playable_rounds,
)
from src import models
from src.services.admin.stage import _collect_item_team_ids, stage_service

DEFAULT_STAGE_MAX_ROUNDS = 5


def stage_item_ready_for_next_round(
    encounters: list[models.Encounter],
) -> bool:
    if not encounters:
        return False
    if has_incomplete_playable_rounds(encounters):
        return False
    return bool(completed_encounters_in_finished_rounds(encounters))


def next_round_number(encounters: list[models.Encounter]) -> int | None:
    rounds = [encounter.round for encounter in encounters if encounter.round is not None]
    if not rounds:
        return None
    return max(rounds) + 1


def stage_max_rounds(stage: models.Stage) -> int:
    raw_value = getattr(stage, "max_rounds", DEFAULT_STAGE_MAX_ROUNDS)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return DEFAULT_STAGE_MAX_ROUNDS
    return max(1, value)


def stage_allows_next_round(stage: models.Stage, next_round: int | None) -> bool:
    return next_round is not None and next_round <= stage_max_rounds(stage)


class SwissRoundsService:
    def __init__(
        self,
        *,
        stage_repo: StageRepository = StageRepository(),
        encounter_repo: EncounterRepository = EncounterRepository(),
    ) -> None:
        self.stage_repo = stage_repo
        self.encounter_repo = encounter_repo

    async def generate_ready_rounds(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> list[models.Encounter]:
        """Generate the next Swiss round for every closed active scope."""
        result = await session.execute(
            self.stage_repo.select()
            .where(
                models.Stage.tournament_id == tournament_id,
                models.Stage.stage_type == enums.StageType.SWISS,
                models.Stage.is_active == True,  # noqa: E712
            )
            .options(selectinload(models.Stage.items).selectinload(models.StageItem.inputs))
        )
        swiss_stages = result.scalars().all()
        if not swiss_stages:
            return []

        stage_ids = [stage.id for stage in swiss_stages]
        encounters_result = await session.execute(
            self.encounter_repo.select().where(models.Encounter.stage_id.in_(stage_ids))
        )
        encounters_by_key: dict[tuple[int, int | None], list[models.Encounter]] = defaultdict(list)
        for encounter in encounters_result.scalars().all():
            encounters_by_key[(encounter.stage_id, encounter.stage_item_id)].append(encounter)

        generated: list[models.Encounter] = []
        for stage in swiss_stages:
            items = stage.items or []
            scopes: list[tuple[int | None, list[models.Encounter]]] = (
                [(item.id, encounters_by_key.get((stage.id, item.id), [])) for item in items]
                if items
                else [(None, encounters_by_key.get((stage.id, None), []))]
            )
            for stage_item_id, item_encounters in scopes:
                # No stopped-scope shortcut: a scope that once had no
                # rematch-free pairing may have one again after a round is
                # re-generated, and generation re-marks it when it truly does
                # not. Skipping on the flag made the stop permanent.
                if not stage_item_ready_for_next_round(item_encounters):
                    continue
                next_round = next_round_number(item_encounters)
                if not stage_allows_next_round(stage, next_round):
                    logger.info(
                        "Swiss auto-round: stage max rounds reached",
                        stage_id=stage.id,
                        stage_item_id=stage_item_id,
                        next_round=next_round,
                        max_rounds=stage_max_rounds(stage),
                    )
                    continue
                generated.extend(
                    await self.generate_next_swiss_round(
                        session,
                        tournament_id=tournament_id,
                        stage_id=stage.id,
                        stage_item_id=stage_item_id,
                        expected_next_round=next_round,
                        stage=stage,
                    )
                )
        return generated

    async def enqueue_swiss_next_rounds(
        self,
        session: AsyncSession,
        tournament_id: int,
    ) -> list[models.Encounter]:
        """Backward-compatible name: generate ready rounds in-process."""
        return await self.generate_ready_rounds(session, tournament_id)

    async def generate_next_swiss_round(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        stage_id: int,
        stage_item_id: int | None,
        expected_next_round: int | None,
        stage: models.Stage | None = None,
    ) -> list[models.Encounter]:
        """Generate one Swiss round without committing or recalculating standings."""
        stage = stage or await stage_service.get_stage(session, stage_id)

        if not stage.is_active:
            logger.warning(
                "Swiss auto-round: stage is not active, skipping",
                stage_id=stage_id,
            )
            return []

        item: models.StageItem | None = None
        team_ids: list[int] = []

        if stage_item_id is not None:
            item = next((i for i in stage.items if i.id == stage_item_id), None)
            if item is None:
                logger.error(
                    "Swiss auto-round: stage item not found",
                    stage_item_id=stage_item_id,
                )
                return []
            team_ids = _collect_item_team_ids(item)
        else:
            for i in stage.items:
                team_ids.extend(_collect_item_team_ids(i))

        if len(team_ids) < 2:
            logger.warning(
                "Swiss auto-round: not enough teams",
                stage_id=stage_id,
                stage_item_id=stage_item_id,
            )
            return []

        current_encounters = await self._get_stage_item_encounters(
            session,
            stage_id,
            stage_item_id,
        )
        actual_next_round = next_round_number(current_encounters)
        if expected_next_round is not None:
            if actual_next_round != expected_next_round:
                logger.info(
                    "Swiss auto-round: stale event skipped",
                    stage_id=stage_id,
                    stage_item_id=stage_item_id,
                    event_next_round=expected_next_round,
                    expected_next_round=actual_next_round,
                )
                return []

        if not stage_allows_next_round(stage, actual_next_round):
            logger.info(
                "Swiss auto-round: stage max rounds reached, skipping",
                stage_id=stage_id,
                stage_item_id=stage_item_id,
                next_round=actual_next_round,
                max_rounds=stage_max_rounds(stage),
            )
            return []

        if not stage_item_ready_for_next_round(current_encounters):
            logger.info(
                "Swiss auto-round: current round is not closed, skipping",
                stage_id=stage_id,
                stage_item_id=stage_item_id,
            )
            return []

        skeleton = await stage_service._generate_stage_skeleton(session, stage, team_ids, stage_item_id)
        if not skeleton.pairings:
            await session.flush()
            logger.info(
                "Swiss auto-round: scope completed because no non-rematch pairing exists",
                stage_id=stage_id,
                stage_item_id=stage_item_id,
            )
            return []

        team_names_by_id = await stage_service._load_team_names(session, team_ids)
        encounters = await stage_service._create_encounters_from_skeleton(
            session,
            stage,
            skeleton,
            stage_item_id,
            team_names_by_id=team_names_by_id,
        )
        await session.flush()

        logger.info(
            "Swiss auto-round: generated %d encounters for round %d",
            len(encounters),
            skeleton.pairings[0].round_number if skeleton.pairings else "?",
            stage_id=stage_id,
            stage_item_id=stage_item_id,
            tournament_id=tournament_id,
        )

        return encounters

    async def _get_stage_item_encounters(
        self,
        session: AsyncSession,
        stage_id: int,
        stage_item_id: int | None,
    ) -> list[models.Encounter]:
        return list(
            await self.encounter_repo.list_for_stage_scope(session, stage_id=stage_id, stage_item_id=stage_item_id)
        )


swiss_rounds_service = SwissRoundsService()
