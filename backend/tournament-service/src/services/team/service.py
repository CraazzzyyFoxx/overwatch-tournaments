import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.repository import PlayerRepository, TeamRepository
from shared.services.tournament.visibility import visible_tournament_ids_subquery
from src import models, schemas
from src.core import enums
from src.core.query_page import execute_page_with_total


class TeamService:
    def __init__(
        self,
        *,
        team_repo: TeamRepository = TeamRepository(),
        player_repo: PlayerRepository = PlayerRepository(),
    ) -> None:
        self.team_repo = team_repo
        self.player_repo = player_repo

    async def get(self, session: AsyncSession, team_id: int, entities: list[str]) -> models.Team | None:
        """
        Retrieves a `Team` model instance by its ID, optionally loading specified related entities.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            team_id: The ID of the team to retrieve.
            entities: A list of strings representing the names of related entities to load.

        Returns:
            A `Team` model instance if found, otherwise `None`.
        """
        return await self.team_repo.get(session, team_id, options=TeamRepository.team_entities(entities))

    async def get_by_name_and_tournament(
        self, session: AsyncSession, tournament_id: int, name: str, entities: list[str]
    ) -> models.Team | None:
        """
        Retrieves a `Team` model instance by its name and associated tournament ID, optionally loading specified related entities.

        Deliberately not ``TeamRepository.get_by_name_and_tournament``: that one is an
        exact-match lookup, while team names here are matched case-insensitively
        (Challonge and the registration flow both round-trip differently-cased names).

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            tournament_id: The ID of the tournament associated with the team.
            name: The name of the team (case-insensitive comparison).
            entities: A list of strings representing the names of related entities to load.

        Returns:
            A `Team` model instance if found, otherwise `None`.
        """
        query = (
            self.team_repo.select()
            .where(
                sa.and_(
                    sa.func.lower(models.Team.name) == name.lower(),
                    models.Team.tournament_id == tournament_id,
                )
            )
            .options(*TeamRepository.team_entities(entities))
        )
        result = await session.execute(query)
        return result.unique().scalars().first()

    async def get_by_tournament(
        self, session: AsyncSession, tournament: models.Tournament, entities: list[str]
    ) -> typing.Sequence[models.Team]:
        """
        Retrieves all `Team` model instances associated with a specific tournament, optionally loading specified related entities.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            tournament: The `Tournament` model instance or ID to filter teams by.
            entities: A list of strings representing the names of related entities to load.

        Returns:
            A sequence of `Team` model instances.
        """
        query = (
            self.team_repo.select()
            .filter_by(tournament_id=tournament.id)
            .options(*TeamRepository.team_entities(entities))
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def get_by_tournament_challonge_id(
        self, session: AsyncSession, tournament_id: int, challonge_id: int, entities: list[str]
    ) -> models.Team | None:
        """
        Retrieves a `Team` model instance by its associated tournament ID and Challonge ID, optionally loading specified related entities.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            tournament_id: The ID of the tournament associated with the team.
            challonge_id: The Challonge ID associated with the team.
            entities: A list of strings representing the names of related entities to load.

        Returns:
            A `Team` model instance if found, otherwise `None`.
        """
        query = (
            self.team_repo.select()
            .options(*TeamRepository.team_entities(entities))
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

    async def get_all(
        self,
        session: AsyncSession,
        params: schemas.TeamFilterParams,
        workspace_id: int | None = None,
    ) -> tuple[typing.Sequence[models.Team], int]:
        """
        Retrieves a paginated list of `Team` model instances based on filtering and sorting parameters, along with the total count of teams matching the criteria.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            params: An instance of `TeamFilterParams` containing filtering, sorting, and pagination parameters.
            workspace_id: An optional workspace ID to filter teams by their tournament's workspace.

        Returns:
            A tuple containing:
            1. A sequence of `Team` model instances.
            2. The total count of teams matching the filtering criteria.
        """
        query = self.team_repo.select().options(*TeamRepository.team_entities(params.entities))
        total_query = sa.select(sa.func.count(models.Team.id))
        if params.tournament_id:
            query = query.where(sa.and_(models.Team.tournament_id == params.tournament_id))
            total_query = total_query.where(sa.and_(models.Team.tournament_id == params.tournament_id))
        else:
            # Cross-tournament browse: exclude teams of hidden tournaments (issue #115).
            # A specific tournament_id is authorized upstream by assert_tournament_viewable.
            visible_ids = visible_tournament_ids_subquery(None)
            query = query.where(models.Team.tournament_id.in_(visible_ids))
            total_query = total_query.where(models.Team.tournament_id.in_(visible_ids))

        if workspace_id is not None:
            query = query.join(models.Tournament, models.Team.tournament_id == models.Tournament.id)
            total_query = total_query.join(models.Tournament, models.Team.tournament_id == models.Tournament.id)
            query = query.where(models.Tournament.workspace_id == workspace_id)
            total_query = total_query.where(models.Tournament.workspace_id == workspace_id)

        if params.search:
            name_match = models.Team.name.ilike(f"%{params.search}%")
            query = query.where(name_match)
            total_query = total_query.where(name_match)

        if params.sort == "group":
            query = (
                query.join(models.Team.standings)
                .join(models.Standing.stage_item)
                .where(models.StageItem.type == enums.StageItemType.GROUP)
                .order_by(params.apply_sort_field(models.StageItem.name))
            )
        elif params.sort == "placement":
            query = query.join(models.Team.standings).order_by(
                params.apply_sort_field(models.Standing.overall_position)
            )
        else:
            query = params.apply_pagination_sort(query, models.Team)
            return await execute_page_with_total(
                session,
                query,
                total_query,
                pk=models.Team.id,
                page=params.page,
                only_count=params.only_count,
            )
        result = await session.execute(query)
        total_result = await session.execute(total_query)
        return result.unique().scalars().all(), total_result.scalar_one()

    async def get_player(self, session: AsyncSession, player_id: int, entities: list[str]) -> models.Player | None:
        """
        Retrieves a `Player` model instance by its ID, optionally loading specified related entities.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            player_id: The ID of the player to retrieve.
            entities: A list of strings representing the names of related entities to load.

        Returns:
            A `Player` model instance if found, otherwise `None`.
        """
        return await self.player_repo.get(session, player_id, options=PlayerRepository.player_entities(entities))

    async def get_player_by_user_and_tournament(
        self, session: AsyncSession, user_id: int, tournament_id: int, entities: list[str]
    ) -> models.Player | None:
        """
        Retrieves a `Player` model instance by its associated user ID and tournament ID, optionally loading specified related entities.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            user_id: The ID of the user associated with the player.
            tournament_id: The ID of the tournament associated with the player.
            entities: A list of strings representing the names of related entities to load.

        Returns:
            A `Player` model instance if found, otherwise `None`.
        """
        return await self.player_repo.get_by_user_and_tournament(
            session,
            user_id=user_id,
            tournament_id=tournament_id,
            options=PlayerRepository.player_entities(entities),
        )

    async def get_player_all(
        self, session: AsyncSession, params: schemas.PlayerFilterParams
    ) -> tuple[typing.Sequence[models.Player], int]:
        """
        Retrieves a paginated list of `Player` model instances based on filtering and sorting parameters, along with the total count of players matching the criteria.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            params: An instance of `PlayerFilterParams` containing filtering, sorting, and pagination parameters.

        Returns:
            A tuple containing:
            1. A sequence of `Player` model instances.
            2. The total count of players matching the filtering criteria.
        """
        query = self.player_repo.select().options(*PlayerRepository.player_entities(params.entities))
        total_query = sa.select(sa.func.count(models.Player.id))
        if params.tournament_id:
            query = query.where(sa.and_(models.Player.tournament_id == params.tournament_id))
            total_query = total_query.where(sa.and_(models.Player.tournament_id == params.tournament_id))

        query = params.apply_pagination_sort(query, models.Player)
        result = await session.execute(query)
        total_result = await session.execute(total_query)
        return result.unique().scalars().all(), total_result.scalar_one()

    async def get_player_count_by_tournament(self, session: AsyncSession, tournament_id: int) -> int:
        """
        Retrieves the total count of `Player` model instances associated with a specific tournament.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            tournament_id: The ID of the tournament to count players for.

        Returns:
            The total count of players associated with the specified tournament.
        """
        return await self.player_repo.count(session, filters=[models.Player.tournament_id == tournament_id])

    async def get_player_count_by_tournament_bulk(
        self, session: AsyncSession, tournaments_ids: list[int]
    ) -> dict[int, int]:
        if not tournaments_ids:
            return {}
        query = (
            sa.select(models.Player.tournament_id, sa.func.count(models.Player.id))
            .where(models.Player.tournament_id.in_(tournaments_ids))
            .group_by(models.Player.tournament_id)
        )
        result = await session.execute(query)
        return {row[0]: row[1] for row in result.all()}

    async def get_team_count_by_tournament(self, session: AsyncSession, tournament_id: int) -> int:
        """Return the number of teams assigned to one tournament."""
        return await self.team_repo.count(session, filters=[models.Team.tournament_id == tournament_id])

    async def get_team_count_by_tournament_bulk(
        self, session: AsyncSession, tournaments_ids: list[int]
    ) -> dict[int, int]:
        """
        Retrieves the total count of `Team` model instances associated with a specific tournament.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            tournaments_ids: The ID of the tournament to count team for.

        Returns:
            The total count of players associated with the specified tournament.
        """
        if not tournaments_ids:
            return {}
        query = (
            sa.select(models.Team.tournament_id, sa.func.count(models.Team.id))
            .where(models.Team.tournament_id.in_(tournaments_ids))
            .group_by(models.Team.tournament_id)
        )
        result = await session.execute(query)
        return {row[0]: row[1] for row in result.all()}


team_service = TeamService()
