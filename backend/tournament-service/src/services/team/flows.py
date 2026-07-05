from cashews import cache
from shared.division_grid import DivisionGrid
from shared.services.division_grid_resolution import resolve_tournament_division
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config, errors, pagination, utils
from src.core.workspace import get_division_grid
from src.services.tournament import flows as tournament_flows
from src.services.user import flows as user_flows

from . import service


def resolve_team_placement(team: models.Team) -> int | None:
    standings = getattr(team, "standings", None) or []
    positive_positions = [
        standing.overall_position for standing in standings if getattr(standing, "overall_position", 0) > 0
    ]
    if positive_positions:
        return min(positive_positions)
    return None


async def to_pydantic(
    session: AsyncSession,
    team: models.Team,
    entities: list[str],
    *,
    grid: DivisionGrid | None = None,
) -> schemas.TeamRead:
    """
    Converts a Team model instance to a Pydantic schema (TeamRead), including related entities.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        team (models.Team): The Team model instance to convert.
        entities (list[str]): A list of related entities to include (e.g., ["tournament", "players", "captain"]).

    Returns:
        schemas.TeamRead: The Pydantic schema representing the team.
    """
    tournament: schemas.TournamentRead | None = None
    players_read: list[schemas.PlayerRead] = []
    captain: schemas.UserRead | None = None
    placement: int | None = None
    group: schemas.TournamentGroupRead | None = None

    if "tournament" in entities:
        tournament = await tournament_flows.to_pydantic(session, team.tournament, entities=[])
    if "players" in entities:
        if grid is None:
            grid = await get_division_grid(session, None, tournament_id=team.tournament_id)
        players_entities = utils.prepare_entities(entities, "players")
        players_read = [
            await to_pydantic_player(session, player, players_entities, grid=grid) for player in team.players
        ]
    if "captain" in entities:
        captain = await user_flows.to_pydantic(session, team.captain, utils.prepare_entities(entities, "captain"))
    if "placement" in entities:
        placement = resolve_team_placement(team)
    if "group" in entities:
        groups = [
            standing.group for standing in team.standings if standing.group is not None and standing.group.is_groups
        ]
        if groups:
            group = await tournament_flows.to_pydantic_group(session, groups[0], [])

    return schemas.TeamRead(
        id=team.id,
        name=team.name,
        avg_sr=team.avg_sr,
        total_sr=team.total_sr,
        captain_id=team.captain_id,
        tournament_id=team.tournament_id,
        tournament=tournament,
        players=players_read,
        captain=captain,
        placement=placement,
        group=group,
    )


async def to_pydantic_player(
    session: AsyncSession, player: models.Player, entities: list[str], *, grid: DivisionGrid
) -> schemas.PlayerRead:
    """
    Converts a Player model instance to a Pydantic schema (PlayerRead), including related entities.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        player (models.Player): The Player model instance to convert.
        entities (list[str]): A list of related entities to include (e.g., ["user", "tournament", "team"]).

    Returns:
        schemas.PlayerRead: The Pydantic schema representing the player.
    """
    user: schemas.UserRead | None = None
    tournament: schemas.TournamentRead | None = None
    team: schemas.TeamRead | None = None

    if "user" in entities:
        # workspace_member_id is NOT NULL (contract step, iwrefac07) and is always
        # eager-loaded regardless of the "user" entity flag (see workspace_member_id
        # dereference below), so the old "workspace_member is not None" guard here
        # was dead — dropped to match app-service's _mappers.py.
        user_entities = [e.replace("user.", "") for e in entities if e.startswith("user.")]
        user = await user_flows.to_pydantic(session, player.workspace_member.player, user_entities)
    if "tournament" in entities:
        tournament = await tournament_flows.to_pydantic(session, player.tournament, entities=[])
    if "team" in entities:
        team = await to_pydantic(session, player.team, entities=[])

    player_dict = player.to_dict()
    # Player.user_id was dropped in the contract step (iwrefac07); PlayerRead.user_id
    # is resolved from workspace_member.player_id instead (workspace_member is always
    # loaded by team_entities/player_entities regardless of the "user" entity flag).
    player_dict["user_id"] = player.workspace_member.player_id

    return schemas.PlayerRead(
        **player_dict,
        division=resolve_tournament_division(
            player.rank,
            tournament_grid=grid,
        ),
        user=user,
        tournament=tournament,
        team=team,
    )


async def get(session: AsyncSession, id: int, entities: list[str]) -> models.Team:
    """
    Retrieves a team by its ID.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        id (int): The ID of the team to retrieve.
        entities (list[str]): A list of related entities to load (e.g., ["tournament", "players"]).

    Returns:
        models.Team: The Team object if found.

    Raises:
        errors.ApiHTTPException: If the team is not found.
    """
    team = await service.get(session, id, entities)
    if not team:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[errors.ApiExc(code="not_found", msg="Team with id {id} not found.")],
        )
    return team


