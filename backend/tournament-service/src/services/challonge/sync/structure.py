"""Local stage / group / stage-item / stage-input rows a Challonge bracket implies."""

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.repository import (
    BracketEncounterRepository,
    StageItemInputRepository,
    StageItemRepository,
    StageRepository,
)
from shared.services.encounter.participants import active_teams
from src import schemas
from src.services.challonge.stage_refs import StageRefs, resolve_stage_refs_from_group
from src.services.challonge.sync._types import _ImportSource
from src.services.challonge.sync.helpers import (
    _append_once,
    _default_stage_item_id,
    _find_loaded_stage_item,
    _find_playoff_stage,
    _group_names_for_challonge_ids,
    _loaded_collection,
    _next_stage_order,
    _playoff_stage_type,
    _stage_for_challonge_group,
    _stage_item_type_for_stage,
)


class ChallongeStructureService:
    """Creates the local stage / group / stage-item / stage-item-input rows a
    Challonge bracket implies, before any match can be routed to one."""

    def __init__(
        self,
        *,
        stage_repo: StageRepository = StageRepository(),
        stage_item_repo: StageItemRepository = StageItemRepository(),
        stage_item_input_repo: StageItemInputRepository = StageItemInputRepository(),
        bracket_encounter_repo: BracketEncounterRepository = BracketEncounterRepository(),
    ) -> None:
        self.stage_repo = stage_repo
        self.stage_item_repo = stage_item_repo
        self.stage_item_input_repo = stage_item_input_repo
        self.bracket_encounter_repo = bracket_encounter_repo

    async def _ensure_stage_item(
        self,
        session: AsyncSession,
        stage: models.Stage,
        *,
        name: str,
        item_type: enums.StageItemType,
    ) -> models.StageItem:
        # If items are not loaded in this session state, query them async to avoid
        # triggering a synchronous lazy-load (MissingGreenlet) in an async context.
        try:
            items_unloaded = "items" in sa_inspect(stage).unloaded
        except Exception:
            items_unloaded = False

        if items_unloaded:
            existing = await self.stage_item_repo.list_by_stage(session, stage.id)
        else:
            existing = list(stage.items or [])

        items = existing
        if items:
            return sorted(items, key=lambda item: (item.order, item.id))[0]

        item = models.StageItem(
            stage_id=stage.id,
            name=name,
            type=item_type,
            order=0,
        )
        item.inputs = []
        await self.stage_item_repo.create(session, item)
        if not items_unloaded:
            stage.items.append(item)
        return item

    async def _create_stage_with_item(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        *,
        name: str,
        description: str | None,
        stage_type: enums.StageType,
        item_type: enums.StageItemType,
    ) -> models.Stage:
        # Stage-level Challonge identity lives in ``challonge_source`` (derived at
        # read time), not on the stage row.
        stage = models.Stage(
            tournament_id=tournament.id,
            name=name,
            description=description,
            stage_type=stage_type,
            order=_next_stage_order(tournament),
        )
        # Seeded while the stage is still transient, like ``item.inputs`` below: the
        # flush turns it persistent, and from then on the first touch of a collection
        # nothing ever loaded emits a lazy SELECT -- MissingGreenlet under async
        # SQLAlchemy.
        stage.items = []
        stage.round_best_of = []
        await self.stage_repo.create(session, stage)
        _append_once(tournament.stages, stage)
        item = models.StageItem(
            stage_id=stage.id,
            name=name,
            type=item_type,
            order=0,
        )
        item.inputs = []
        await self.stage_item_repo.create(session, item)
        _append_once(stage.items, item)
        return stage

    async def _ensure_group_stage(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        stage: models.Stage,
        *,
        item_type: enums.StageItemType,
    ) -> None:
        if stage not in (tournament.stages or []):
            _append_once(tournament.stages, stage)
        await self._ensure_stage_item(
            session,
            stage,
            name=stage.name,
            item_type=item_type,
        )

    async def _create_group_with_stage(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        *,
        name: str,
        challonge_id: int | None,
        stage_type: enums.StageType,
    ) -> models.Stage:
        stage = await self._create_stage_with_item(
            session,
            tournament,
            name=name,
            description=None,
            stage_type=stage_type,
            item_type=_stage_item_type_for_stage(stage_type),
        )
        if challonge_id is not None:
            stage.challonge_group_id = challonge_id
            await session.flush()
        return stage

    async def _ensure_stage_structure_for_matches(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        source: _ImportSource,
        matches: list[schemas.ChallongeMatch],
    ) -> dict[str, int]:
        stats = {"stages_created": 0, "groups_created": 0}

        if source.stage is not None:
            await self._ensure_stage_item(
                session,
                source.stage,
                name=source.stage.name,
                item_type=_stage_item_type_for_stage(source.stage.stage_type),
            )

        group_ids = {match.group_id for match in matches if match.group_id is not None}
        names_by_group_id = _group_names_for_challonge_ids(group_ids)
        for group_id in sorted(group_ids):
            stage = _stage_for_challonge_group(tournament, group_id)
            if stage is None and source.stage is not None:
                existing_id = source.stage.challonge_group_id
                if existing_id == group_id or (
                    existing_id is None and source.stage.stage_type == enums.StageType.ROUND_ROBIN
                ):
                    stage = source.stage
            if stage is None:
                await self._create_group_with_stage(
                    session,
                    tournament,
                    name=names_by_group_id[group_id],
                    challonge_id=group_id,
                    stage_type=enums.StageType.ROUND_ROBIN,
                )
                stats["groups_created"] += 1
                stats["stages_created"] += 1
            else:
                if stage.challonge_group_id != group_id:
                    stage.challonge_group_id = group_id
                before_stage_count = len(tournament.stages or [])
                await self._ensure_group_stage(
                    session,
                    tournament,
                    stage,
                    item_type=enums.StageItemType.GROUP,
                )
                stats["stages_created"] += max(0, len(tournament.stages or []) - before_stage_count)

        ungrouped_matches = [match for match in matches if match.group_id is None]
        if not ungrouped_matches:
            return stats

        if source.stage is not None and not group_ids:
            return stats

        playoff_stage = _find_playoff_stage(tournament)
        if playoff_stage is None:
            await self._create_group_with_stage(
                session,
                tournament,
                name="Playoffs",
                challonge_id=None,
                stage_type=_playoff_stage_type(ungrouped_matches),
            )
            stats["groups_created"] += 1
            stats["stages_created"] += 1
        else:
            before_stage_count = len(tournament.stages or [])
            await self._ensure_group_stage(
                session,
                tournament,
                playoff_stage,
                item_type=enums.StageItemType.SINGLE_BRACKET,
            )
            stats["stages_created"] += max(0, len(tournament.stages or []) - before_stage_count)

        return stats

    async def _resolve_stage_refs_for_match(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        source: _ImportSource,
        stage: models.Stage | None,
        match: schemas.ChallongeMatch,
    ) -> StageRefs:
        if stage is None:
            stage = source.stage
        return await resolve_stage_refs_from_group(
            session,
            tournament_id=tournament.id,
            stage_id=stage.id if stage else None,
            stage_item_id=_default_stage_item_id(stage, match),
        )

    async def _load_stage_inputs(
        self,
        session: AsyncSession,
        stage_id: int,
    ) -> list[models.StageItemInput]:
        result = await session.execute(
            self.stage_item_input_repo.select()
            .join(models.StageItem, models.StageItemInput.stage_item_id == models.StageItem.id)
            .where(models.StageItem.stage_id == stage_id)
        )
        return list(result.scalars().all())

    async def _ensure_stage_item_team_inputs(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        *,
        stage_item_id: int | None,
        team_ids: list[int | None],
    ) -> int:
        if stage_item_id is None:
            return 0

        unique_team_ids: list[int] = []
        seen_team_ids: set[int] = set()
        for team_id in team_ids:
            if team_id is None or team_id in seen_team_ids:
                continue
            unique_team_ids.append(team_id)
            seen_team_ids.add(team_id)
        if not unique_team_ids:
            return 0

        stage, item = _find_loaded_stage_item(tournament, stage_item_id)
        if stage is None or item is None:
            return 0

        stage_items = _loaded_collection(stage, "items") or [item]
        stage_inputs: list[models.StageItemInput] = []
        inputs_loaded = True
        for candidate in stage_items:
            candidate_inputs = _loaded_collection(candidate, "inputs")
            if candidate_inputs is None:
                inputs_loaded = False
                break
            stage_inputs.extend(candidate_inputs)

        if not inputs_loaded:
            stage_inputs = await self._load_stage_inputs(session, stage.id)

        existing_team_ids = {stage_input.team_id for stage_input in stage_inputs if stage_input.team_id is not None}
        used_slots = {stage_input.slot for stage_input in stage_inputs if stage_input.stage_item_id == stage_item_id}
        next_slot = 1
        created: list[models.StageItemInput] = []

        for team_id in unique_team_ids:
            if team_id in existing_team_ids:
                continue
            while next_slot in used_slots:
                next_slot += 1
            stage_input = models.StageItemInput(
                stage_item_id=stage_item_id,
                slot=next_slot,
                input_type=enums.StageItemInputType.FINAL,
                team_id=team_id,
            )
            created.append(stage_input)
            existing_team_ids.add(team_id)
            used_slots.add(next_slot)
            next_slot += 1

            item_inputs = _loaded_collection(item, "inputs")
            if item_inputs is not None:
                try:
                    item.inputs.append(stage_input)
                except Exception:
                    pass

        if created:
            await self.stage_item_input_repo.create_many(session, created)
        return len(created)

    async def _ensure_encounter_stage_inputs(
        self,
        session: AsyncSession,
        tournament: models.Tournament,
        encounter: models.Encounter | None,
    ) -> int:
        if encounter is None:
            return 0
        position = await self.bracket_encounter_repo.get_position(session, encounter.id)
        if position is None:
            return 0
        return await self._ensure_stage_item_team_inputs(
            session,
            tournament,
            stage_item_id=position.stage_item_id,
            team_ids=[seat.team_id for seat in await active_teams(session, encounter.id)],
        )


structure_service = ChallongeStructureService()
