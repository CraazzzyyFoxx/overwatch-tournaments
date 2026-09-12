"""Admin service layer for stage CRUD and bracket generation."""

from collections.abc import Sequence

from loguru import logger
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.tournament.pick_ban import PickBanConfig, PickBanConfigSlot
from shared.repository import (
    EncounterRepository,
    PickBanConfigRepository,
    StageItemInputRepository,
    StageItemRepository,
    StageRepository,
    StandingRepository,
    TeamRepository,
    TournamentRepository,
)
from shared.services.bracket import round_robin
from shared.services.bracket.engine import generate_bracket, placeholder_bracket, placeholder_seeds
from shared.services.bracket.persist import persist_skeleton
from shared.services.bracket.swiss import SwissPairingImpossibleError, SwissStanding
from shared.services.bracket.swiss_settings import (
    clear_swiss_byes,
    clear_swiss_scope_stopped,
    mark_swiss_scope_stopped,
    record_swiss_bye,
    swiss_bye_team_ids,
)
from shared.services.bracket.types import BracketSkeleton, Pairing
from shared.services.encounter_naming import build_encounter_name_from_ids
from src import models, schemas
from src.domain.admin.best_of import parse_best_of_config, resolve_best_of
from src.domain.stage.lifecycle import stage_lifecycle
from src.domain.stage.seeds import (
    GroupSlice,
    SeedRanking,
    apply_seed_ranking,
    group_advance_counts,
    group_for_index,
    parse_seed_mode,
    parse_seed_ranking,
    rank_team_ids,
)
from src.domain.stage.seeds import (
    advance_split as _advance_split,
)
from src.domain.stage.seeds import (
    build_seeding as _build_seeding,
)
from src.domain.stage.seeds import (
    collect_item_team_ids as _collect_item_team_ids,
)
from src.domain.stage.seeds import (
    lower_bracket_item as _lower_bracket_item,
)
from src.domain.stage.seeds import (
    resolve_seeds as _resolve_seeds,
)
from src.services.admin.stage_common import (
    BRACKET_STAGE_TYPES,
    GROUPED_GENERATION_STAGE_TYPES,
    _apply_seeding,
    _bracket_seeds,
    _pick_ban_config_signature,
)
from src.services.tournament.events import (
    STRUCTURE_RESOURCES,
    enqueue_tournament_recalculation,
    publish_tournament_invalidation,
)


