"""The stage hooks of ``FlowNodeService``: seat the inputs, start, revert to draft (spec §5.3)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.errors import BaseAPIException as HTTPException
from src.services.admin.stage.base import StageServiceBase
from src.services.encounter.room_reconcile import request_stage_reconcile
from src.services.notifications.lifecycle import lifecycle_notifier
from src.services.tournament.events import enqueue_tournament_recalculation


class StageLifecycleMixin(StageServiceBase):
    async def seat_inputs(self, session: AsyncSession, stage: models.Stage) -> None:
        """Hook ``draft → ready``: seat the teams of the stage's flow input (spec §5.3, plan Decision 1).

        A stage the admin already seeded keeps its seats, each stamped with its input row (a seeded team the input
        does not hold is refused); otherwise every input is replaced by the seating the input's rows and the stage's
        ``seed_ranking`` plan. A stage without an input edge, and an individual Swiss stage, is left alone.
        """
        await self._lock_stage(session, stage.id)
        if stage.stage_type == enums.StageType.INDIVIDUAL_SWISS:
            return
        _, rows = await self._stage_input_rows(session, stage)
        if not rows:
            return
        # Re-read under the lock: a seed writer may have committed between the hook's load and the lock.
        stage = await self.get_stage(session, stage.id, populate_existing=True)
        if not stage.items:
            raise ApiHTTPException(
                status_code=400,
                detail=[
                    ApiExc(
                        code="stage_has_no_items",
                        msg="Add a group or bracket to this stage before it is ready",
                    )
                ],
            )
        inputs = [inp for item in stage.items for inp in item.inputs]
        seated = [inp for inp in inputs if inp.input_type == enums.StageItemInputType.FINAL and inp.team_id is not None]
        if seated:
            result_of = {row.team_id: row.id for row in rows}
            outside = sorted({inp.team_id for inp in seated if inp.team_id not in result_of})
            if outside:
                raise ApiHTTPException(
                    status_code=409,
                    detail=[
                        ApiExc(
                            code="seed_not_in_input", msg=f"Teams {outside} are seeded but not in this stage's input"
                        )
                    ],
                )
            for inp in seated:
                inp.source_result_id = result_of[inp.team_id]
            return
        for inp in inputs:
            await self.stage_item_input_repo.delete(session, inp)
        plan = await self._plan_for(session, stage, rows)
        await self.stage_item_input_repo.create_many(
            session,
            [
                models.StageItemInput(
                    stage_item_id=item_id,
                    slot=slot,
                    input_type=enums.StageItemInputType.FINAL,
                    team_id=one.team_id,
                    source_result_id=one.result_id,
                )
                for item_id, seats in plan.items()
                for slot, one in enumerate(seats, 1)
            ],
        )
        await enqueue_tournament_recalculation(session, stage.tournament_id)

    async def start_stage(self, session: AsyncSession, stage: models.Stage) -> list[models.Encounter]:
        """Hook ``ready → live``: publish the stage, generate its encounters when it has none, tell the rosters."""
        # ``is_published`` is the room's "is this bracket live" gate, so this is what makes a preview stage's
        # encounters owe their pick-ban sessions. Nothing else about them is written here.
        stage.is_published = True
        request_stage_reconcile(session, stage.id)
        if await self._count_stage_encounters(session, stage.id):
            await self._notify_published_encounters(session, stage)
            return []
        # Generation into a published stage tells the rosters itself.
        return await self.generate_encounters(session, stage.id, notify=False, commit=False, stage=stage)

    async def _notify_published_encounters(self, session: AsyncSession, stage: models.Stage) -> None:
        """Tell the rosters of every complete pairing in a live stage.

        Two callers make pairings playable in bulk: the stage going live (``is_published``
        is what the room gates on, so until then they were a preview nobody
        could enter) and generation into an already-published stage -- above
        all ``_fill_bracket_seeds`` writing the group winners into a playoff
        that went live with TBD slots. Already-told pairings are deduped by the
        notifier's key.

        DMs only (``channel=False``): a bracket going live readies a dozen
        encounters at once, and a dozen channel posts is spam.
        """
        # Fully seated, not "both team columns set": a pairing is complete when
        # it has as many live participations as it has slots, which is the
        # same question for a duel and for a lobby.
        seated = (
            select(func.count())
            .select_from(models.EncounterTeam)
            .where(
                models.EncounterTeam.encounter_id == models.Encounter.id,
                models.EncounterTeam.active.is_(True),
            )
            .scalar_subquery()
        )
        result = await session.execute(
            self.encounter_repo.select()
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(models.BracketEncounter.stage_id == stage.id, seated >= models.Encounter.slot_count)
        )
        # No channel post: a bracket going live readies a dozen encounters at once.
        await lifecycle_notifier.on_encounters_changed(session, list(result.scalars()), channel=False)

    async def revert_to_draft(self, session: AsyncSession, stage: models.Stage) -> None:
        """Hook ``ready → draft``: refuse once a match was reported, otherwise take the stage back to a preview.

        ``is_published`` gates whether an encounter is live for reporting/pick-ban
        (``src.services.bracket.usability.is_encounter_live``): once a captain has acted on a match, taking that gate
        back down would strand real data behind a bracket that looks like a preview again. So the revert is allowed
        only while every one of the stage's encounters is still ``OPEN``.

        Keeps the seats ``seat_inputs`` wrote: the next ``draft → ready`` stamps them again and refuses a team the
        input no longer holds, so clear the stage's seeds first when the input changed.
        """
        touched = await session.scalar(
            select(func.count())
            .select_from(models.BracketEncounter)
            .join(models.Encounter, models.Encounter.id == models.BracketEncounter.encounter_id)
            .where(
                models.BracketEncounter.stage_id == stage.id,
                models.Encounter.status != enums.EncounterStatus.OPEN,
            )
        )
        if touched > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot revert to draft: this stage already has reported or in-progress matches.",
            )
        stage.is_published = False
