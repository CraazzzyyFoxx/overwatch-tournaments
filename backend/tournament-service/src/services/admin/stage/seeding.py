"""Filling a stage with teams: seeding them in directly, or wiring them from group standings."""

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src.domain.stage.seeds import (
    GroupSlice,
    group_advance_counts,
    group_for_index,
    parse_seed_mode,
    rank_team_ids,
)
from src.domain.stage.seeds import build_seeding as _build_seeding
from src.domain.stage.seeds import separate_groups as _separate_groups
from src.services.admin.stage.base import StageServiceBase
from src.services.admin.stage_common import (
    BRACKET_STAGE_TYPES,
    QUALIFYING_SOURCE_STAGE_TYPES,
    _apply_seeding,
)
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

        Idempotent: any existing FINAL inputs in target stage_items are REMOVED
        before seeding — this is a "reset and reseed" operation. TENTATIVE inputs
        are preserved (they point to upstream stage outputs, not team assignments).

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
        ordered_ids = rank_team_ids(teams, ranking, rng_seed=stage.id)
        by_id = {team.id: team for team in teams}
        teams_sorted = [by_id[team_id] for team_id in ordered_ids]

        stage_items = sorted(stage.items, key=lambda item: (item.order, item.id))
        num_groups = len(stage_items)

        # Wipe existing FINAL inputs. We keep TENTATIVE (advance-from-stage) and
        # EMPTY inputs — only manually-assigned team slots are reset.
        for item in stage_items:
            for inp in list(item.inputs):
                if inp.input_type == enums.StageItemInputType.FINAL:
                    await session.delete(inp)
        # Flushed before the new rows go in: the reseed hands out the same slot
        # numbers the wiped inputs held, and the unit of work emits inserts
        # before deletes -- which uq_stage_item_input_item_slot would refuse.
        await session.flush()

        # The occupied slots of each stage_item, which the preserved TENTATIVE
        # inputs already hold. Re-scanned per assignment rather than counted up
        # from the first gap: a preserved TENTATIVE at slot 2 makes the free
        # slots 1 and 3, and a running counter would hand out 1 and 2 -- two
        # inputs on one slot.
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

    async def wire_from_groups(
        self,
        session: AsyncSession,
        target_stage_id: int,
        source_stage_id: int,
        top: int,
        *,
        top_lb: int = 0,
        upper_per_group: int | None = None,
        mode: str = "cross",
        notify: bool = True,
        commit: bool = True,
    ) -> models.Stage:
        """Wire TENTATIVE inputs in ``target_stage`` pointing to top-N of each group in
        ``source_stage``.

        Two column orders, ``cross`` (default: every odd column of places
        flipped, A1, B1, B2, A2) and ``snake`` (all 1st places, then all 2nd
        places, ...). A generated bracket then has the order rearranged
        (``separate_groups``) so no first-round match of its 1-vs-N layout seats
        two teams of one group; a custom bracket template pairs its seeds as
        drawn and keeps the column order.

        Each group sends its own ``StageItem.advance_count`` when that is set,
        else ``top + top_lb``; of those, ``upper_per_group`` (defaulting to
        ``top`` once ``top_lb > 0``, otherwise "all of them") start in the upper
        bracket and the rest in the lower one, with a group's own
        ``advance_upper_count`` overriding that. A group's lower-bracket band
        starts right after its own upper band, so uneven groups do not share one
        offset. Lower-bracket starters require a DOUBLE_ELIMINATION target; its
        BRACKET_LOWER stage item is created here when it has none.

        Idempotent: existing FINAL inputs are preserved; existing TENTATIVE inputs
        with the same slot are overwritten.
        """
        target_stage = await self.get_stage(session, target_stage_id)
        source_stage = await self.get_stage(session, source_stage_id)

        if target_stage.tournament_id != source_stage.tournament_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source and target stages must belong to the same tournament",
            )
        if source_stage.stage_type not in QUALIFYING_SOURCE_STAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source stage must be a group stage (round robin, swiss or ffa league)",
            )
        if target_stage.stage_type not in BRACKET_STAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target stage must be a bracket (single_elimination or double_elimination)",
            )
        if top < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="`top` must be non-negative")
        if top_lb < 0:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="`top_lb` must be non-negative")
        if not target_stage.items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target stage has no stage items; create one before wiring",
            )

        lb_item = next(
            (i for i in target_stage.items if i.type == enums.StageItemType.BRACKET_LOWER),
            None,
        )
        if top_lb > 0 and target_stage.stage_type != enums.StageType.DOUBLE_ELIMINATION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="`top_lb` requires a double_elimination target stage",
            )

        source_items = sorted(source_stage.items, key=lambda item: (item.order, item.id))
        if not source_items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source stage has no stage items",
            )

        num_groups = len(source_items)

        # Per group: its own ``advance_count`` if set, else ``top + top_lb``, split
        # by its own ``advance_upper_count`` if set, else ``upper_per_group``.
        counts = group_advance_counts(
            source_items,
            default_advance=top + top_lb,
            default_upper=upper_per_group if upper_per_group is not None else (top if top_lb > 0 else None),
        )
        if target_stage.stage_type != enums.StageType.DOUBLE_ELIMINATION:
            # No lower bracket to send anyone to: a group's own ``advance_upper_count``
            # is a leftover from a DE plan, not a reason to refuse. Everyone it
            # advances enters the one bracket (``_projected_bracket_seed_counts``
            # projects the same). The explicit ``top_lb > 0`` refusal above still stands.
            counts = [(item_id, upper + lower, 0) for item_id, upper, lower in counts]
        if not any(upper or lower for _, upper, lower in counts):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nothing advances: set `top`, or an advance count on the source stage or its groups",
            )
        if sum(lower for _, _, lower in counts) > 0:
            # Only a DE target can get here: the collapse above zeroes the rest.
            if lb_item is None:
                # A DE stage that sends teams lower gets its Lower bracket item here.
                lb_item = models.StageItem(
                    stage_id=target_stage.id,
                    name="Lower bracket",
                    type=enums.StageItemType.BRACKET_LOWER,
                    order=max(item.order for item in target_stage.items) + 1,
                    # Explicitly empty: once flushed, an untouched collection would
                    # lazy-load, and a lazy load on an async session raises.
                    inputs=[],
                )
                session.add(lb_item)
                target_stage.items.append(lb_item)
                await session.flush()
        if sum(upper for _, upper, _ in counts) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Fewer than 2 teams reach the upper bracket",
            )

        # UB: first non-lower stage_item by order. A group's lower-bracket band
        # starts right after its own upper one, which for uneven groups is not a
        # shared offset.
        ub_items = [item for item in target_stage.items if item.type != enums.StageItemType.BRACKET_LOWER]
        if not ub_items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target stage has only a lower bracket item; create an upper bracket item before wiring",
            )
        ub_item = sorted(ub_items, key=lambda item: (item.order, item.id))[0]
        # A generated bracket opens 1-vs-N, so its seeds are arranged to keep a
        # group's teams apart there; a custom template pairs them as drawn.
        arrange = _separate_groups if target_stage.bracket_template is None else list
        _apply_seeding(session, arrange(_build_seeding([GroupSlice(i, 1, ub) for i, ub, _ in counts], mode)), ub_item)

        lb_slices = [GroupSlice(i, ub + 1, lb) for i, ub, lb in counts if lb > 0]
        # Unconditional on purpose: a re-wire that now sends nobody lower has to
        # clear the TENTATIVE rows the previous one left on the lower item.
        if lb_item is not None:
            _apply_seeding(session, arrange(_build_seeding(lb_slices, mode)), lb_item)

        if notify:
            await self._publish_structure_changed(session, target_stage.tournament_id)
        if commit:
            await session.commit()
        else:
            await session.flush()

        logger.info(
            "Wired TENTATIVE inputs from stage {} ({} groups × top {}, top_lb {}) into stage {} ({})",
            source_stage.id,
            num_groups,
            top,
            top_lb,
            target_stage.id,
            mode,
        )
        return target_stage if not commit else await self.get_stage(session, target_stage_id)

    async def _preceding_phase_group_stages(self, session: AsyncSession, stage: models.Stage) -> list[models.Stage]:
        result = await session.execute(
            self.stage_repo.select()
            .where(
                models.Stage.tournament_id == stage.tournament_id,
                models.Stage.stage_type.in_(QUALIFYING_SOURCE_STAGE_TYPES),
                models.Stage.order < stage.order,
            )
            .options(selectinload(models.Stage.items))
            .order_by(models.Stage.order.desc(), models.Stage.id.desc())
        )
        groups = list(result.scalars().all())
        if not groups:
            return []
        phase = groups[0].order
        return [group for group in groups if group.order == phase]

    async def _preceding_group_stage(self, session: AsyncSession, stage: models.Stage) -> models.Stage | None:
        """The unique group stage in the latest earlier phase.

        Same ``order`` is parallel, not earlier. Several group stages in that
        earlier phase is ambiguous — returns None so nothing guesses which
        division feeds this bracket.
        """
        tied = await self._preceding_phase_group_stages(session, stage)
        return tied[0] if len(tied) == 1 else None

    async def _auto_wire_from_groups(
        self,
        session: AsyncSession,
        stage: models.Stage,
        *,
        strict: bool = False,
        source_stage_id: int | None = None,
    ) -> bool:
        """Derive playoff seeding from a group stage's ``advance_count`` and
        ``advance_upper_count``, then wire TENTATIVE inputs (snake seeding).

        ``source_stage_id`` names the feeding group stage explicitly — required
        when several divisions share the earlier phase, since none of them is
        "the" preceding stage. Without it the source is the one group stage of
        the latest earlier phase.

        No-op when the stage is not a bracket, has no preceding group stage, or
        nothing there is configured to advance — neither the source stage's
        ``advance_count`` nor any of its groups' own — keeping manually wired
        playoffs working unchanged. Set ``strict=True`` (the standalone
        "Auto-wire" action) to raise a descriptive 400 for those cases instead of
        silently skipping, so an admin can see WHY nothing got wired.

        Returns whether wiring happened.
        """
        if stage.stage_type not in BRACKET_STAGE_TYPES:
            if strict:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Only single/double elimination stages can be auto-wired from groups",
                )
            return False

        if source_stage_id is not None:
            # ``wire_from_groups`` re-validates tournament and stage type below.
            source: models.Stage | None = await self.get_stage(session, source_stage_id)
        else:
            candidates = await self._preceding_phase_group_stages(session, stage)
            if len(candidates) > 1:
                if strict:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=(
                            f"Phase {candidates[0].order} runs {len(candidates)} group stages "
                            f"({', '.join(candidate.name for candidate in candidates)}) — "
                            "pick which one feeds this bracket"
                        ),
                    )
                return False
            source = candidates[0] if candidates else None

        stage_advance = (source.advance_count or 0) if source is not None else 0
        group_advance = any(getattr(item, "advance_count", None) for item in source.items) if source else False
        if source is None or (stage_advance <= 0 and not group_advance):
            if strict:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        'No earlier round-robin/Swiss stage with "Teams advancing to '
                        'playoff" configured — on the stage or on one of its groups'
                    ),
                )
            return False

        # ``default_advance = source.advance_count``, ``default_upper =
        # source.advance_upper_count`` (NULL → everyone starts upper).
        # A single elimination playoff has no lower bracket, so the source's split
        # is ignored there and every advancing team starts in the bracket.
        #
        # The plain group-major order ("snake": A1, B1, …, A2, B2, …) puts the
        # group winners on the top seeds the engine's 1-vs-N layout spreads
        # apart; ``wire_from_groups`` then swaps runners-up so none opens against
        # its own group (three groups sending two would otherwise pair C1-C2).
        await self.wire_from_groups(
            session,
            stage.id,
            source.id,
            stage_advance,
            top_lb=0,
            upper_per_group=(
                source.advance_upper_count if stage.stage_type == enums.StageType.DOUBLE_ELIMINATION else None
            ),
            mode="snake",
            notify=False,
            commit=False,
        )
        return True

    async def auto_wire_stage(
        self,
        session: AsyncSession,
        stage_id: int,
        *,
        source_stage_id: int | None = None,
        notify: bool = True,
        commit: bool = True,
    ) -> models.Stage:
        """Standalone trigger for the same group->bracket auto-wiring that
        "Activate & generate" runs automatically. Lets an admin preview/debug the
        wiring, or refresh it after changing the source stage's "Teams advancing
        to playoff" count, without activating or generating anything.

        ``source_stage_id`` names the feeding group stage — the only way to wire
        a playoff when several divisions share the earlier phase.
        """
        stage = await self.get_stage(session, stage_id)
        await self._auto_wire_from_groups(session, stage, strict=True, source_stage_id=source_stage_id)
        if notify:
            await self._publish_structure_changed(session, stage.tournament_id)
        if commit:
            await session.commit()
        else:
            await session.flush()
        return await self.get_stage(session, stage_id)
