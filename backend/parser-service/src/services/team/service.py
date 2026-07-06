import typing

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared.domain.player_sub_roles import normalize_sub_role
from shared.repository import get_or_create_workspace_member
from src import models
from src.core import enums, utils
from src.services.user import service as user_service


async def _resolve_workspace_member_id(
    session: AsyncSession,
    *,
    tournament_id: int,
    player_id: int,
) -> int:
    """Resolve the ``workspace_member`` anchor for a roster player being created.

    The workspace is derived from the player's tournament (``tournament.workspace_id``);
    the member row is created idempotently if one does not already exist for this
    (workspace, player) pair.
    """
    workspace_id_result = await session.execute(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    workspace_id = workspace_id_result.scalar_one()
    member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=player_id)
    return member.id


async def resolve_workspace_member_ids(
    session: AsyncSession,
    *,
    workspace_id: int,
    player_ids: set[int],
) -> dict[int, int]:
    """Batch counterpart of ``_resolve_workspace_member_id``: resolve (or create)
    the ``workspace_member`` anchors for a whole roster in two statements.

    Mirrors ``get_or_create_workspace_member``'s insert-or-select idempotency
    (``INSERT ... ON CONFLICT DO NOTHING`` on
    ``uq_workspace_member_workspace_player``, then one ``SELECT``), so concurrent
    imports never raise duplicate-key errors. Returns ``player_id -> member.id``.
    """
    if not player_ids:
        return {}

    insert_stmt = (
        pg_insert(models.WorkspaceMember)
        .values(
            [
                {"workspace_id": workspace_id, "player_id": player_id}
                # Sorted for a deterministic insert order (avoids deadlocks
                # between concurrent bulk imports).
                for player_id in sorted(player_ids)
            ]
        )
        .on_conflict_do_nothing(constraint="uq_workspace_member_workspace_player")
    )
    await session.execute(insert_stmt)

    result = await session.execute(
        sa.select(models.WorkspaceMember.player_id, models.WorkspaceMember.id).where(
            models.WorkspaceMember.workspace_id == workspace_id,
            models.WorkspaceMember.player_id.in_(list(player_ids)),
        )
    )
    return dict(result.all())


