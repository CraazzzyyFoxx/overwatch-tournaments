"""Re-applying a stage's best-of configuration to the encounters it already has."""

from collections import Counter, defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from src.domain.admin.best_of import best_of_config, resolve_best_of, resolve_swiss_best_of
from src.domain.bracket import SwissThresholds
from src.services.admin.stage.base import StageServiceBase
from src.services.admin.stage_common import BRACKET_STAGE_TYPES
from src.services.bracket.swiss_state import bye_rounds
from src.services.encounter.ffa import ffa_encounter_service
from src.services.standings.service import rank_group, standings_service
from src.services.tournament.events import enqueue_tournament_recalculation


class StageBestOfMixin(StageServiceBase):
    async def apply_best_of_to_existing(self, session: AsyncSession, stage_id: int) -> int:
        """Backfill ``best_of`` on a stage's existing encounters from its config.

        Reads the stage's best-of config and rewrites each encounter's
        ``best_of`` in place (preserving scores/results). Applies the same
        resolution the generator uses; ``final`` targets the max round among the
        stage's encounters for elimination stages, and a Swiss stage with
        thresholds judges each encounter on the records its teams brought into
        its round. Returns the number of rows whose ``best_of`` actually changed.
        """
        stage = await self.get_stage(session, stage_id)
        cfg = best_of_config(stage)
        thresholds = SwissThresholds.of(stage)
        stakes = (
            await self._swiss_stakes(session, stage, thresholds)
            if stage.stage_type == enums.StageType.SWISS and thresholds
            else {}
        )
        is_elimination = stage.stage_type in BRACKET_STAGE_TYPES

        # ``EncounterRepository.list_by_stage`` also predicates on tournament_id
        # and orders the rows; neither matches this backfill's scan.
        result = await session.execute(
            select(models.Encounter, models.BracketEncounter.round)
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(models.BracketEncounter.stage_id == stage_id)
        )
        rows = result.tuples().all()
        max_round = max((round_number for _encounter, round_number in rows), default=0)

        targets: dict[int, int] = {}
        for encounter, round_number in rows:
            at_stake = stakes.get(encounter.id)
            targets[encounter.id] = (
                resolve_swiss_best_of(cfg, round_number, qualification=at_stake[0], elimination=at_stake[1])
                if at_stake is not None
                else resolve_best_of(cfg, round_number, is_final=is_elimination and round_number == max_round)
            )
        moving = sorted(encounter.id for encounter, _round in rows if encounter.best_of != targets[encounter.id])
        if not moving:
            await session.commit()
            return 0

        # Lock order of every result writer: the encounters first (all of them, in id order, re-read under the
        # lock), the recalculation state last. A lobby's settle requests the standings itself, and with the
        # encounters locked one by one that request would come between two of them. A lobby that settles or
        # reopens also advances into -- or resets -- every encounter its links reach (``reset_downstream``
        # recurses), so that closure is locked up front with it.
        lobby_ids = [
            encounter.id
            for encounter, _round in rows
            if encounter.id in moving and encounter.scoring_preset == "points"
        ]
        downstream: list[int] = []
        if lobby_ids:
            link = models.EncounterLink
            reached = (
                select(link.target_encounter_id.label("id"))
                .where(link.source_encounter_id.in_(lobby_ids))
                .cte("reached", recursive=True)
            )
            reached = reached.union(
                select(link.target_encounter_id).join(reached, link.source_encounter_id == reached.c.id)
            )
            downstream = list((await session.execute(select(reached.c.id))).scalars().all())
        locked = await session.scalars(
            self.encounter_repo.select()
            .where(models.Encounter.id.in_(sorted({*moving, *downstream})))
            .order_by(models.Encounter.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        changed = 0
        for encounter in locked.all():
            # A downstream encounter is locked, not rewritten, unless it is one of this stage's own.
            if encounter.id not in targets or encounter.best_of == targets[encounter.id]:
                continue
            encounter.best_of = targets[encounter.id]
            changed += 1
            # A lobby's completion is derived from "confirmed games >= best_of",
            # so moving the bar here settles or reopens it. A duel's
            # is decided by its series score, which this does not touch.
            if encounter.scoring_preset == "points":
                await ffa_encounter_service.refresh_completion(session, encounter, actor_user_id=None)

        if changed:
            # Last, after every encounter above: a series length is a standings input.
            await enqueue_tournament_recalculation(session, stage.tournament_id)
            await self._publish_structure_changed(session, stage.tournament_id)
        await session.commit()
        return changed

    async def _swiss_stakes(
        self, session: AsyncSession, stage: models.Stage, thresholds: SwissThresholds
    ) -> dict[int, tuple[bool, bool]]:
        """``encounter_id -> (qualification, elimination)`` for every Swiss encounter.

        Replayed per round off the results and byes of the rounds before it --
        what the teams brought into the round, as the generator saw them. A bye
        stored without a round predates round tracking and counts everywhere.
        """
        tournament = await session.get_one(models.Tournament, stage.tournament_id)
        items = {item.id: item for item in stage.items}
        byes = await bye_rounds(session, stage.id)
        by_scope: defaultdict[int | None, list] = defaultdict(list)
        for encounter in await standings_service.load_stage_encounters(session, stage.id):
            by_scope[encounter.stage_item_id].append(encounter)

        stakes: dict[int, tuple[bool, bool]] = {}
        for stage_item_id, encounters in by_scope.items():
            for round_number in {encounter.round for encounter in encounters}:
                bye_counts = Counter(
                    team_id
                    for team_id, bye_round in byes.get(stage_item_id, ())
                    if bye_round is None or bye_round < round_number
                )
                ranked = rank_group(
                    tournament,
                    stage,
                    items.get(stage_item_id),
                    [encounter for encounter in encounters if encounter.round < round_number],
                    bye_counts=bye_counts,
                )
                records = {team.team_id: (team.wins + bye_counts[team.team_id], team.loses) for team in ranked}
                for encounter in encounters:
                    if encounter.round == round_number:
                        stakes[encounter.id] = thresholds.stakes(
                            records.get(seat.team_id, (0, 0)) for seat in encounter.seats
                        )
        return stakes