class AdminStageService:
    def __init__(
        self,
        *,
        stage_repo: StageRepository = StageRepository(),
        stage_item_repo: StageItemRepository = StageItemRepository(),
        stage_item_input_repo: StageItemInputRepository = StageItemInputRepository(),
        encounter_repo: EncounterRepository = EncounterRepository(),
        standing_repo: StandingRepository = StandingRepository(),
        team_repo: TeamRepository = TeamRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        pick_ban_config_repo: PickBanConfigRepository = PickBanConfigRepository(),
    ) -> None:
        self.stage_repo = stage_repo
        self.stage_item_repo = stage_item_repo
        self.stage_item_input_repo = stage_item_input_repo
        self.encounter_repo = encounter_repo
        self.standing_repo = standing_repo
        self.team_repo = team_repo
        self.tournament_repo = tournament_repo
        self.pick_ban_config_repo = pick_ban_config_repo

    async def _publish_structure_changed(self, session: AsyncSession, tournament_id: int) -> None:
        """Announce that this tournament's set of page sections moved.

        Every stage write reaches here, and every one of them creates, removes or
        re-shapes a stage — which is exactly ``tournament.structure``, the one
        resource a client cannot repair by refetching a query (it has to re-run
        the route).
        """
        await publish_tournament_invalidation(session, tournament_id, STRUCTURE_RESOURCES)

    async def get_stage(self, session: AsyncSession, stage_id: int) -> models.Stage:
        stage = await self.stage_repo.get(
            session,
            stage_id,
            options=[selectinload(models.Stage.items).selectinload(models.StageItem.inputs)],
        )
        if not stage:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
        return stage

    async def get_tournament_id(self, session: AsyncSession, stage_id: int) -> int:
        tournament_id = await self.stage_repo.get_tournament_id(session, stage_id)
        if tournament_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stage not found")
        return tournament_id

    async def get_planned_rounds(self, session: AsyncSession, stage_id: int) -> list[int]:
        """The round numbers this stage's bracket has, or will have.

        Elimination round numbering is not the plain ``1..max_rounds`` sequence
        ``max_rounds`` (an independently admin-set planning field) would suggest:
        double elimination's lower bracket uses negative numbers, and even single
        elimination's actual round count depends on team count, which may not
        match ``max_rounds`` at all. This lets a caller scope a cascade config
        (e.g. a pick-ban rule) to a round correctly before the bracket exists,
        rather than guessing and silently missing every lower-bracket round or
        landing a rule on a round number the eventual bracket will never have.

        Once encounters exist they are the ground truth. Before that, this
        predicts the same numbers the real generator will produce off the stage's
        seed counts (``_bracket_seed_counts``) -- empty when the stage type isn't a
        bracket, or no seeds are known or projected yet, in which case only the
        tournament-/stage-wide scopes are meaningful.
        """
        stage = await self.get_stage(session, stage_id)

        # DISTINCT projection of a single column: the round numbers only, never
        # the encounters themselves.
        generated = await session.execute(
            select(models.Encounter.round).where(models.Encounter.stage_id == stage_id).distinct()
        )
        existing_rounds = sorted({row[0] for row in generated.all()})
        if existing_rounds:
            return existing_rounds

        if stage.stage_type not in BRACKET_STAGE_TYPES:
            return []

        upper_count, lower_count = await self._bracket_seed_counts(session, stage)
        skeleton = placeholder_bracket(stage.stage_type, upper_count, lower_count=lower_count)
        return sorted({pairing.round_number for pairing in skeleton.pairings})

    async def get_bracket_preview(self, session: AsyncSession, stage_id: int) -> dict:
        """The bracket this stage would generate, as a read-only skeleton.

        Same generator, same seed order and same best-of resolution as
        ``_generate_bracket_encounters`` -> ``persist_skeleton``; nothing is
        written. That is the point: a preview drawn from a re-derived shape
        drifts from the real thing on exactly the cases that matter (byes in a
        non-power-of-two bracket, the lower bracket's cross-drops), so it is
        drawn from the generator instead.

        Wired teams come back under their real ids and names; an unseeded playoff
        falls back to the projected seed counts the way generation does, and every
        slot comes back TBD.

        ``local_id`` is 1-based and skeleton-local: ``sources`` reference it and
        not encounter ids, because these matches do not exist yet.
        """
        stage = await self.get_stage(session, stage_id)
        if stage.stage_type not in BRACKET_STAGE_TYPES:
            return {"matches": []}

        sorted_items = sorted(stage.items, key=lambda item: (item.order, item.id))
        upper_ids, lower_ids = _bracket_seeds(stage, sorted_items, _lower_bracket_item(stage, sorted_items))
        upper_ids = await self._rank_seed_ids(session, stage, upper_ids)
        lower_ids = await self._rank_seed_ids(session, stage, lower_ids)
        de_include_reset = (
            stage.stage_type == enums.StageType.DOUBLE_ELIMINATION
            and (stage.settings_json or {}).get("de_grand_final_type") == "with_reset"
        )

        if len(upper_ids) + len(lower_ids) < 2:
            upper_count, lower_count = await self._projected_bracket_seed_counts(session, stage)
            if upper_count < 2:
                return {"matches": []}
            upper_ids = placeholder_seeds(upper_count)
            lower_ids = placeholder_seeds(lower_count, offset=upper_count)

        skeleton = _resolve_seeds(
            generate_bracket(
                stage.stage_type,
                upper_ids,
                de_include_reset=de_include_reset,
                lower_bracket_team_ids=lower_ids,
            ),
            {},
        )

        team_names_by_id = await self._load_team_names(session, upper_ids + lower_ids)
        best_of_cfg = parse_best_of_config(stage.settings_json)
        max_round = max((pairing.round_number for pairing in skeleton.pairings), default=0)
        sources: dict[int, list[dict]] = {}
        for edge in skeleton.advancement_edges:
            sources.setdefault(edge.target_local_id, []).append(
                {"local_id": edge.source_local_id + 1, "role": edge.role, "slot": edge.target_slot}
            )

        return {
            "matches": [
                {
                    "local_id": pairing.local_id + 1,
                    "round": pairing.round_number,
                    "name": build_encounter_name_from_ids(
                        pairing.home_team_id,
                        pairing.away_team_id,
                        team_names_by_id,
                    ),
                    "best_of": resolve_best_of(
                        best_of_cfg,
                        pairing.round_number,
                        is_final=pairing.round_number == max_round,
                    ),
                    "home_team_id": pairing.home_team_id,
                    "away_team_id": pairing.away_team_id,
                    "sources": sources.get(pairing.local_id, []),
                }
                for pairing in skeleton.pairings
            ]
        }

    async def _bracket_seed_counts(self, session: AsyncSession, stage: models.Stage) -> tuple[int, int]:
        """How many teams start in ``stage``'s upper and lower bracket.

        Wired inputs (including still-TENTATIVE ones once activation resolves them)
        are ground truth. Before any exist — the common case for a playoff seeded
        only after its groups finish — the counts are projected from the preceding
        group stage instead, so the bracket can be planned, and generated, off the
        ``advance_count`` alone.
        """
        sorted_items = sorted(stage.items, key=lambda item: (item.order, item.id))
        upper, lower = _bracket_seeds(stage, sorted_items, _lower_bracket_item(stage, sorted_items))
        if len(upper) + len(lower) >= 2:
            return len(upper), len(lower)
        return await self._projected_bracket_seed_counts(session, stage)

    async def _projected_bracket_seed_counts(self, session: AsyncSession, stage: models.Stage) -> tuple[int, int]:
        """The upper/lower seed counts the preceding group stage will feed into
        ``stage``, mirroring ``_auto_wire_from_groups``: each group of the nearest
        earlier Swiss/round-robin stage sends its own ``advance_count`` (falling
        back to the stage's), split the way that wiring will split it. ``(0, 0)``
        when there is no such source, or nothing is configured to advance."""
        source = await self._preceding_group_stage(session, stage)
        if source is None:
            return 0, 0

        top, top_lb = _advance_split(stage, source.advance_count or 0)
        items = sorted(source.items, key=lambda item: (item.order, item.id))
        # ``or`` covers a source stage with no groups at all: one implicit group.
        counts = group_advance_counts(stage, items, default_upper=top, default_lower=top_lb) or [(0, top, top_lb)]
        upper = sum(item_upper for _, item_upper, _ in counts)
        lower = sum(item_lower for _, _, item_lower in counts)
        if upper + lower == 0:
            return 0, 0
        if lower:
            return upper, lower

        if stage.stage_type == enums.StageType.DOUBLE_ELIMINATION and getattr(stage, "split_lower_bracket", False):
            # One bracket item holds both halves — ``_bracket_seeds`` splits the
            # seed list down the middle instead of wiring a separate item.
            return upper // 2, upper - upper // 2
        return upper, 0

    async def get_stage_item(self, session: AsyncSession, stage_item_id: int) -> models.StageItem:
        item = await self.stage_item_repo.get(session, stage_item_id, options=[selectinload(models.StageItem.inputs)])
        if not item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Stage item not found",
            )
        return item

    async def get_stages_by_tournament(self, session: AsyncSession, tournament_id: int) -> list[models.Stage]:
        return list(
            await self.stage_repo.list_by_tournament(
                session,
                tournament_id,
                options=[selectinload(models.Stage.items).selectinload(models.StageItem.inputs)],
            )
        )

    async def get_stage_progress(self, session: AsyncSession, tournament_id: int) -> list[dict]:
        """Return per-stage and per-stage_item progress (completed / total
        encounters). Used by admin UI to render the "Group A — 8/10 done" badge
        and to warn before activating a playoff with pending group matches.
        """
        stages_list = list(
            await self.stage_repo.list_by_tournament(session, tournament_id, options=[selectinload(models.Stage.items)])
        )
        if not stages_list:
            return []

        stage_ids = [s.id for s in stages_list]
        # GROUP BY in SQL: totals and completed counts, never encounter rows.
        counts = await session.execute(
            select(
                models.Encounter.stage_id,
                models.Encounter.stage_item_id,
                func.count().label("total"),
                func.coalesce(
                    func.sum(case((models.Encounter.status == enums.EncounterStatus.COMPLETED, 1), else_=0)),
                    0,
                ).label("completed"),
            )
            .where(models.Encounter.stage_id.in_(stage_ids))
            .group_by(models.Encounter.stage_id, models.Encounter.stage_item_id)
        )
        agg = {(row.stage_id, row.stage_item_id): (int(row.total), int(row.completed)) for row in counts}
        output: list[dict] = []
        for stage in stages_list:
            stage_total = 0
            stage_completed = 0
            item_progress: list[dict] = []
            for item in sorted(stage.items, key=lambda it: it.order):
                total, completed = agg.get((stage.id, item.id), [0, 0])
                stage_total += total
                stage_completed += completed
                item_progress.append(
                    {
                        "stage_item_id": item.id,
                        "name": item.name,
                        "total": total,
                        "completed": completed,
                        "is_completed": total > 0 and completed == total,
                    }
                )
            # Also include encounters with NULL stage_item_id (shouldn't happen
            # after Phase A backfill, but safe).
            total, completed = agg.get((stage.id, None), [0, 0])
            stage_total += total
            stage_completed += completed

            output.append(
                {
                    "stage_id": stage.id,
                    "name": stage.name,
                    "stage_type": stage.stage_type.value,
                    "lifecycle": stage_lifecycle(stage, has_encounters=stage_total > 0).value,
                    "is_active": stage.is_active,
                    "is_completed": stage.is_completed,
                    "total": stage_total,
                    "completed": stage_completed,
                    "items": item_progress,
                }
            )
        return output

    async def create_stage(self, session: AsyncSession, tournament_id: int, data: schemas.StageCreate) -> models.Stage:
        tournament = await self.tournament_repo.get(session, tournament_id)
        if not tournament:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tournament not found")

        # The deprecated stage.challonge_id/slug columns are no longer written: a
        # supplied Challonge link becomes a normalized challonge_source row scoped to
        # the new stage instead.
        payload = data.model_dump()
        challonge_id = payload.pop("challonge_id", None)
        challonge_slug = payload.pop("challonge_slug", None)
        stage = models.Stage(tournament_id=tournament_id, **payload)
        await self.stage_repo.create(session, stage)
        if challonge_id is not None:
            session.add(
                models.ChallongeSource(
                    tournament_id=tournament_id,
                    stage_id=stage.id,
                    challonge_tournament_id=challonge_id,
                    slug=challonge_slug,
                    source_type="stage",
                )
            )
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()
        return await self.get_stage(session, stage.id)

    async def update_stage(self, session: AsyncSession, stage_id: int, data: schemas.StageUpdate) -> models.Stage:
        stage = await self.get_stage(session, stage_id)
        tournament_id = stage.tournament_id
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(stage, field, value)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()
        return await self.get_stage(session, stage.id)

    async def delete_stage(self, session: AsyncSession, stage_id: int) -> None:
        stage = await self.get_stage(session, stage_id)
        tournament_id = stage.tournament_id
        # Encounter.stage_id and Standing.stage_id reference Stage with ON DELETE
        # SET NULL, so deleting the stage alone would orphan its matches and
        # standings rather than remove them. Delete that derived data explicitly
        # first; the encounter's dependents (maps, match rows, links, mappings)
        # cascade from the encounter delete.
        await self.encounter_repo.delete_for_stage(session, stage_id)
        await self.standing_repo.delete_for_stage(session, stage_id)
        await self.stage_repo.delete(session, stage)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()

    async def delete_stage_item(self, session: AsyncSession, stage_item_id: int) -> None:
        """Delete one stage item (group/bracket lane) without deleting its stage.

        Same reasoning as ``delete_stage``: Encounter.stage_item_id and
        Standing.stage_item_id are ON DELETE SET NULL, so deleting the item alone
        would orphan its matches and standings rather than remove them. The item's
        own inputs cascade (StageItemInput.stage_item_id is ON DELETE CASCADE).
        """
        item = await self.get_stage_item(session, stage_item_id)
        tournament_id = await self.stage_repo.get_tournament_id(session, item.stage_id)
        await self.encounter_repo.delete_for_stage_item(session, stage_item_id)
        await self.standing_repo.delete_for_stage_item(session, stage_item_id)
        await self.stage_item_repo.delete(session, item)
        await enqueue_tournament_recalculation(session, tournament_id)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()

    async def _merge_pick_ban_configs(
        self,
        session: AsyncSession,
        *,
        target_stage: models.Stage,
        source_stage_ids: list[int],
        kind: enums.PickBanKind,
    ) -> None:
        """Generalizes ``_merge_map_veto_configs`` onto ``PickBanConfig``, scoped
        by ``kind`` -- called once per kind so a tournament's map and hero configs
        are deduped independently."""
        target_configs = list(
            await self.pick_ban_config_repo.list_for_stages(
                session,
                tournament_id=target_stage.tournament_id,
                kind=kind,
                stage_ids=[target_stage.id],
            )
        )
        if len(target_configs) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Target stage has multiple {kind.value} pick-ban configs; resolve them before merging",
            )

        source_configs = list(
            await self.pick_ban_config_repo.list_for_stages(
                session,
                tournament_id=target_stage.tournament_id,
                kind=kind,
                stage_ids=source_stage_ids,
                options=[
                    selectinload(PickBanConfig.items),
                    selectinload(PickBanConfig.slots).selectinload(PickBanConfigSlot.items),
                ],
            )
        )
        if not source_configs:
            return

        if target_configs:
            for config in source_configs:
                await session.delete(config)
            return

        signatures = {_pick_ban_config_signature(config) for config in source_configs}
        if len(signatures) > 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Source stages have different {kind.value} pick-ban configs; keep one target config before merging"
                ),
            )

        keeper = source_configs[0]
        keeper.stage_id = target_stage.id
        for config in source_configs[1:]:
            await session.delete(config)

    async def _retarget_stage_rows(
        self,
        session: AsyncSession,
        model,
        *,
        source_stage_ids: list[int],
        target_stage_id: int,
    ) -> None:
        # Generic over Encounter/Standing/ChallongeSource; no single repository
        # can express it.
        result = await session.execute(select(model).where(model.stage_id.in_(source_stage_ids)))
        for row in result.scalars().all():
            row.stage_id = target_stage_id

    async def merge_group_stages(
        self,
        session: AsyncSession,
        *,
        target_stage_id: int,
        source_stage_ids: list[int],
        target_name: str | None = None,
    ) -> models.Stage:
        """Merge old one-group stages into one grouped stage.

        Old tournaments were migrated as A/B/C/D separate Stage rows. The modern
        shape is one grouped Stage with A/B/C/D as StageItem rows, so this moves
        source items and all stage-scoped references to the selected target stage.
        """
        target_stage = await self.get_stage(session, target_stage_id)
        if target_stage.stage_type not in GROUPED_GENERATION_STAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target stage must be ROUND_ROBIN or SWISS",
            )

        unique_source_stage_ids = list(dict.fromkeys(source_stage_ids))
        if len(unique_source_stage_ids) != len(source_stage_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="source_stage_ids must not contain duplicates",
            )
        if target_stage_id in unique_source_stage_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Target stage cannot be included in source_stage_ids",
            )

        source_by_id = {stage.id: stage for stage in await self.stage_repo.bulk_get(session, unique_source_stage_ids)}
        missing = [stage_id for stage_id in unique_source_stage_ids if stage_id not in source_by_id]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source stages not found: {missing}",
            )

        source_stages = [source_by_id[stage_id] for stage_id in unique_source_stage_ids]
        for source_stage in source_stages:
            if source_stage.tournament_id != target_stage.tournament_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="All source stages must belong to the target tournament",
                )
            if source_stage.stage_type != target_stage.stage_type:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="All merged group stages must have the same stage type",
                )

        # Analytical: joins Stage purely to order the items by their owning
        # stage's order, so the merged group numbering follows stage order.
        items_result = await session.execute(
            self.stage_item_repo.select()
            .join(models.Stage, models.StageItem.stage_id == models.Stage.id)
            .where(models.StageItem.stage_id.in_(unique_source_stage_ids))
            .order_by(
                models.Stage.order.asc(),
                models.Stage.id.asc(),
                models.StageItem.order.asc(),
                models.StageItem.id.asc(),
            )
        )
        source_items = list(items_result.scalars().all())
        if not source_items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source stages have no stage items to merge",
            )

        all_items = [
            *sorted(target_stage.items, key=lambda item: (item.order, item.id)),
            *source_items,
        ]
        if any(item.type != enums.StageItemType.GROUP for item in all_items):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only group stage items can be merged",
            )

        seen_names: set[str] = set()
        for item in all_items:
            normalized_name = item.name.strip().lower()
            if normalized_name in seen_names:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f'Duplicate group name "{item.name}" would be created',
                )
            seen_names.add(normalized_name)

        for kind in (enums.PickBanKind.MAP, enums.PickBanKind.HERO):
            await self._merge_pick_ban_configs(
                session,
                target_stage=target_stage,
                source_stage_ids=unique_source_stage_ids,
                kind=kind,
            )

        for model in (
            models.Encounter,
            models.Standing,
            models.ChallongeSource,
        ):
            await self._retarget_stage_rows(
                session,
                model,
                source_stage_ids=unique_source_stage_ids,
                target_stage_id=target_stage.id,
            )

        target_items = sorted(target_stage.items, key=lambda item: (item.order, item.id))
        stage_order_by_id = {
            target_stage.id: target_stage.order,
            **{stage.id: stage.order for stage in source_stages},
        }
        ordered_items = sorted(
            [*target_items, *source_items],
            key=lambda item: (stage_order_by_id.get(item.stage_id, 0), item.order, item.id),
        )
        for order, item in enumerate(ordered_items):
            item.stage_id = target_stage.id
            item.order = order

        next_target_name = target_name.strip() if target_name else ""
        if next_target_name:
            target_stage.name = next_target_name
        target_stage.is_active = target_stage.is_active or any(stage.is_active for stage in source_stages)
        # A merge retargets the source stages' encounters onto `target_stage`
        # (`_retarget_stage_rows` above); if any source was already published,
        # those encounters must stay reportable under their new stage.
        target_stage.is_published = target_stage.is_published or any(stage.is_published for stage in source_stages)
        target_stage.is_completed = target_stage.is_completed and all(stage.is_completed for stage in source_stages)

        await session.flush()
        for source_stage in source_stages:
            await self.stage_repo.delete(session, source_stage)

        await enqueue_tournament_recalculation(session, target_stage.tournament_id)
        await self._publish_structure_changed(session, target_stage.tournament_id)
        await session.commit()

        logger.info(
            "Merged %d source group stages into stage %s for tournament %s",
            len(source_stage_ids),
            target_stage.id,
            target_stage.tournament_id,
        )
        return await self.get_stage(session, target_stage.id)

    async def create_stage_item(
        self, session: AsyncSession, stage_id: int, data: schemas.StageItemCreate
    ) -> models.StageItem:
        stage = await self.get_stage(session, stage_id)
        tournament_id = stage.tournament_id
        item = models.StageItem(stage_id=stage_id, **data.model_dump())
        await self.stage_item_repo.create(session, item)
        await enqueue_tournament_recalculation(session, tournament_id)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()
        item_id = item.id
        return await self.get_stage_item(session, item_id)

    async def update_stage_item(
        self,
        session: AsyncSession,
        stage_item_id: int,
        data: schemas.StageItemUpdate,
    ) -> models.StageItem:
        item = await self.get_stage_item(session, stage_item_id)
        tournament_id = await self.stage_repo.get_tournament_id(session, item.stage_id)
        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(item, field, value)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()
        return await self.get_stage_item(session, stage_item_id)

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

        next_input_type = update_data.get("input_type", inp.input_type)
        next_team_id = update_data.get("team_id", inp.team_id)
        next_source_stage_item_id = update_data.get("source_stage_item_id", inp.source_stage_item_id)
        next_source_position = update_data.get("source_position", inp.source_position)

        if "team_id" in update_data and next_team_id is not None:
            team = await self.team_repo.get(session, next_team_id)
            if team is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Team not found",
                )
            if team.tournament_id != tournament_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Team does not belong to this tournament",
                )

            # Analytical: joins StageItem to scope the duplicate-team check to the
            # whole stage rather than the one item the input belongs to.
            existing_result = await session.execute(
                self.stage_item_input_repo.select()
                .join(models.StageItem, models.StageItemInput.stage_item_id == models.StageItem.id)
                .where(
                    models.StageItem.stage_id == stage_id,
                    models.StageItemInput.id != input_id,
                    models.StageItemInput.team_id == next_team_id,
                )
            )
            existing_input = existing_result.scalar_one_or_none()
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
        await self.stage_item_input_repo.delete(session, inp)
        await enqueue_tournament_recalculation(session, tournament_id)
        await self._publish_structure_changed(session, tournament_id)
        await session.commit()

    async def activate_stage(
        self,
        session: AsyncSession,
        stage_id: int,
        *,
        notify: bool = True,
        commit: bool = True,
        stage: models.Stage | None = None,
    ) -> models.Stage:
        """Activate a stage, resolving tentative inputs from previous stages."""
        stage = stage or await self.get_stage(session, stage_id)

        await session.execute(
            update(models.Stage)
            .where(models.Stage.tournament_id == stage.tournament_id, models.Stage.id != stage_id)
            .values(is_active=False)
        )

        stage.is_active = True
        # Sticky: unlike ``is_active`` this never gets cleared by another
        # stage's activation, so a bracket generated as a preview becomes -- and
        # stays -- reportable/veto-able from here on (see ``shared.services.
        # bracket.usability.is_encounter_live``).
        stage.is_published = True

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
                    inp.team_id = standings[inp.source_position - 1].team_id
                    inp.input_type = enums.StageItemInputType.FINAL

        await self._finish_structure_write(session, stage, notify=notify, commit=commit, schedule_standings=False)
        return stage

    async def deactivate_stage(
        self,
        session: AsyncSession,
        stage_id: int,
        *,
        notify: bool = True,
        commit: bool = True,
    ) -> models.Stage:
        """Revert an accidentally-activated stage back to Draft/preview.

        ``is_published`` is documented (and, until now, enforced) as sticky
        because it gates whether an encounter is live for reporting/pick-ban
        (``shared.services.bracket.usability.is_encounter_live``) -- once a
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
        touched = await self.encounter_repo.count(
            session,
            filters=[
                models.Encounter.stage_id == stage_id,
                models.Encounter.status != enums.EncounterStatus.OPEN,
            ],
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

    async def _finish_structure_write(
        self,
        session: AsyncSession,
        stage: models.Stage,
        *,
        notify: bool,
        commit: bool,
        schedule_standings: bool,
    ) -> None:
        if schedule_standings:
            await enqueue_tournament_recalculation(session, stage.tournament_id)
        if notify:
            await self._publish_structure_changed(session, stage.tournament_id)
        if commit:
            await session.commit()
        else:
            await session.flush()

    async def _load_team_names(
        self,
        session: AsyncSession,
        team_ids: Sequence[int],
    ) -> dict[int, str]:
        # ``> 0`` skips the negative placeholder seeds a bracket generated before
        # its teams are known is built from (``placeholder_seeds``).
        unique_team_ids = sorted({team_id for team_id in team_ids if team_id is not None and team_id > 0})
        if not unique_team_ids:
            return {}

        # Two-column projection: names only, never whole Team rows.
        result = await session.execute(
            select(models.Team.id, models.Team.name).where(models.Team.id.in_(unique_team_ids))
        )
        return dict(result.all())

    async def _load_rankable_teams(
        self,
        session: AsyncSession,
        team_ids: Sequence[int],
    ) -> dict[int, models.Team]:
        unique_team_ids = sorted({team_id for team_id in team_ids if team_id is not None and team_id > 0})
        if not unique_team_ids:
            return {}
        teams = await self.team_repo.bulk_get(session, unique_team_ids)
        return {team.id: team for team in teams}

    async def _rank_seed_ids(
        self,
        session: AsyncSession,
        stage: models.Stage,
        team_ids: list[int],
    ) -> list[int]:
        ranking = parse_seed_ranking(getattr(stage, "settings_json", None))
        if ranking is SeedRanking.SLOT or not team_ids:
            return team_ids
        teams = await self._load_rankable_teams(session, team_ids)
        return apply_seed_ranking(team_ids, teams, ranking, rng_seed=stage.id)

    async def _get_swiss_generation_context(
        self,
        session: AsyncSession,
        stage_id: int,
        stage_item_id: int | None,
    ) -> tuple[list[SwissStanding] | None, set[frozenset[int]] | None, int]:
        existing = list(
            await self.encounter_repo.list_for_stage_scope(session, stage_id=stage_id, stage_item_id=stage_item_id)
        )
        if not existing:
            return None, None, 1

        swiss_round = max(e.round for e in existing) + 1
        swiss_played_pairs: set[frozenset[int]] = set()
        for encounter in existing:
            if encounter.home_team_id and encounter.away_team_id:
                swiss_played_pairs.add(frozenset({encounter.home_team_id, encounter.away_team_id}))

        # No repository method covers standings ordered by position within one
        # stage scope; built from the repo's select() meanwhile.
        standing_result = await session.execute(
            self.standing_repo.select()
            .where(
                models.Standing.stage_id == stage_id,
                models.Standing.stage_item_id == stage_item_id,
            )
            .order_by(models.Standing.position, models.Standing.team_id)
        )
        raw_standings = list(standing_result.scalars().all())
        swiss_standings = [
            SwissStanding(
                team_id=standing.team_id,
                points=standing.points,
                buchholz=standing.buchholz or 0.0,
            )
            for standing in raw_standings
        ]

        return swiss_standings, swiss_played_pairs, swiss_round

    async def _generate_stage_skeleton(
        self,
        session: AsyncSession,
        stage: models.Stage,
        team_ids: list[int],
        stage_item_id: int | None,
        *,
        lower_bracket_team_ids: list[int] | None = None,
    ) -> BracketSkeleton:
        swiss_standings = None
        swiss_played_pairs: set[frozenset[int]] | None = None
        swiss_round = 1
        if stage.stage_type == enums.StageType.SWISS:
            swiss_standings, swiss_played_pairs, swiss_round = await self._get_swiss_generation_context(
                session, stage.id, stage_item_id
            )
            if swiss_standings is None:
                clear_swiss_byes(stage, stage_item_id)
            from src.services.standings.swiss_auto_round import stage_allows_next_round, stage_max_rounds

            if not stage_allows_next_round(stage, swiss_round):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Swiss stage reached max_rounds",
                )

            # A Swiss allowed as many rounds as a full circle IS a round robin.
            # Pairing it one round at a time only invites corners where no
            # rematch-free round is left, and no ordering of the schedule can
            # matter when every team meets every other anyway.
            if swiss_standings is None and stage_max_rounds(stage) >= len(team_ids) - 1:
                clear_swiss_scope_stopped(stage, stage_item_id)
                return round_robin.generate(team_ids)

        de_include_reset = (
            stage.stage_type == enums.StageType.DOUBLE_ELIMINATION
            and (stage.settings_json or {}).get("de_grand_final_type") == "with_reset"
        )

        try:
            skeleton = generate_bracket(
                stage.stage_type,
                team_ids,
                swiss_standings=swiss_standings,
                swiss_played_pairs=swiss_played_pairs,
                swiss_round_number=swiss_round,
                swiss_bye_history=set(swiss_bye_team_ids(stage, stage_item_id)),
                de_include_reset=de_include_reset,
                lower_bracket_team_ids=lower_bracket_team_ids,
            )
        except SwissPairingImpossibleError:
            mark_swiss_scope_stopped(stage, stage_item_id)
            logger.info(
                "Swiss scope ended because no complete non-rematch pairing exists",
                stage_id=stage.id,
                stage_item_id=stage_item_id,
                round=swiss_round,
            )
            return BracketSkeleton(pairings=[], total_rounds=0)

        if stage.stage_type == enums.StageType.SWISS:
            clear_swiss_scope_stopped(stage, stage_item_id)
            if skeleton.bye_team_id is not None:
                record_swiss_bye(stage, stage_item_id, skeleton.bye_team_id)
        return skeleton

    async def _create_encounters_from_skeleton(
        self,
        session: AsyncSession,
        stage: models.Stage,
        skeleton: BracketSkeleton,
        stage_item_id: int | None,
        *,
        team_names_by_id: dict[int, str],
        lb_stage_item_id: int | None = None,
    ) -> list[models.Encounter]:
        """Persist bracket pairings as Encounter rows and wire EncounterLink records."""
        best_of_cfg = parse_best_of_config(stage.settings_json)
        return await persist_skeleton(
            session,
            stage=stage,
            skeleton=skeleton,
            stage_item_id=stage_item_id,
            team_names_by_id=team_names_by_id,
            lb_stage_item_id=lb_stage_item_id,
            is_elimination=stage.stage_type in BRACKET_STAGE_TYPES,
            best_of_for_round=lambda round_number, *, is_final: resolve_best_of(
                best_of_cfg, round_number, is_final=is_final
            ),
        )

    async def _fill_bracket_seeds(
        self,
        session: AsyncSession,
        stage: models.Stage,
        upper_ids: list[int],
        lower_ids: list[int],
    ) -> list[models.Encounter] | None:
        """Seed real teams into a bracket that was generated before it had any.

        ``generate_encounters`` can build a bracket off the preceding group stage's
        ``advance_count`` alone, which leaves every slot TBD. Once the groups finish
        and the TENTATIVE inputs resolve, the shape is already right and only the
        seeds are missing — so they are written into the existing encounters rather
        than throwing the bracket away, which would take its ids, schedule and
        advancement links with it.

        Returns ``None``, leaving the caller to refuse, unless the stage really is
        that untouched preview: a recorded team or an encounter that left ``OPEN``
        means this is a live bracket, and so does a shape the resolved seeds would
        no longer produce.
        """
        # ``EncounterRepository.list_by_stage`` also predicates on tournament_id,
        # which would change the rows this preview check sees; kept as a select().
        result = await session.execute(
            self.encounter_repo.select()
            .where(models.Encounter.stage_id == stage.id)
            .order_by(models.Encounter.round, models.Encounter.id)
        )
        existing = list(result.scalars().all())
        if not existing or any(
            encounter.home_team_id is not None
            or encounter.away_team_id is not None
            or encounter.status != enums.EncounterStatus.OPEN
            for encounter in existing
        ):
            return None

        seed_ids = upper_ids + lower_ids
        skeleton = _resolve_seeds(
            placeholder_bracket(stage.stage_type, len(upper_ids), lower_count=len(lower_ids)),
            dict(zip(placeholder_seeds(len(seed_ids)), seed_ids, strict=True)),
        )

        encounters_by_round: dict[int, list[models.Encounter]] = {}
        for encounter in existing:
            encounters_by_round.setdefault(encounter.round, []).append(encounter)
        pairings_by_round: dict[int, list[Pairing]] = {}
        for pairing in skeleton.pairings:
            pairings_by_round.setdefault(pairing.round_number, []).append(pairing)
        if {rnd: len(items) for rnd, items in encounters_by_round.items()} != {
            rnd: len(items) for rnd, items in pairings_by_round.items()
        }:
            return None

        team_names_by_id = await self._load_team_names(session, upper_ids + lower_ids)
        for round_number, pairings in pairings_by_round.items():
            for pairing, encounter in zip(pairings, encounters_by_round[round_number], strict=True):
                encounter.home_team_id = pairing.home_team_id
                encounter.away_team_id = pairing.away_team_id
                encounter.name = build_encounter_name_from_ids(
                    pairing.home_team_id,
                    pairing.away_team_id,
                    team_names_by_id,
                )
        await session.flush()
        return existing

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
        - stage has no stage_items
        - team count is zero
        - teams don't all belong to the same tournament as the stage
        """
        stage = await self.get_stage(session, stage_id)
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

        # Track next free slot per stage_item so we don't collide with preserved
        # TENTATIVE inputs.
        next_slot: dict[int, int] = {}
        for item in stage_items:
            used_slots = {inp.slot for inp in item.inputs if inp.input_type != enums.StageItemInputType.FINAL}
            candidate = 1
            while candidate in used_slots:
                candidate += 1
            next_slot[item.id] = candidate

        snake = mode != "random"

        for team_idx, team in enumerate(teams_sorted):
            group_idx = group_for_index(team_idx, num_groups, snake=snake)
            target_item = stage_items[group_idx]
            slot = next_slot[target_item.id]
            next_slot[target_item.id] = slot + 1

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
            "Seeded %d teams into stage %s across %d groups (mode=%s)",
            len(teams_sorted),
            stage.id,
            num_groups,
            mode,
        )
        return await self.get_stage(session, stage_id)

    async def wire_from_groups(
        self,
        session: AsyncSession,
        target_stage_id: int,
        source_stage_id: int,
        top: int,
        *,
        top_lb: int = 0,
        mode: str = "cross",
        notify: bool = True,
        commit: bool = True,
    ) -> models.Stage:
        """Wire TENTATIVE inputs in ``target_stage`` pointing to top-N of each group in
        ``source_stage``.

        Supports two seeding modes:

        - ``cross`` (default): standard cross-group seeding that avoids same-group
          rematches in the first playoff round. Given groups A, B, C, ... and
          ``top=2``, slots are arranged as:
              A1, B2, C1, D2, ...  A2, B1, C2, D1
          i.e. every slot ``i`` uses group ``i % G`` and position ``1 + (i // G) % top``
          with odd "columns" flipped. This guarantees group A's 1st-seed does not
          meet group A's 2nd-seed in round 1.
        - ``snake``: simple top-down (all 1st-seeds first, then all 2nd-seeds, ...).

        Each group sends its own ``StageItem.advance_count`` when that is set,
        split upper/lower by the same rule auto-wiring uses; groups without one
        take the caller's ``top``/``top_lb`` verbatim. A group's lower-bracket
        band starts right after its own upper band, so uneven groups do not share
        one offset. ``top_lb > 0`` requires a DOUBLE_ELIMINATION target with a
        BRACKET_LOWER stage item.

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
        if source_stage.stage_type not in GROUPED_GENERATION_STAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source stage must be ROUND_ROBIN or SWISS",
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
        if top_lb > 0:
            if target_stage.stage_type != enums.StageType.DOUBLE_ELIMINATION:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="`top_lb` requires a double_elimination target stage",
                )
            if lb_item is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=("Target stage has no BRACKET_LOWER stage item; create one before using top_lb"),
                )

        source_items = sorted(source_stage.items, key=lambda item: (item.order, item.id))
        if not source_items:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Source stage has no stage items",
            )

        num_groups = len(source_items)

        # Per group: its own ``advance_count`` if set, else the caller's top/top_lb.
        counts = group_advance_counts(target_stage, source_items, default_upper=top, default_lower=top_lb)
        if not any(upper or lower for _, upper, lower in counts):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nothing advances: set `top`, or an advance count on the source stage or its groups",
            )

        # UB: first stage_item by order. A group's lower-bracket band starts right
        # after its own upper one, which for uneven groups is not a shared offset.
        ub_item = sorted(target_stage.items, key=lambda item: (item.order, item.id))[0]
        _apply_seeding(session, _build_seeding([GroupSlice(i, 1, ub) for i, ub, _ in counts], mode), ub_item)

        lb_slices = [GroupSlice(i, ub + 1, lb) for i, ub, lb in counts if lb > 0]
        if lb_slices and lb_item is not None:
            _apply_seeding(session, _build_seeding(lb_slices, mode), lb_item)

        if notify:
            await self._publish_structure_changed(session, target_stage.tournament_id)
        if commit:
            await session.commit()
        else:
            await session.flush()

        logger.info(
            "Wired TENTATIVE inputs from stage %s (%d groups × top %d, top_lb %d) into stage %s (%s)",
            source_stage.id,
            num_groups,
            top,
            top_lb,
            target_stage.id,
            mode,
        )
        return target_stage if not commit else await self.get_stage(session, target_stage_id)

    async def _check_upstream_stages_completed(self, session: AsyncSession, stage: models.Stage) -> list[int]:
        """Return ids of upstream stages that feed into ``stage`` via TENTATIVE
        inputs but are NOT yet marked ``is_completed``. Empty list means safe
        to activate. Used by /activate-and-generate to prevent admins from
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

    async def _preceding_phase_group_stages(
        self, session: AsyncSession, stage: models.Stage
    ) -> list[models.Stage]:
        result = await session.execute(
            self.stage_repo.select()
            .where(
                models.Stage.tournament_id == stage.tournament_id,
                models.Stage.stage_type.in_(GROUPED_GENERATION_STAGE_TYPES),
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
        earlier phase is ambiguous — returns None so auto-wire does not guess.
        """
        tied = await self._preceding_phase_group_stages(session, stage)
        return tied[0] if len(tied) == 1 else None


    async def _auto_wire_from_groups(self, session: AsyncSession, stage: models.Stage, *, strict: bool = False) -> bool:
        """Derive playoff seeding from the preceding group stage's ``advance_count``
        and this stage's ``split_lower_bracket`` flag, then wire TENTATIVE inputs
        (cross seeding). Replaces the manual Automation block.

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
        source = await self._preceding_group_stage(session, stage)
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

        top, top_lb = _advance_split(stage, stage_advance)

        # The bracket engine applies standard 1-vs-N seeding (``_seeding_order``)
        # internally, which already spreads the top seeds across the bracket. Feeding
        # it a plain group-major order ("snake": A1, B1, …, A2, B2, …) therefore
        # avoids same-group round-1 rematches; the "cross" order double-crosses and
        # reunites group opponents in round 1.
        await self.wire_from_groups(
            session,
            stage.id,
            source.id,
            top,
            top_lb=top_lb,
            mode="snake",
            notify=False,
            commit=False,
        )
        return True

    async def auto_wire_stage(
        self, session: AsyncSession, stage_id: int, *, notify: bool = True, commit: bool = True
    ) -> models.Stage:
        """Standalone trigger for the same group->bracket auto-wiring that
        "Activate & generate" runs automatically. Lets an admin preview/debug the
        wiring, or refresh it after changing the source stage's "Teams advancing
        to playoff" count, without activating or generating anything.
        """
        stage = await self.get_stage(session, stage_id)
        await self._auto_wire_from_groups(session, stage, strict=True)
        if notify:
            await self._publish_structure_changed(session, stage.tournament_id)
        if commit:
            await session.commit()
        else:
            await session.flush()
        return await self.get_stage(session, stage_id)

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
        # Auto-wire playoff seeds from the preceding group stage (replaces the manual
        # Automation block). Runs BEFORE the upstream-completion check so that check
        # sees the freshly created TENTATIVE inputs.
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

    async def generate_encounters(
        self,
        session: AsyncSession,
        stage_id: int,
        *,
        notify: bool = True,
        commit: bool = True,
        schedule_standings: bool = True,
        stage: models.Stage | None = None,
    ) -> list[models.Encounter]:
        """Generate bracket encounters for a stage based on its type and team inputs.

        Never overwrites: an item (or, for a non-grouped stage, the stage as a
        whole) that already has encounters is left alone rather than getting a
        second set of matches. A grouped stage (Swiss/Round Robin with multiple
        groups) lets a newly added group generate on its own once earlier groups
        are already underway; a non-grouped stage refuses outright, since there
        is no partial bracket to preserve there -- delete its matches first to
        regenerate.

        A bracket stage with no seeds is the one exception. Rather than refuse, it
        is built from the preceding group stage's ``advance_count`` × groups (see
        ``_bracket_seed_counts``) with every slot left TBD, so the playoff can be
        laid out, scheduled and configured while the groups are still running;
        ``_fill_bracket_seeds`` writes the teams into it once they resolve.
        """
        stage = stage or await self.get_stage(session, stage_id)

        existing_by_item_result = await session.execute(
            select(models.Encounter.stage_item_id, func.count())
            .where(models.Encounter.stage_id == stage_id)
            .group_by(models.Encounter.stage_item_id)
        )
        existing_by_item: dict[int | None, int] = dict(existing_by_item_result.all())

        if stage.stage_type in GROUPED_GENERATION_STAGE_TYPES and len(stage.items) > 1:
            encounters = await self._generate_grouped_encounters(session, stage, existing_by_item)
        else:
            encounters = await self._generate_bracket_encounters(session, stage, existing_by_item)

        await self._finish_structure_write(
            session,
            stage,
            notify=notify,
            commit=commit,
            schedule_standings=schedule_standings,
        )
        return encounters

    async def _generate_grouped_encounters(
        self,
        session: AsyncSession,
        stage: models.Stage,
        existing_by_item: dict[int | None, int],
    ) -> list[models.Encounter]:
        eligible_items = [item for item in stage.items if existing_by_item.get(item.id, 0) == 0]
        if not eligible_items:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Every group already has generated matches. Delete a group's matches first to regenerate it.",
            )
        encounters: list[models.Encounter] = []
        for item in eligible_items:
            team_ids = _collect_item_team_ids(item)
            if len(team_ids) < 2:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Each group needs at least 2 teams to generate a bracket",
                )
            skeleton = await self._generate_stage_skeleton(session, stage, team_ids, item.id)
            team_names_by_id = await self._load_team_names(session, team_ids)
            encounters.extend(
                await self._create_encounters_from_skeleton(
                    session,
                    stage,
                    skeleton,
                    item.id,
                    team_names_by_id=team_names_by_id,
                )
            )
        return encounters

    async def _generate_bracket_encounters(
        self,
        session: AsyncSession,
        stage: models.Stage,
        existing_by_item: dict[int | None, int],
    ) -> list[models.Encounter]:
        sorted_items = sorted(stage.items, key=lambda it: (it.order, it.id))
        primary_item_id = sorted_items[0].id if sorted_items else None
        lb_item = _lower_bracket_item(stage, sorted_items)
        lb_stage_item_id = lb_item.id if lb_item is not None else None

        team_ids, lower_bracket_team_ids = _bracket_seeds(stage, sorted_items, lb_item)
        is_bracket = stage.stage_type in BRACKET_STAGE_TYPES
        if is_bracket:
            team_ids = await self._rank_seed_ids(session, stage, team_ids)
            lower_bracket_team_ids = await self._rank_seed_ids(session, stage, lower_bracket_team_ids)

        seeds_are_placeholders = False
        if is_bracket and len(team_ids) + len(lower_bracket_team_ids) < 2:
            upper_count, lower_count = await self._projected_bracket_seed_counts(session, stage)
            team_ids = placeholder_seeds(upper_count)
            lower_bracket_team_ids = placeholder_seeds(lower_count, offset=upper_count)
            seeds_are_placeholders = True

        if sum(existing_by_item.values()) > 0:
            filled = (
                None
                if seeds_are_placeholders or not is_bracket
                else await self._fill_bracket_seeds(session, stage, team_ids, lower_bracket_team_ids)
            )
            if filled is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This stage already has generated matches. Delete them first to regenerate the bracket.",
                )
            return filled

        if len(team_ids) < 2:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Need at least 2 teams to generate a bracket",
            )

        skeleton = await self._generate_stage_skeleton(
            session,
            stage,
            team_ids,
            primary_item_id,
            lower_bracket_team_ids=lower_bracket_team_ids,
        )
        if seeds_are_placeholders:
            skeleton = _resolve_seeds(skeleton, {})
        team_names_by_id = await self._load_team_names(session, team_ids + lower_bracket_team_ids)
        return await self._create_encounters_from_skeleton(
            session,
            stage,
            skeleton,
            primary_item_id,
            team_names_by_id=team_names_by_id,
            lb_stage_item_id=lb_stage_item_id,
        )

    async def apply_best_of_to_existing(self, session: AsyncSession, stage_id: int) -> int:
        """Backfill ``best_of`` on a stage's existing encounters from its config.

        Reads ``Stage.settings_json['best_of']`` and rewrites each encounter's
        ``best_of`` in place (preserving scores/results). Applies the same
        resolution the generator uses; ``final`` targets the max round among the
        stage's encounters for elimination stages. Returns the number of rows
        whose ``best_of`` actually changed.
        """
        stage = await self.get_stage(session, stage_id)
        cfg = parse_best_of_config(stage.settings_json)
        is_elimination = stage.stage_type in BRACKET_STAGE_TYPES

        # ``EncounterRepository.list_by_stage`` also predicates on tournament_id
        # and orders the rows; neither matches this backfill's original scan.
        result = await session.execute(self.encounter_repo.select().where(models.Encounter.stage_id == stage_id))
        encounters = list(result.scalars().all())
        max_round = max((encounter.round for encounter in encounters), default=0)

        changed = 0
        for encounter in encounters:
            target = resolve_best_of(
                cfg,
                encounter.round,
                is_final=is_elimination and encounter.round == max_round,
            )
            if encounter.best_of != target:
                encounter.best_of = target
                changed += 1

        if changed:
            await self._publish_structure_changed(session, stage.tournament_id)
        await session.commit()
        return changed


stage_service = AdminStageService()
