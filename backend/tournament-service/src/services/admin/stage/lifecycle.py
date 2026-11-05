"""The stage hooks of ``FlowNodeService``: seat the inputs, start, revert to draft (spec §5.3)."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src.services.admin.stage.base import StageServiceBase
from src.services.admin.stage.qualification import _boundary_tie_unresolved
from src.services.encounter.room_reconcile import request_stage_reconcile
from src.services.notifications.lifecycle import lifecycle_notifier


class StageLifecycleMixin(StageServiceBase):
    async def seat_inputs(self, session: AsyncSession, stage: models.Stage) -> None:
        """Hook ``draft → ready``: wire the playoff from its groups, then resolve tentative inputs to teams.

        ``_auto_wire_from_groups`` runs first so the loop sees the freshly created TENTATIVE inputs.
        """
        await self._auto_wire_from_groups(session, stage)

        source_item_ids = {
            inp.source_stage_item_id
            for item in stage.items
            for inp in item.inputs
            if inp.input_type == enums.StageItemInputType.TENTATIVE
            and inp.source_stage_item_id is not None
            and inp.source_position is not None
        }
        standings_by_item: dict[int, list[models.Standing]] = {}
        if source_item_ids:
            standings_result = await session.execute(
                self.standing_repo.select()
                .where(models.Standing.stage_item_id.in_(source_item_ids))
                .order_by(models.Standing.stage_item_id, models.Standing.position)
            )
            for standing in standings_result.scalars():
                standings_by_item.setdefault(standing.stage_item_id, []).append(standing)

        for item in stage.items:
            for inp in item.inputs:
                if inp.input_type != enums.StageItemInputType.TENTATIVE:
                    continue
                if inp.source_stage_item_id is None or inp.source_position is None:
                    continue
                standings = standings_by_item.get(inp.source_stage_item_id, [])
                if inp.source_position <= len(standings):
                    if _boundary_tie_unresolved(standings, inp.source_position):
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail=(
                                "unresolved tie at qualification boundary; pin the order in Standings "
                                f"(source stage item {inp.source_stage_item_id}, "
                                f"position {inp.source_position})"
                            ),
                        )
                    inp.team_id = standings[inp.source_position - 1].team_id
                    inp.input_type = enums.StageItemInputType.FINAL

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

        Does not unwind ``seat_inputs``' resolution of TENTATIVE inputs to FINAL -- re-wire from the source stage
        (``wire_from_groups``) if that also needs undoing.
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
