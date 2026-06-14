import typing

import sqlalchemy as sa
from shared.domain.player_sub_roles import normalize_sub_role
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.orm.strategy_options import _AbstractLoad

from src import models
from src.core import enums, utils
from src.services.user import service as user_service


def team_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    entities: list[_AbstractLoad] = []

    if "tournament" in in_entities:
        entities.append(utils.join_entity(child, models.Team.tournament))
    if "players" in in_entities:
        players_entities = utils.prepare_entities(in_entities, "players")
        players_entity = utils.join_entity(child, models.Team.players)
        entities.append(players_entity)
        if "user" in players_entities:
            user_entity = utils.join_entity(players_entity, models.Player.user)
            entities.append(user_entity)
            entities.extend(user_service.user_entities(utils.prepare_entities(players_entities, "user"), user_entity))
    if "captain" in in_entities:
        captain_entity = utils.join_entity(child, models.Team.captain)
        entities.append(captain_entity)
        entities.extend(user_service.user_entities(utils.prepare_entities(in_entities, "captain"), captain_entity))
    if "placement" in in_entities:
        entities.append(utils.join_entity(child, models.Team.standings))

    return entities


def player_entities(entities_in: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    entities = []

    if "user" in entities_in:
        entities.append(utils.join_entity(child, models.Player.user))
    if "tournament" in entities_in:
        entities.append(utils.join_entity(child, models.Player.tournament))
    if "team" in entities_in:
        team_entity = utils.join_entity(child, models.Player.team)
        entities.append(team_entity)
        entities.extend(team_entities(utils.prepare_entities(entities_in, "team"), team_entity))

    return entities


async def get(session: AsyncSession, team_id: int, entities: list[str]) -> models.Team | None:
    query = sa.select(models.Team).where(sa.and_(models.Team.id == team_id)).options(*team_entities(entities))
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_by_name_and_tournament(
    session: AsyncSession, tournament_id: int, name: str, entities: list[str]
) -> models.Team | None:
    query = (
        sa.select(models.Team)
        .where(
            sa.and_(
                sa.func.lower(models.Team.name) == name.lower(),
                models.Team.tournament_id == tournament_id,
            )
        )
        .options(*team_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_by_tournament(
    session: AsyncSession, tournament_id: int, entities: list[str]
) -> typing.Sequence[models.Team]:
    query = sa.select(models.Team).filter_by(tournament_id=tournament_id).options(*team_entities(entities))
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_by_tournament_challonge_id(
    session: AsyncSession, tournament_id: int, challonge_id: int, entities: list[str]
) -> models.Team | None:
    query = (
        sa.select(models.Team)
        .options(*team_entities(entities))
        .join(models.ChallongeTeam, models.Team.id == models.ChallongeTeam.team_id)
        .where(
            sa.and_(
                models.ChallongeTeam.tournament_id == tournament_id,
                models.ChallongeTeam.challonge_id == challonge_id,
            )
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_by_captain_tournament(
    session: AsyncSession,
    captain: models.User,
    tournament: models.Tournament,
    entities: list[str],
) -> models.Team | None:
    query = (
        sa.select(models.Team)
        .where(
            sa.and_(
                models.Team.captain_id == captain.id,
                models.Team.tournament_id == tournament.id,
            )
        )
        .options(*team_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_by_players_by_ids_tournament(
    session: AsyncSession,
    players_ids: list[int],
    tournament: models.Tournament,
    entities: list[str],
) -> models.Team | None:
    query = (
        sa.select(models.Team)
        .join(models.Player, models.Team.id == models.Player.team_id)
        .options(*team_entities(entities))
        .where(
            sa.and_(
                models.Player.user_id.in_(players_ids),
                models.Team.tournament_id == tournament.id,
                models.Player.is_substitution.is_(False),
            )
        )
        .group_by(models.Team.id)
        .having(sa.func.count(models.Player.id) >= 3)
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_players_tournament(
    session: AsyncSession, tournament_id: int, entities: list[str]
) -> typing.Sequence[models.Player]:
    query = (
        sa.select(models.Player)
        .options(*player_entities(entities))
        .where(models.Player.tournament_id == tournament_id, models.Player.is_substitution.is_(False))
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_player_by_user_and_tournament(
    session: AsyncSession, user_id: int, tournament_id: int, entities: list[str]
) -> models.Player | None:
    query = (
        sa.select(models.Player)
        .options(*player_entities(entities))
        .where(
            sa.and_(
                models.Player.user_id == user_id,
                models.Player.tournament_id == tournament_id,
            )
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_player_by_team_and_user(
    session: AsyncSession, team_id: int, user_id: int, entities: list[str]
) -> models.Player | None:
    query = (
        sa.select(models.Player)
        .options(*player_entities(entities))
        .where(sa.and_(models.Player.user_id == user_id, models.Player.team_id == team_id))
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_player_by_user(
    session: AsyncSession, user_id: int, entities: list[str]
) -> typing.Sequence[models.Player]:
    query = (
        sa.select(models.Player).where(sa.and_(models.Player.user_id == user_id)).options(*player_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_player_by_user_and_role(
    session: AsyncSession, user_id: int, role: enums.HeroClass, entities: list[str]
) -> typing.Sequence[models.Player]:
    query = (
        sa.select(models.Player)
        .options(*player_entities(entities))
        .where(sa.and_(models.Player.user_id == user_id, models.Player.role == role))
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def create(
    session: AsyncSession,
    *,
    name: str,
    balancer_name: str,
    avg_sr: float,
    total_sr: int,
    tournament: models.Tournament,
    captain: models.User,
) -> models.Team:
    team = models.Team(
        name=name,
        balancer_name=balancer_name,
        avg_sr=avg_sr,
        total_sr=total_sr,
        tournament_id=tournament.id,
        captain_id=captain.id,
    )

    session.add(team)
    await session.commit()
    return team


def construct_player(
    **kwargs,
) -> models.Player:
    return models.Player(
        **kwargs,
    )


async def create_player(
    session: AsyncSession,
    *,
    name: str,
    sub_role: str | None = None,
    rank: int,
    role: enums.HeroClass,
    user: models.User,
    tournament: models.Tournament,
    team: models.Team,
    is_substitution: bool = False,
    related_player_id: int | None = None,
    is_newcomer: bool = False,
    is_newcomer_role: bool = False,
) -> models.Player:
    player = models.Player(
        name=name,
        sub_role=normalize_sub_role(sub_role),
        rank=rank,
        role=role,
        user_id=user.id,
        tournament_id=tournament.id,
        team_id=team.id,
        is_substitution=is_substitution,
        related_player_id=related_player_id,
        is_newcomer=is_newcomer,
        is_newcomer_role=is_newcomer_role,
    )

    session.add(player)
    await session.commit()
    return player


def create_player_sync(
    session: Session,
    *,
    name: str,
    sub_role: str | None = None,
    rank: int,
    role: enums.HeroClass,
    user: models.User,
    tournament: models.Tournament,
    team: models.Team,
    is_substitution: bool = False,
    related_player_id: int | None = None,
    is_newcomer: bool = False,
    is_newcomer_role: bool = False,
) -> models.Player:
    player = models.Player(
        name=name,
        sub_role=normalize_sub_role(sub_role),
        rank=rank,
        role=role,
        user_id=user.id,
        tournament_id=tournament.id,
        team_id=team.id,
        is_substitution=is_substitution,
        related_player_id=related_player_id,
        is_newcomer=is_newcomer,
        is_newcomer_role=is_newcomer_role,
    )

    session.add(player)
    session.commit()
    return player


async def get_teams_by_tournament(
    session: AsyncSession, tournament_id: int, entities: list[str]
) -> typing.Sequence[models.Team]:
    query = (
        sa.select(models.Team)
        .options(*team_entities(entities))
        .where(sa.and_(models.Team.tournament_id == tournament_id))
    )
    result = await session.execute(query)
    return result.unique().scalars().all()
