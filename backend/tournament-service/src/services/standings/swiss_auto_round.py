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
from collections.abc import Mapping, Sequence

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.domain.tournament_utils import (
    completed_encounters_in_finished_rounds,
    has_incomplete_playable_rounds,
)
from shared.repository import EncounterRepository, StageRepository
from src.services.admin.stage import _collect_item_team_ids, stage_service
from src.services.notifications.lifecycle import lifecycle_notifier
from src.services.standings.service import StageEncounter, standings_service

DEFAULT_STAGE_MAX_ROUNDS = 5


def stage_item_ready_for_next_round(
    encounters: list[StageEncounter],
) -> bool:
    rounds = {encounter.id: encounter.round for encounter in encounters}
    if not encounters:
        return False
    if has_incomplete_playable_rounds(encounters, rounds):
        return False
    return bool(completed_encounters_in_finished_rounds(encounters, rounds))


def next_round_number(encounters: list[StageEncounter]) -> int | None:
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
        *,
        stages: Sequence[models.Stage] | None = None,
        encounters: Mapping[int, list[StageEncounter]] | None = None,
    ) -> list[models.Encounter]:
        """Generate the next Swiss round for every closed active scope.

        The standings job passes what its ranking already loaded: the tournament's ``stages`` (items and inputs
        loaded) and each stage's ``encounters`` by stage id. Without them both are read here, fresh.
        """
        if stages is None:
            result = await session.execute(
                self.stage_repo.select()
                .where(
                    models.Stage.tournament_id == tournament_id,
                    models.Stage.stage_type == enums.StageType.SWISS,
                    models.Stage.is_active == True,  # noqa: E712
                )
                .options(selectinload(models.Stage.items).selectinload(models.StageItem.inputs))
                # Fresh even when the identity map holds these rows: a rolled-back savepoint left them expired.
                .execution_options(populate_existing=True)
            )
            swiss_stages = result.scalars().all()
        else:
            swiss_stages = [stage for stage in stages if stage.stage_type == enums.StageType.SWISS and stage.is_active]
        if not swiss_stages:
            return []

        encounters_by_key: dict[tuple[int, int | None], list[StageEncounter]] = defaultdict(list)
        for stage in swiss_stages:
            stage_encounters = encounters.get(stage.id) if encounters is not None else None
            if stage_encounters is None:
                stage_encounters = await standings_service.load_stage_encounters(session, stage.id)
            for encounter in stage_encounters:
                encounters_by_key[(stage.id, encounter.stage_item_id)].append(encounter)

        generated: list[models.Encounter] = []
        for stage in swiss_stages:
            items = stage.items or []
            scopes: list[tuple[int | None, list[StageEncounter]]] = (
                [(item.id, encounters_by_key.get((stage.id, item.id), [])) for item in items]
                if items
                else [(None, encounters_by_key.get((stage.id, None), []))]
            )
            for stage_item_id, item_encounters in scopes:
                # No stopped-scope shortcut: a scope that once had no
                # complete pairing may have one again after a round is
                # re-generated, and generation re-marks it when it truly does
                # not. Skipping on the flag would make the stop permanent.
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
                        encounters=item_encounters,
                    )
                )
        return generated

    async def generate_next_swiss_round(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        stage_id: int,
        stage_item_id: int | None,
        expected_next_round: int | None,
        stage: models.Stage | None = None,
        encounters: list[StageEncounter] | None = None,
    ) -> list[models.Encounter]:
        """Generate one Swiss round without committing or recalculating standings.

        ``encounters``: the scope's encounters when the caller already loaded them; read here otherwise.
        """
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

        current_encounters = (
            encounters
            if encounters is not None
            else await self._get_stage_item_encounters(session, stage_id, stage_item_id)
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

        skeleton = await stage_service._generate_stage_skeleton(
            session, stage, team_ids, stage_item_id, encounters=current_encounters
        )
        if not skeleton.pairings:
            await session.flush()
            logger.info(
                "Swiss auto-round: scope completed, no round left to pair",
                stage_id=stage_id,
                stage_item_id=stage_item_id,
            )
            return []

        created = await stage_service._create_encounters_from_skeleton(
            session,
            stage,
            skeleton,
            stage_item_id,
            teams_by_id=await stage_service._seat_teams(session, team_ids),
        )
        await session.flush()

        # DMs only: a Swiss round pairs the whole scope at once, and a channel
        # post per pairing is spam.
        await lifecycle_notifier.on_encounters_changed(session, created, channel=False)

        logger.info(
            "Swiss auto-round: generated {} encounters for round {}",
            len(created),
            skeleton.pairings[0].round_number if skeleton.pairings else "?",
            stage_id=stage_id,
            stage_item_id=stage_item_id,
            tournament_id=tournament_id,
        )

        return created

    async def _get_stage_item_encounters(
        self,
        session: AsyncSession,
        stage_id: int,
        stage_item_id: int | None,
    ) -> list[StageEncounter]:
        return [
            encounter
            for encounter in await standings_service.load_stage_encounters(session, stage_id)
            if encounter.stage_item_id == stage_item_id
        ]


swiss_rounds_service = SwissRoundsService()
