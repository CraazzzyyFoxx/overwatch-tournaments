import typing

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums, errors, pagination, utils
from shared.division_grid import DivisionGrid
from shared.services.cache_generations import versioned
from shared.services.division_grid.resolution import resolve_tournament_division
from src import schemas
from src.core import config
from src.core.workspace import get_division_grid
from src.services.tournament.cache_resources import TEAMS, tournament_generations
from src.services.tournament.flows import flows_service as tournament_flows_service
from src.services.user.flows import flows_service as user_flows_service
from src.services.user.flows import user_to_read

from .service import TeamService, team_service

#: The entities ``to_pydantic`` honours: all a cached read's key keeps of the client's list (``canonical_entities``).
READ_ENTITIES = frozenset({"tournament", "players", "captain", "placement", "group"})


def resolve_team_placement(team: models.Team) -> int | None:
    standings = getattr(team, "standings", None) or []
    positive_positions = [
        standing.overall_position for standing in standings if getattr(standing, "overall_position", 0) > 0
    ]
    if positive_positions:
        return min(positive_positions)
    return None


class TeamFlowsService:
    def __init__(self, *, teams: TeamService = team_service) -> None:
        self.teams = teams

    async def to_pydantic(
        self,
        session: AsyncSession,
        team: models.Team,
        entities: list[str],
        *,
        grid: DivisionGrid | None = None,
    ) -> schemas.TeamRead:
        """Convert a team to ``TeamRead`` with the requested ``entities`` (e.g. tournament, players, captain)."""
        tournament: schemas.TournamentRead | None = None
        players_read: list[schemas.PlayerRead] = []
        captain: schemas.UserRead | None = None
        placement: int | None = None
        group: schemas.TeamGroupRead | None = None

        if "tournament" in entities:
            tournament = await tournament_flows_service.to_pydantic(session, team.tournament, entities=[])
        if "players" in entities:
            if grid is None:
                grid = await get_division_grid(session, None, tournament_id=team.tournament_id)
            players_entities = utils.prepare_entities(entities, "players")
            if "tournament" in players_entities or "team" in players_entities:
                players_read = [
                    await self.to_pydantic_player(session, player, players_entities, grid=grid)
                    for player in team.players
                ]
            else:
                players_read = [self.player_to_read(player, players_entities, grid=grid) for player in team.players]
        # ``Team.captain_id`` is nullable in practice: ``SET NULL`` on the captain's player
        # row, and a scrim room's away side has no captain until someone claims it.
        if "captain" in entities and team.captain is not None:
            captain = await user_flows_service.to_pydantic(
                session, team.captain, utils.prepare_entities(entities, "captain")
            )
        if "placement" in entities:
            placement = resolve_team_placement(team)
        if "group" in entities:
            for standing in team.standings:
                item = standing.stage_item
                if item is not None and item.type == enums.StageItemType.GROUP:
                    group = schemas.TeamGroupRead(id=item.id, name=item.name)
                    break

        return schemas.TeamRead(
            id=team.id,
            name=team.name,
            image_url=team.image_url,
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

    def player_to_read(
        self,
        player: models.Player,
        entities: list[str],
        *,
        grid: DivisionGrid,
        tournament: schemas.TournamentRead | None = None,
        team: schemas.TeamRead | None = None,
    ) -> schemas.PlayerRead:
        user: schemas.UserRead | None = None
        if "user" in entities:
            user_entities = [e.replace("user.", "") for e in entities if e.startswith("user.")]
            user = user_to_read(player.workspace_member.player, user_entities)

        player_dict = player.to_dict()
        # PlayerRead.user_id comes from workspace_member.player_id: workspace_member_id is
        # NOT NULL and team_entities/player_entities always load it, whatever the entities.
        player_dict["user_id"] = player.workspace_member.player_id
        player_dict["role"] = player.role_ref

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

    async def to_pydantic_player(
        self, session: AsyncSession, player: models.Player, entities: list[str], *, grid: DivisionGrid
    ) -> schemas.PlayerRead:
        """Converts a Player model instance to PlayerRead, including related entities."""
        tournament: schemas.TournamentRead | None = None
        team: schemas.TeamRead | None = None
        if "tournament" in entities:
            tournament = await tournament_flows_service.to_pydantic(session, player.tournament, entities=[])
        if "team" in entities:
            team = await self.to_pydantic(session, player.team, entities=[])
        return self.player_to_read(player, entities, grid=grid, tournament=tournament, team=team)

    async def get(self, session: AsyncSession, id: int, entities: list[str]) -> models.Team:
        """Return the team by id with ``entities`` loaded; 404 when missing."""
        team = await self.teams.get(session, id, entities)
        if not team:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg="Team with id {id} not found.")],
            )
        return team

    async def get_read(self, session: AsyncSession, id: int, entities: list[str]) -> schemas.TeamRead:
        """Return the team by id as ``TeamRead``; 404 when missing."""
        team = await self.get(session, id, entities)
        return await self.to_pydantic(session, team, entities)

    async def get_by_name_and_tournament(
        self, session: AsyncSession, tournament_id: int, name: str, entities: list[str]
    ) -> models.Team:
        """Return the team by name within the tournament; 404 when missing."""
        team = await self.teams.get_by_name_and_tournament(session, tournament_id, name, entities)
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
        self, session: AsyncSession, tournament_id: int, challonge_id: int, entities: list[str]
    ) -> models.Team:
        """Return the team by Challonge id within the tournament; 404 when missing."""
        team = await self.teams.get_by_tournament_challonge_id(session, tournament_id, challonge_id, entities)
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
        self, session: AsyncSession, user_id: int, tournament_id: int, entities: list[str]
    ) -> models.Player:
        """Return the user's player in the tournament; 404 when missing."""
        player = await self.teams.get_player_by_user_and_tournament(session, user_id, tournament_id, entities)
        if not player:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[
                    errors.ApiExc(
                        code="not_found",
                        msg=f"Player with user [id={user_id}] not found in tournament [id={tournament_id}].",
                    )
                ],
            )

        return player

    async def get_player(self, session: AsyncSession, player_id: int, entities: list[str]) -> models.Player | None:
        """Return the player by id, or None."""
        return await self.teams.get_player(session, player_id, entities)

    async def to_pydantic_many(
        self, session: AsyncSession, teams: typing.Iterable[models.Team], entities: list[str]
    ) -> list[schemas.TeamRead]:
        """``to_pydantic`` for each team, resolving the division grid once per tournament rather than once per team
        (one SQL statement and two Redis round trips each)."""
        grids: dict[int, DivisionGrid] = {}
        reads = []
        for team in teams:
            if "players" in entities and team.tournament_id not in grids:
                grids[team.tournament_id] = await get_division_grid(session, None, tournament_id=team.tournament_id)
            reads.append(await self.to_pydantic(session, team, entities, grid=grids.get(team.tournament_id)))
        return reads

    # Values are the dumped wire dict (``v3``), not a pickled ``Paginated[TeamRead]``: Redis keeps values across a
    # deploy and cashews returns them unvalidated, so a wire change must bump the version.
    @versioned(
        generations=tournament_generations("{params.tournament_id}", TEAMS),
        ttl=config.settings.teams_cache_ttl,
        key="teams:v3:{workspace_id}:{params.tournament_id}:{params.page}:{params.per_page}:{params.sort}:{params.order}:{params.entities}:{params.search}:{params.discipline}:{params.only_count}",
        prefix="fastapi:",
    )
    async def get_all(
        self,
        session: AsyncSession,
        params: schemas.TeamFilterParams,
        workspace_id: int | None = None,
    ) -> dict[str, typing.Any]:
        """A page of teams as ``Paginated[TeamRead]``'s wire dict (``exclude_none``), optionally scoped to one
        workspace. A ``tournament_id`` is the caller's to gate: this neither loads nor 404s it. ``params.entities``
        is the key's too: pass them through ``canonical_entities(..., READ_ENTITIES)``."""
        results, total = await self.teams.get_all(session, params, workspace_id=workspace_id)
        return pagination.Paginated(
            results=await self.to_pydantic_many(session, results, params.entities),
            total=total,
            per_page=params.per_page,
            page=params.page,
        ).model_dump(mode="json", exclude_none=True)


flows_service = TeamFlowsService()