async def get_read(session: AsyncSession, id: int, entities: list[str]) -> schemas.TeamRead:
    """
    Retrieves a team by its ID and converts it to a Pydantic schema.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        id (int): The ID of the team to retrieve.
        entities (list[str]): A list of related entities to include (e.g., ["tournament", "players"]).

    Returns:
        schemas.TeamRead: The Pydantic schema representing the team.
    """
    team = await get(session, id, entities)
    return await to_pydantic(session, team, entities)


@cache(ttl=config.settings.teams_cache_ttl, key="teams_by_tournament:{tournament_id}:{entities}", prefix="fastapi:")
async def get_by_tournament_read(
    session: AsyncSession, tournament_id: int, entities: list[str]
) -> list[schemas.TeamRead]:
    """
    Retrieves all teams for a specific tournament and converts them to Pydantic schemas.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        tournament_id (int): The ID of the tournament.
        entities (list[str]): A list of related entities to include (e.g., ["tournament", "players"]).

    Returns:
        list[schemas.TeamRead]: A list of Pydantic schemas representing the teams.
    """
    tournament = await tournament_flows.get(session, tournament_id, [])
    teams = await service.get_by_tournament(session, tournament=tournament, entities=entities)
    grid = None
    if "players" in entities:
        grid = await get_division_grid(session, None, tournament_id=tournament_id)
    return [await to_pydantic(session, team, entities=entities, grid=grid) for team in teams]


async def get_by_name_and_tournament(
    session: AsyncSession, tournament_id: int, name: str, entities: list[str]
) -> models.Team:
    """
    Retrieves a team by its name and associated tournament.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        tournament_id (int): The ID of the tournament.
        name (str): The name of the team to retrieve.
        entities (list[str]): A list of related entities to load (e.g., ["tournament", "players"]).

    Returns:
        models.Team: The Team object if found.

    Raises:
        errors.ApiHTTPException: If the team is not found.
    """
    team = await service.get_by_name_and_tournament(session, tournament_id, name, entities)
    if not team:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Team with name {name} in tournament {tournament_id} not found.",
                )
            ],
        )
    return team


async def get_by_tournament_challonge_id(
    session: AsyncSession, tournament_id: int, challonge_id: int, entities: list[str]
) -> models.Team:
    """
    Retrieves a team by its Challonge ID and associated tournament.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        tournament_id (int): The ID of the tournament.
        challonge_id (int): The Challonge ID of the team to retrieve.
        entities (list[str]): A list of related entities to load (e.g., ["tournament", "players"]).

    Returns:
        models.Team: The Team object if found.

    Raises:
        errors.ApiHTTPException: If the team is not found.
    """
    team = await service.get_by_tournament_challonge_id(session, tournament_id, challonge_id, entities)
    if not team:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Team with challonge_id {challonge_id} in tournament {tournament_id} not found.",
                )
            ],
        )
    return team


async def get_player_by_user_and_tournament(
    session: AsyncSession, user_id: int, tournament_id: int, entities: list[str]
) -> models.Player:
    """
    Retrieves a player by their user ID and associated tournament.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        user_id (int): The ID of the user.
        tournament_id (int): The ID of the tournament.
        entities (list[str]): A list of related entities to load (e.g., ["user", "team"]).

    Returns:
        models.Player: The Player object if found.

    Raises:
        errors.ApiHTTPException: If the player is not found.
    """
    player = await service.get_player_by_user_and_tournament(session, user_id, tournament_id, entities)
    if not player:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Player with user [id={user_id}] not found in tournament [number={tournament_id}].",
                )
            ],
        )

    return player


async def get_player(session: AsyncSession, player_id: int, entities: list[str]) -> models.Player | None:
    """
    Retrieves a player by their ID.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        player_id (int): The ID of the player to retrieve.
        entities (list[str]): A list of related entities to load (e.g., ["user", "team"]).

    Returns:
        models.Player: The Player object if found.
    """
    return await service.get_player(session, player_id, entities)


@cache(ttl=config.settings.teams_cache_ttl, key="teams:{workspace_id}:{params.tournament_id}:{params.page}:{params.per_page}:{params.sort}:{params.order}:{params.entities}", prefix="fastapi:")
async def get_all(
    session: AsyncSession,
    params: schemas.TeamFilterParams,
    workspace_id: int | None = None,
) -> pagination.Paginated[schemas.TeamRead]:
    """
    Retrieves a paginated list of teams based on filter parameters.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        params (schemas.TeamFilterParams): Filter, pagination, and sorting parameters.
        workspace_id (int | None): Optional workspace ID to filter teams by.

    Returns:
        pagination.Paginated[schemas.TeamRead]: A paginated list of Pydantic schemas representing the teams.
    """
    if params.tournament_id:
        await tournament_flows.get(session, params.tournament_id, [])

    results, total = await service.get_all(session, params, workspace_id=workspace_id)
    grids = {}
    results_pydantic = []
    for result in results:
        grid = None
        if "players" in params.entities:
            t_id = result.tournament_id
            if t_id not in grids:
                grids[t_id] = await get_division_grid(session, None, tournament_id=t_id)
            grid = grids[t_id]
        results_pydantic.append(await to_pydantic(session, result, entities=params.entities, grid=grid))

    return pagination.Paginated(
        results=results_pydantic,
        total=total,
        per_page=params.per_page,
        page=params.page,
    )
