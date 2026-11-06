"""Filling a stage with teams by seeding them in directly."""

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src.domain.stage.seeds import (
    SeedRanking,
    group_for_index,
    parse_seed_mode,
    rank_team_ids,
)
from src.services.admin.stage.base import StageServiceBase
from src.services.tournament.events import enqueue_tournament_recalculation


class StageSeedingMixin(StageServiceBase):
    async def seed_teams(
        self,
        session: AsyncSession,
        stage_id: int,
        team_ids: list[int],
        *,
        mode: str = "snake_sr",
        notify: bool = True,
    ) -> models.Stage:
        """Auto-distribute teams into the stage's stage_items (groups/brackets).

        Modes:

        - ``snake_sr`` (default): rank by ``Team.avg_sr`` descending, then
          deal them out in a snake pattern across stage_items. For 4 groups the
          order becomes A, B, C, D, D, C, B, A, A, B, C, D, ... — this balances
          each group's strength regardless of team count per group.
        - ``random``: ``random.Random(stage.id)`` shuffle, then round-robin
          across stage_items. Stable across processes.
        - ``by_total_sr``: same as ``snake_sr`` but ranks by ``total_sr`` (useful
          when ``avg_sr`` can be skewed by player count differences).
        - ``captain_rank``: rank by the captain's own roster rank descending (the draft playoff: the strongest
          captain is seed 1); teams without a ranked captain sort last.

        Idempotent: any existing FINAL inputs in target stage_items are REMOVED
        before seeding — this is a "reset and reseed" operation. EMPTY inputs are
        preserved.

        Raises HTTPException if:
        - the stage already has generated encounters (409, like the bracket template writers)
        - stage has no stage_items
        - team count is zero
        - teams don't all belong to the same tournament as the stage
        """
        # Under the stage lock every other input writer and the bracket job take: a generation must not build on
        # seeds this is rewriting. Loaded after the lock so the inputs wiped below are the current ones.
        await self._lock_stage(session, stage_id)
        await self._assert_no_encounters(session, stage_id)
        stage = await self.get_stage(session, stage_id, populate_existing=True)
        if not stage.items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Stage has no stage_items to seed into",
            )
        if not team_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="team_ids must be non-empty")
        if len(set(team_ids)) != len(team_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="team_ids contain duplicates")

        teams = list(await self.team_repo.bulk_get(session, team_ids))
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

        ranking = parse_seed_mode(mode)
        if ranking is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unknown seeding mode: {mode!r}",
            )
        captain_ranks = await self._captain_ranks(session, team_ids) if ranking is SeedRanking.CAPTAIN_RANK else None
        ordered_ids = rank_team_ids(teams, ranking, rng_seed=stage.id, captain_ranks=captain_ranks)
        by_id = {team.id: team for team in teams}
        teams_sorted = [by_id[team_id] for team_id in ordered_ids]

        stage_items = sorted(stage.items, key=lambda item: (item.order, item.id))
        num_groups = len(stage_items)

        # Wipe existing FINAL inputs. We keep EMPTY inputs — only manually-assigned
        # team slots are reset.
        for item in stage_items:
            for inp in list(item.inputs):
                if inp.input_type == enums.StageItemInputType.FINAL:
                    await session.delete(inp)
        # Flushed before the new rows go in: the reseed hands out the same slot
        # numbers the wiped inputs held, and the unit of work emits inserts
        # before deletes -- which uq_stage_item_input_item_slot would refuse.
        await session.flush()

        # The occupied slots of each stage_item, which the preserved EMPTY inputs
        # still hold. Re-scanned per assignment rather than counted up from the
        # first gap: an EMPTY at slot 2 makes the free slots 1 and 3, and a
        # running counter would hand out 1 and 2 -- two inputs on one slot.
        used_slots: dict[int, set[int]] = {
            item.id: {inp.slot for inp in item.inputs if inp.input_type != enums.StageItemInputType.FINAL}
            for item in stage_items
        }

        snake = mode != "random"

        for team_idx, team in enumerate(teams_sorted):
            group_idx = group_for_index(team_idx, num_groups, snake=snake)
            target_item = stage_items[group_idx]
            taken = used_slots[target_item.id]
            slot = 1
            while slot in taken:
                slot += 1
            taken.add(slot)

            session.add(
                models.StageItemInput(
                    stage_item_id=target_item.id,
                    slot=slot,
                    input_type=enums.StageItemInputType.FINAL,
                    team_id=team.id,
                    seat_source="manual",
                )
            )

        await enqueue_tournament_recalculation(session, stage.tournament_id)
        if notify:
            await self._publish_structure_changed(session, stage.tournament_id)
        await session.commit()

        logger.info(
            "Seeded {} teams into stage {} across {} groups (mode={})",
            len(teams_sorted),
            stage.id,
            num_groups,
            mode,
        )
        # Reloaded: the inputs were deleted and added through the session, not
        # through the ``items[].inputs`` collections of the stage loaded above.
        return await self.get_stage(session, stage_id, populate_existing=True)

    async def _captain_ranks(self, session: AsyncSession, team_ids: list[int]) -> dict[int, int | None]:
        """Team id -> rank of the captain's own roster row (``Team.captain_id`` is a ``players.user`` id)."""
        rows = await session.execute(
            sa.select(models.Player.team_id, models.Player.rank)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.Team, models.Team.id == models.Player.team_id)
            .where(
                models.Player.team_id.in_(team_ids),
                models.Player.is_substitution.is_(False),
                models.WorkspaceMember.player_id == models.Team.captain_id,
            )
        )
        return dict(rows.all())