def team_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    entities: list[_AbstractLoad] = []

    if "tournament" in in_entities:
        entities.append(utils.join_entity(child, models.Team.tournament))
    if "players" in in_entities:
        players_entities = utils.prepare_entities(in_entities, "players")
        players_entity = utils.join_entity(child, models.Team.players)
        entities.append(players_entity)
        # PlayerRead.user_id is a required field (resolved from
        # workspace_member.player_id, contract step iwrefac07), so
        # workspace_member itself must always be loaded here -- not just when
        # "user"/"workspace_member" is requested. The nested
        # workspace_member.player (+ further user sub-entities) stays gated
        # behind "user" since that's the expensive/optional part.
        workspace_member_entity = utils.join_entity(players_entity, models.Player.workspace_member)
        entities.append(workspace_member_entity)
        if "user" in players_entities:
            user_entity = utils.join_entity(workspace_member_entity, models.WorkspaceMember.player)
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

    # PlayerRead.user_id is a required field resolved from
    # workspace_member.player_id (contract step iwrefac07), so workspace_member
    # is always loaded here -- the nested .player (full user profile) stays
    # gated behind "user".
    workspace_member_entity = utils.join_entity(child, models.Player.workspace_member)
    entities.append(workspace_member_entity)
    if "user" in entities_in:
        entities.append(utils.join_entity(workspace_member_entity, models.WorkspaceMember.player))
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
    # Resolve the team via the normalized challonge_participant_mapping ->
    # challonge_source join instead of the deprecated challonge_team table.
    query = (
        sa.select(models.Team)
        .options(*team_entities(entities))
        .join(
            models.ChallongeParticipantMapping,
            models.ChallongeParticipantMapping.team_id == models.Team.id,
        )
        .join(
            models.ChallongeSource,
            models.ChallongeSource.id == models.ChallongeParticipantMapping.source_id,
        )
        .where(
            sa.and_(
                models.ChallongeSource.tournament_id == tournament_id,
                models.ChallongeParticipantMapping.challonge_participant_id == challonge_id,
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
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .options(*team_entities(entities))
        .where(
            sa.and_(
                models.WorkspaceMember.player_id.in_(players_ids),
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
                models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id),
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
        .where(
            sa.and_(
                models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id),
                models.Player.team_id == team_id,
            )
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().first()


async def get_player_by_user(
    session: AsyncSession, user_id: int, entities: list[str]
) -> typing.Sequence[models.Player]:
    query = (
        sa.select(models.Player)
        .where(sa.and_(models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id)))
        .options(*player_entities(entities))
    )
    result = await session.execute(query)
    return result.unique().scalars().all()


async def get_player_by_user_and_role(
    session: AsyncSession, user_id: int, role: enums.HeroClass, entities: list[str]
) -> typing.Sequence[models.Player]:
    query = (
        sa.select(models.Player)
        .options(*player_entities(entities))
        .where(
            sa.and_(
                models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id),
                models.Player.role == role,
            )
        )
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
    # NOTE (P5.2c): unreferenced anywhere in the codebase (no callers, no tests) and
    # has no session/tournament in scope to resolve workspace_member_id, so it cannot
    # be wired without a signature change. If this is ever revived as a real creation
    # site, it MUST set workspace_member_id (see create_player / create_player_sync
    # in this module for the resolution pattern) before it is safe to use.
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
    workspace_member_id = await _resolve_workspace_member_id(
        session,
        tournament_id=tournament.id,
        player_id=user.id,
    )
    player = models.Player(
        name=name,
        sub_role=normalize_sub_role(sub_role),
        rank=rank,
        role=role,
        tournament_id=tournament.id,
        team_id=team.id,
        is_substitution=is_substitution,
        related_player_id=related_player_id,
        is_newcomer=is_newcomer,
        is_newcomer_role=is_newcomer_role,
        workspace_member_id=workspace_member_id,
    )

    session.add(player)
    await session.commit()
    return player


def _resolve_workspace_member_id_sync(
    session: Session,
    *,
    tournament_id: int,
    player_id: int,
) -> int:
    """Sync counterpart of ``_resolve_workspace_member_id`` for callers on a sync ``Session``.

    Mirrors ``get_or_create_workspace_member``'s insert-or-select idempotency
    (``INSERT ... ON CONFLICT DO NOTHING`` then ``SELECT``) since that helper is
    async-only.
    """
    workspace_id = session.execute(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    ).scalar_one()

    insert_stmt = (
        pg_insert(models.WorkspaceMember)
        .values(workspace_id=workspace_id, player_id=player_id)
        .on_conflict_do_nothing(constraint="uq_workspace_member_workspace_player")
        .returning(models.WorkspaceMember.id)
    )
    member_id = session.execute(insert_stmt).scalar_one_or_none()
    if member_id is not None:
        session.flush()
        return member_id

    existing = session.execute(
        sa.select(models.WorkspaceMember.id).where(
            models.WorkspaceMember.workspace_id == workspace_id,
            models.WorkspaceMember.player_id == player_id,
        )
    ).scalar_one_or_none()
    if existing is None:
        raise RuntimeError(
            f"_resolve_workspace_member_id_sync: no row after ON CONFLICT DO NOTHING "
            f"(workspace_id={workspace_id}, player_id={player_id})"
        )
    return existing


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
    workspace_member_id = _resolve_workspace_member_id_sync(
        session,
        tournament_id=tournament.id,
        player_id=user.id,
    )
    player = models.Player(
        name=name,
        sub_role=normalize_sub_role(sub_role),
        rank=rank,
        role=role,
        tournament_id=tournament.id,
        team_id=team.id,
        is_substitution=is_substitution,
        related_player_id=related_player_id,
        is_newcomer=is_newcomer,
        is_newcomer_role=is_newcomer_role,
        workspace_member_id=workspace_member_id,
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
