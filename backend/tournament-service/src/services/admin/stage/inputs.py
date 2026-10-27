"""Stage item inputs, one row at a time: create, edit, move between items and slots, delete."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src import schemas
from src.services.admin.stage.base import StageServiceBase
from src.services.tournament.events import enqueue_tournament_recalculation


class StageInputsMixin(StageServiceBase):
    async def _assert_input_assignable(
        self,
        session: AsyncSession,
        *,
        stage_id: int,
        stage_item_id: int,
        tournament_id: int,
        team_id: int | None,
        slot: int | None,
        exclude_input_id: int | None = None,
    ) -> models.StageItemInput | None:
        """The invariants every seed slot has to satisfy, whoever writes it.

        Creation and editing both go through here, so neither can write a second
        input on one slot, or a team from a different tournament (the FK only
        proves the team exists).

        Returns the OTHER input of this stage that already holds ``team_id``, if
        there is one -- editing swaps the two teams, creating has nothing to swap
        with and refuses.
        """
        if slot is not None:
            slot_filters = [
                models.StageItemInput.stage_item_id == stage_item_id,
                models.StageItemInput.slot == slot,
            ]
            if exclude_input_id is not None:
                slot_filters.append(models.StageItemInput.id != exclude_input_id)
            taken = await session.scalar(self.stage_item_input_repo.select().where(*slot_filters).limit(1))
            if taken is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Slot {slot} is already used in this stage item",
                )

        if team_id is None:
            return None

        team = await self.team_repo.get(session, team_id)
        if team is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
        if team.tournament_id != tournament_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Team does not belong to this tournament",
            )

        # Analytical: joins StageItem to scope the duplicate-team check to the
        # whole stage rather than the one item the input belongs to.
        duplicate_filters = [
            models.StageItem.stage_id == stage_id,
            models.StageItemInput.team_id == team_id,
        ]
        if exclude_input_id is not None:
            duplicate_filters.append(models.StageItemInput.id != exclude_input_id)
        return await session.scalar(
            self.stage_item_input_repo.select()
            .join(models.StageItem, models.StageItemInput.stage_item_id == models.StageItem.id)
            .where(*duplicate_filters)
            .limit(1)
        )

    async def _assert_source_in_tournament(
        self, session: AsyncSession, source_stage_item_id: int | None, tournament_id: int
    ) -> None:
        """A TENTATIVE seed qualifies from a group of THIS tournament.

        Activation copies the team the source's standings name, so a foreign
        item would seat another tournament's -- or workspace's -- team here.
        The foreign key only proves the item exists.
        """
        if source_stage_item_id is None:
            return
        source_tournament_id = await session.scalar(
            select(models.Stage.tournament_id)
            .join(models.StageItem, models.StageItem.stage_id == models.Stage.id)
            .where(models.StageItem.id == source_stage_item_id)
        )
        if source_tournament_id != tournament_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source stage item does not belong to this tournament",
            )

    async def create_stage_item_input(
        self,
        session: AsyncSession,
        stage_item_id: int,
        data: schemas.StageItemInputCreate,
    ) -> models.StageItemInput:
        stage_item = await self.stage_item_repo.get(
            session, stage_item_id, options=[selectinload(models.StageItem.stage)]
        )
        if not stage_item:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage item not found")
        tournament_id = stage_item.stage.tournament_id
        await self._assert_source_in_tournament(session, data.source_stage_item_id, tournament_id)
        duplicate = await self._assert_input_assignable(
            session,
            stage_id=stage_item.stage_id,
            stage_item_id=stage_item_id,
            tournament_id=tournament_id,
            team_id=data.team_id,
            slot=data.slot,
        )
        if duplicate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Selected team is already assigned in this stage; replace a populated slot to swap teams",
            )
        inp = models.StageItemInput(stage_item_id=stage_item_id, **data.model_dump())
        await self.stage_item_input_repo.create(session, inp)
        await enqueue_tournament_recalculation(session, tournament_id)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()
        await session.refresh(inp)
        return inp

    async def update_stage_item_input(
        self,
        session: AsyncSession,
        input_id: int,
        data: schemas.StageItemInputUpdate,
    ) -> models.StageItemInput:
        inp = await self.stage_item_input_repo.get(
            session,
            input_id,
            options=[selectinload(models.StageItemInput.stage_item).selectinload(models.StageItem.stage)],
        )
        if not inp:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage item input not found")

        tournament_id = inp.stage_item.stage.tournament_id
        stage_id = inp.stage_item.stage_id
        update_data = data.model_dump(exclude_unset=True)
        if not update_data:
            return inp

        if update_data.get("stage_item_id") is not None or update_data.get("slot") is not None:
            await self._move_input(session, inp, update_data.get("stage_item_id"), update_data.get("slot"))

        next_input_type = update_data.get("input_type", inp.input_type)
        next_team_id = update_data.get("team_id", inp.team_id)
        next_source_stage_item_id = update_data.get("source_stage_item_id", inp.source_stage_item_id)
        next_source_position = update_data.get("source_position", inp.source_position)

        if "team_id" in update_data and next_team_id is not None:
            existing_input = await self._assert_input_assignable(
                session,
                stage_id=stage_id,
                stage_item_id=inp.stage_item_id,
                tournament_id=tournament_id,
                team_id=next_team_id,
                slot=None,
                exclude_input_id=input_id,
            )
            if existing_input is not None:
                if inp.team_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=(
                            "Selected team is already assigned in this stage; replace a populated slot to swap teams"
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
                    detail=("TENTATIVE inputs require source_stage_item_id and source_position"),
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

        await self._assert_source_in_tournament(session, next_source_stage_item_id, tournament_id)
        inp.input_type = next_input_type
        inp.team_id = next_team_id
        inp.source_stage_item_id = next_source_stage_item_id
        inp.source_position = next_source_position

        await enqueue_tournament_recalculation(session, tournament_id)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()
        await session.refresh(inp)
        return inp

    async def delete_stage_item_input(self, session: AsyncSession, input_id: int) -> None:
        """Remove one seed slot. Inverse of create_stage_item_input.

        Encounters that already name the team stay; recalculation follows.
        """
        inp = await self.stage_item_input_repo.get(
            session,
            input_id,
            options=[selectinload(models.StageItemInput.stage_item).selectinload(models.StageItem.stage)],
        )
        if not inp:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage item input not found")
        tournament_id = inp.stage_item.stage.tournament_id
        await self._lock_stage(session, inp.stage_item.stage_id)
        await session.refresh(inp, ["stage_item_id"])  # a move may have committed before the lock
        stage_item_id = inp.stage_item_id
        await self.stage_item_input_repo.delete(session, inp)
        # The seeds below the removed one move up: a group is seeded 1..N, not 1..N with a hole.
        await self._reseat_slots(session, await self._item_inputs(session, [stage_item_id]))
        await enqueue_tournament_recalculation(session, tournament_id)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()

    async def _item_inputs(self, session: AsyncSession, stage_item_ids: list[int]) -> list[models.StageItemInput]:
        """These items' inputs in seed order."""
        return list(
            await session.scalars(
                self.stage_item_input_repo.select()
                .where(models.StageItemInput.stage_item_id.in_(stage_item_ids))
                .order_by(models.StageItemInput.slot, models.StageItemInput.id)
            )
        )

    async def _move_input(
        self,
        session: AsyncSession,
        inp: models.StageItemInput,
        stage_item_id: int | None,
        slot: int | None,
    ) -> None:
        """Re-seat ``inp`` at seed ``slot`` of ``stage_item_id`` (default: its own item, at the end).

        An insert, not a swap: the inputs between the old and the new seat shift
        by one, and the item it leaves closes the gap.
        """
        stage_id = inp.stage_item.stage_id
        await self._lock_stage(session, stage_id)
        await session.refresh(inp, ["stage_item_id"])  # a move may have committed before the lock
        source_item_id = inp.stage_item_id
        target_item_id = source_item_id if stage_item_id is None else stage_item_id
        if target_item_id != source_item_id:
            target_item = await self.stage_item_repo.get(session, target_item_id)
            if target_item is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage item not found")
            if target_item.stage_id != stage_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="A team can only move between the groups of its own stage",
                )

        rows = await self._item_inputs(session, [source_item_id, target_item_id])
        source = [row for row in rows if row.stage_item_id == source_item_id and row.id != inp.id]
        target = (
            source if target_item_id == source_item_id else [row for row in rows if row.stage_item_id == target_item_id]
        )
        target.insert(len(target) if slot is None else min(slot - 1, len(target)), inp)
        inp.stage_item_id = target_item_id
        await self._reseat_slots(session, *([target] if target is source else [source, target]))

    async def _reseat_slots(self, session: AsyncSession, *items: list[models.StageItemInput]) -> None:
        """Number each list's inputs 1..N in list order.

        Through negative slots first: ``uq_stage_item_input_item_slot`` is checked
        row by row, so renumbering in place can hand a row the slot a neighbour
        has not given up yet.
        """
        for temporary, row in enumerate((row for rows in items for row in rows), 1):
            row.slot = -temporary
        await session.flush()
        for rows in items:
            for slot, row in enumerate(rows, 1):
                row.slot = slot
        await session.flush()
