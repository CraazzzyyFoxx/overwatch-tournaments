import typing
from dataclasses import dataclass
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import enums, utils


def tournament_entities(
        in_entities: list[str], child: typing.Any | None = None
) -> list[sa.orm.strategy_options._AbstractLoad]:
    entities = []
    if "groups" in in_entities:
        entities.append(utils.join_entity(child, models.Tournament.groups))
    if "stages" in in_entities:
        stage_entity = utils.join_entity(child, models.Tournament.stages)
        stage_items_entity = utils.join_entity(stage_entity, models.Stage.items)
        entities.append(stage_entity)
        entities.append(stage_items_entity)
        entities.append(utils.join_entity(stage_items_entity, models.StageItem.inputs))
    return entities


async def get(session: AsyncSession, id: int, entities: list[str]) -> models.Tournament | None:
    query = (
        sa.select(models.Tournament).where(sa.and_(models.Tournament.id == id)).options(*tournament_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_all(
    session: AsyncSession,
    is_league: bool | None = None,
    is_finished: bool | None = None,
    entities: list[str] | None = None,
    workspace_id: int | None = None,
) -> typing.Sequence[models.Tournament]:
    query = (
        sa.select(models.Tournament)
        .options(*tournament_entities(entities or []))
        .order_by(models.Tournament.id.asc())
    )

    if is_league is not None:
        query = query.where(models.Tournament.is_league.is_(is_league))
    if is_finished is not None:
        query = query.where(models.Tournament.is_finished.is_(is_finished))
    if workspace_id is not None:
        query = query.where(models.Tournament.workspace_id == workspace_id)

    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_by_number(session: AsyncSession, number: int, entities: list[str]) -> models.Tournament | None:
    query = (
        sa.select(models.Tournament)
        .where(sa.and_(models.Tournament.number == number))
        .options(*tournament_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_by_number_and_league(
    session: AsyncSession, number: int, is_league: bool, entities: list[str]
) -> models.Tournament | None:
    query = (
        sa.select(models.Tournament)
        .where(
            sa.and_(
                models.Tournament.number == number,
                models.Tournament.is_league == is_league,
            )
        )
        .options(*tournament_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_by_name(session: AsyncSession, name: str, entities: list[str]) -> models.Tournament | None:
    query = (
        sa.select(models.Tournament)
        .where(sa.and_(models.Tournament.name == name))
        .options(*tournament_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def create(
    session: AsyncSession,
    *,
    workspace_id: int,
    number: int,
    is_league: bool,
    name: str,
    description: str | None = None,
    challonge_id: int | None = None,
    challonge_slug: str | None = None,
    start_date: datetime | date | None = None,
    end_date: datetime | date | None = None,
    division_grid_version_id: int | None = None,
) -> models.Tournament:
    tournament = models.Tournament(
        workspace_id=workspace_id,
        number=number,
        is_league=is_league,
        name=name,
        description=description,
        challonge_id=challonge_id,
        challonge_slug=challonge_slug,
        start_date=start_date,
        end_date=end_date,
        division_grid_version_id=division_grid_version_id,
    )
    session.add(tournament)
    await session.commit()
    return tournament


@dataclass(frozen=True)
class GroupSpec:
    """Plain-value description of one group to create (see ``create_groups``)."""

    name: str
    is_groups: bool
    description: str | None = None
    challonge_id: int | None = None
    challonge_slug: str | None = None


async def create_groups(
    session: AsyncSession,
    tournament: models.Tournament,
    specs: list[GroupSpec],
) -> list[models.TournamentGroup]:
    """Create legacy TournamentGroups AND their corresponding Stage/StageItems.

    Ensures every new group is immediately part of the new stage model so that
    encounters attached to these groups render correctly on the public bracket
    view (which filters by stage_id/stage_item_id).

    Batched counterpart of ``create_group``: one max-order SELECT, two flushes
    and a single commit for the whole set instead of one SELECT + commit per
    group. Stage orders are assigned sequentially in ``specs`` order, exactly
    as repeated ``create_group`` calls would have done.
    """
    if not specs:
        return []

    # 1. Determine stage order: highest existing stage order in this tournament + 1
    max_order_row = await session.execute(
        sa.select(sa.func.coalesce(sa.func.max(models.Stage.order), -1)).where(
            models.Stage.tournament_id == tournament.id
        )
    )
    next_order = int(max_order_row.scalar_one()) + 1

    stages: list[models.Stage] = []
    for offset, spec in enumerate(specs):
        stage_type = (
            enums.StageType.ROUND_ROBIN if spec.is_groups else enums.StageType.DOUBLE_ELIMINATION
        )
        stages.append(
            models.Stage(
                tournament_id=tournament.id,
                name=spec.name,
                description=spec.description,
                stage_type=stage_type,
                order=next_order + offset,
                challonge_id=spec.challonge_id,
                challonge_slug=spec.challonge_slug,
            )
        )
    session.add_all(stages)
    await session.flush()

    groups: list[models.TournamentGroup] = []
    for spec, stage in zip(specs, stages, strict=True):
        stage_item_type = (
            enums.StageItemType.GROUP if spec.is_groups else enums.StageItemType.SINGLE_BRACKET
        )
        session.add(
            models.StageItem(
                stage_id=stage.id,
                name=spec.name,
                type=stage_item_type,
                order=0,
            )
        )
        group = models.TournamentGroup(
            tournament=tournament,
            name=spec.name,
            description=spec.description,
            is_groups=spec.is_groups,
            challonge_id=spec.challonge_id,
            challonge_slug=spec.challonge_slug,
            stage_id=stage.id,
        )
        session.add(group)
        groups.append(group)

    await session.commit()
    return groups


async def create_group(
    session: AsyncSession,
    tournament: models.Tournament,
    *,
    name: str,
    description: str | None = None,
    is_groups: bool = False,
    challonge_id: int | None = None,
    challonge_slug: str | None = None,
) -> models.TournamentGroup:
    """Single-group convenience wrapper around ``create_groups``."""
    groups = await create_groups(
        session,
        tournament,
        [
            GroupSpec(
                name=name,
                is_groups=is_groups,
                description=description,
                challonge_id=challonge_id,
                challonge_slug=challonge_slug,
            )
        ],
    )
    return groups[0]
