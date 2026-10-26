"""Stage activation and deactivation, and activate-then-generate."""

from sqlalchemy import func, select, update
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
    async def activate_stage(
        self,
        session: AsyncSession,
        stage_id: int,
        *,
        notify: bool = True,
        commit: bool = True,
        stage: models.Stage | None = None,
    ) -> models.Stage:
        """Activate a stage, resolving tentative inputs from previous stages.

        Activation moves the tournament to this stage's phase: stages of OTHER
        phases go inactive, same-phase siblings (the parallel Low/High divisions
        that share one ``order``) stay active beside it.
        """
        stage = stage or await self.get_stage(session, stage_id)

        await session.execute(
            update(models.Stage)
            .where(
                models.Stage.tournament_id == stage.tournament_id,
                models.Stage.order != stage.order,
            )
            .values(is_active=False)
        )

        stage.is_active = True
        # Sticky: unlike ``is_active`` this never gets cleared by another
        # stage's activation, so a bracket generated as a preview becomes -- and
        # stays -- reportable/veto-able from here on (see ``shared.services.
        # bracket.usability.is_encounter_live``).
        stage.is_published = True
        # That flag IS the room's "is this bracket live" gate, so activation is
        # what makes a preview stage's encounters owe their pick-ban sessions.
        # Nothing else about them is written here, and the room's state read
        # does not open a session on the way past either.
        request_stage_reconcile(session, stage.id)

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

        await self._notify_published_encounters(session, stage)
        await self._finish_structure_write(session, stage, notify=notify, commit=commit, schedule_standings=False)
        return stage

    async def _notify_published_encounters(self, session: AsyncSession, stage: models.Stage) -> None:
        """Tell the rosters of every complete pairing in a live stage.

        Two callers make pairings playable in bulk: activation (``is_published``
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

    async def deactivate_stage(
        self,
        session: AsyncSession,
        stage_id: int,
        *,
        notify: bool = True,
        commit: bool = True,
    ) -> models.Stage:
        """Revert an accidentally-activated stage back to Draft/preview.

        ``is_published`` is otherwise sticky
        because it gates whether an encounter is live for reporting/pick-ban
        (``src.services.bracket.usability.is_encounter_live``) -- once a
        captain has acted on a match, taking that gate back down would strand
        real data behind a bracket that looks like a preview again. So this only
        allows the revert while every one of the stage's encounters is still
        ``OPEN``: nothing has been reported or started yet, so there is nothing
        to strand. Refuses with 409 the moment any encounter left ``OPEN``.

        Does not unwind ``activate_stage``'s resolution of TENTATIVE inputs to
        FINAL -- re-wire from the source stage (``wire_from_groups``) if that
        also needs undoing.
        """
        stage = await self.get_stage(session, stage_id)
        touched = await session.scalar(
            select(func.count())
            .select_from(models.BracketEncounter)
            .join(models.Encounter, models.Encounter.id == models.BracketEncounter.encounter_id)
            .where(
                models.BracketEncounter.stage_id == stage_id,
                models.Encounter.status != enums.EncounterStatus.OPEN,
            )
        )
        if touched > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot revert to draft: this stage already has reported or in-progress matches.",
            )

        stage.is_active = False
        stage.is_published = False
        await self._finish_structure_write(session, stage, notify=notify, commit=commit, schedule_standings=False)
        return stage

    async def _check_upstream_stages_completed(self, session: AsyncSession, stage: models.Stage) -> list[int]:
        """Return ids of upstream stages that feed into ``stage`` via TENTATIVE
        inputs but are NOT yet marked ``is_completed``. Empty list means safe
        to activate. Used by ``activate_and_generate`` to prevent admins from
        freezing playoff seeds before groups finish.
        """
        source_item_ids = list(
            {
                inp.source_stage_item_id
                for item in stage.items
                for inp in item.inputs
                if inp.input_type == enums.StageItemInputType.TENTATIVE and inp.source_stage_item_id is not None
            }
        )
        if not source_item_ids:
            return []

        source_items = await self.stage_item_repo.bulk_get(session, source_item_ids)
        source_stage_ids = {item.stage_id for item in source_items if item.stage_id is not None}

        if not source_stage_ids:
            return []

        stages = await self.stage_repo.bulk_get(session, sorted(source_stage_ids))
        return [s.id for s in stages if not s.is_completed]

    async def activate_and_generate(
        self,
        session: AsyncSession,
        stage_id: int,
        *,
        force: bool = False,
        notify: bool = True,
        commit: bool = True,
        schedule_standings: bool = True,
    ) -> tuple[models.Stage, list[models.Encounter]]:
        """Combined endpoint: activate a stage (resolving TENTATIVE inputs) and
        immediately generate bracket encounters. Single click for the admin.

        Unless ``force=True``, raises HTTP 409 when any upstream (source) stage
        still has pending encounters — prevents freezing playoff seeds before
        groups are actually finished.
        """
        stage = await self.get_stage(session, stage_id)
        # Auto-wire playoff seeds from the preceding group stage. Runs BEFORE the
        # upstream-completion check so that check sees the freshly created
        # TENTATIVE inputs.
        await self._auto_wire_from_groups(session, stage)
        if not force:
            pending = await self._check_upstream_stages_completed(session, stage)
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

        stage = await self.activate_stage(session, stage_id, notify=False, commit=False, stage=stage)
        encounters = await self.generate_encounters(
            session,
            stage_id,
            notify=False,
            commit=False,
            schedule_standings=schedule_standings,
            stage=stage,
        )
        await self._finish_structure_write(session, stage, notify=notify, commit=commit, schedule_standings=False)
        return stage, encounters
