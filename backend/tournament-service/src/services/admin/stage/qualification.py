"""Requalification: ready stages re-seated from their input's current results (spec §8.4)."""

from collections import defaultdict

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.core import enums
from shared.domain.encounter_naming import build_encounter_name_from_ids
from shared.services.encounter.participants import active_teams, place_team, vacate_slot
from shared.services.flow_queries import input_boundary_tied
from src.services.admin.stage.base import StageServiceBase
from src.services.notifications.lifecycle import lifecycle_notifier


class StageQualificationMixin(StageServiceBase):
    async def reseat_ready_stages(self, session: AsyncSession, tournament_id: int) -> int:
        """Re-plan every ``ready`` stage from its input's current rows and move the seats that changed.

        A ``ready`` stage is the only one downstream of a result that may still follow it (a ``live`` one is refused by
        ``flow.corrections``). A stage with a hand-edited seat or whose input filter waits on a boundary tie is left
        alone. Returns how many seats changed hands, were added or removed.
        """
        stage_ids = await session.scalars(
            select(models.FlowNode.stage_id)
            .where(
                models.FlowNode.tournament_id == tournament_id,
                models.FlowNode.kind == enums.FlowNodeKind.STAGE,
                models.FlowNode.status == enums.FlowNodeStatus.READY,
            )
            .order_by(models.FlowNode.id)
        )
        return sum([await self._reseat_stage(session, stage_id) for stage_id in stage_ids.all()])

    async def _reseat_stage(self, session: AsyncSession, stage_id: int) -> int:
        stage = await self.get_stage(session, stage_id, populate_existing=True)
        if stage.stage_type == enums.StageType.INDIVIDUAL_SWISS:
            return 0
        node, rows = await self._stage_input_rows(session, stage)
        current = {(item.id, inp.slot): inp for item in stage.items for inp in item.inputs}
        seated = [inp for inp in current.values() if inp.team_id is not None]
        in_input = {row.team_id for row in rows}
        # A seat without its source row is an admin's hand edit -- unless its team left the input, which is what
        # deleting the team's result row (``ON DELETE SET NULL``) looks like.
        hand_edited = any(inp.source_result_id is None and inp.team_id in in_input for inp in seated)
        if node is None or not rows or not seated or hand_edited or await input_boundary_tied(session, node.id):
            return 0
        plan = await self._plan_for(session, stage, rows)
        wanted = {(item_id, slot): one for item_id, seats in plan.items() for slot, one in enumerate(seats, 1)}
        added = [key for key in wanted if key not in current]
        removed = [inp for key, inp in current.items() if key not in wanted and inp.team_id is not None]
        # A bracket that already has encounters cannot grow or shrink here.
        if (added or removed) and await self._count_stage_encounters(session, stage.id):
            return 0
        changed = [
            key
            for key, one in wanted.items()
            if key in current and (current[key].team_id, current[key].source_result_id) != (one.team_id, one.result_id)
        ]
        item_ids = {key[0] for key in [*added, *changed]} | {inp.stage_item_id for inp in removed}
        if not item_ids:
            return 0
        # Encounter rows first: a write racing this reseat waits here, and the rows are re-read below under the lock.
        await session.execute(
            select(models.Encounter.id)
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(models.BracketEncounter.stage_item_id.in_(sorted(item_ids)))
            .with_for_update(of=models.Encounter)
        )
        # One mapping per item, applied in a single pass: two seats that swapped teams would otherwise chase each other.
        replacements: dict[int, dict[int, int]] = {}
        moved = len(added) + len(removed)
        for key in changed:
            inp, one = current[key], wanted[key]
            if inp.team_id != one.team_id:
                moved += 1
                if inp.team_id is not None:
                    replacements.setdefault(key[0], {})[inp.team_id] = one.team_id
            inp.team_id, inp.source_result_id = one.team_id, one.result_id
            inp.input_type = enums.StageItemInputType.FINAL
        for inp in removed:
            await self.stage_item_input_repo.delete(session, inp)
        await self.stage_item_input_repo.create_many(
            session,
            [
                models.StageItemInput(
                    stage_item_id=key[0],
                    slot=key[1],
                    input_type=enums.StageItemInputType.FINAL,
                    team_id=wanted[key].team_id,
                    source_result_id=wanted[key].result_id,
                )
                for key in added
            ],
        )
        for stage_item_id, mapping in replacements.items():
            await self._replace_teams_in_stage_item(session, stage_item_id=stage_item_id, mapping=mapping)
        return moved

    async def _replace_teams_in_stage_item(
        self,
        session: AsyncSession,
        *,
        stage_item_id: int,
        mapping: dict[int, int],
    ) -> None:
        """Move every ``old -> new`` slot of an untouched stage item at once,
        renaming the encounters and resetting their pick-ban.

        A seat changes hands the only way it can: the occupant is retired
        and the replacement is seated in the same slot. The item is untouched --
        nothing was played in it -- so the retired rows carry no result with them;
        :meth:`_reseat_stage` holds the encounter rows locked since it checked that.
        """
        from src.services.encounter.pick_ban_session import pick_ban_session_service

        seat = aliased(models.EncounterTeam)
        result = await session.execute(
            self.encounter_repo.select()
            .join(models.BracketEncounter, models.BracketEncounter.encounter_id == models.Encounter.id)
            .where(
                models.BracketEncounter.stage_item_id == stage_item_id,
                sa.exists()
                .where(seat.encounter_id == models.Encounter.id)
                .where(seat.active.is_(True))
                .where(seat.team_id.in_(mapping)),
            )
        )
        encounters = list(result.scalars())
        if not encounters:
            return
        seats_by_encounter: dict[int, list[models.EncounterTeam]] = defaultdict(list)
        for row in (
            await session.execute(
                select(models.EncounterTeam)
                .where(
                    models.EncounterTeam.encounter_id.in_([encounter.id for encounter in encounters]),
                    models.EncounterTeam.active.is_(True),
                )
                .order_by(models.EncounterTeam.slot)
            )
        ).scalars():
            seats_by_encounter[row.encounter_id].append(row)

        team_ids = set(mapping.values())
        for seats in seats_by_encounter.values():
            team_ids.update(row.team_id for row in seats if row.team_id is not None)
        names = await self._load_team_names(session, sorted(team_ids))
        lineups = await self._team_lineups(session, sorted(set(mapping.values())))
        for encounter in encounters:
            seats = seats_by_encounter[encounter.id]
            moves = [(row, mapping[row.team_id]) for row in seats if row.team_id is not None and row.team_id in mapping]
            # Every old seat is vacated before any new one is placed: two teams of one encounter may trade seats.
            for row, _ in moves:
                await vacate_slot(session, encounter, slot=row.slot)
            for row, replacement in moves:
                await place_team(
                    session,
                    encounter,
                    slot=row.slot,
                    team_id=replacement,
                    name=names.get(replacement, "TBD"),
                    seed=row.seed,
                    members=lineups.get(replacement, ()),
                )
            live = await active_teams(session, encounter.id)
            by_slot = {row.slot: row.team_id for row in live}
            encounter.name = build_encounter_name_from_ids(
                [by_slot.get(slot) for slot in range(1, encounter.slot_count + 1)],
                names,
            )
            # The pick-ban rooms follow the new pairing.
            await pick_ban_session_service.sync_all_pick_ban_sessions_after_team_change(session, encounter)
        # No channel post: requalification rewrites a whole stage item.
        await lifecycle_notifier.on_encounters_changed(session, encounters, channel=False)
