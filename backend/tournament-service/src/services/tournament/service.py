import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared.repository import TournamentRepository
from src import models, schemas
from src.core import enums, pagination, utils
from src.core.query_page import execute_page_with_total

__all__ = (
    "TournamentService",
    "tournament_entities",
    "tournament_service",
)


def _is_desc(order: typing.Any) -> bool:
    """``PaginationSortParams.order`` is either the enum or the bare literal."""
    return order == pagination.SortOrder.DESC or order == "desc"


def tournament_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """
    Constructs a list of SQLAlchemy load options for querying related entities of a `Tournament` model.

    Args:
        in_entities: A list of strings representing the names of related entities to load.
        child: An optional SQLAlchemy relationship or join entity to chain the load options.

    Returns:
        A list of SQLAlchemy load options (`_AbstractLoad`) for the specified entities.
    """
    entities = []
    if "stages" in in_entities:
        stage_entity = child.selectinload(models.Tournament.stages) if child else selectinload(models.Tournament.stages)
        entities.append(stage_entity)
    if "division_grid_version" in in_entities:
        entities.append(utils.join_entity(child, models.Tournament.division_grid_version))
    return entities


class TournamentService:
    def __init__(self, *, tournament_repo: TournamentRepository = TournamentRepository()) -> None:
        self.tournament_repo = tournament_repo

    async def get(self, session: AsyncSession, id: int, entities: list[str]) -> models.Tournament | None:
        """
        Retrieves a `Tournament` model instance by its ID, optionally including related entities.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            id: The ID of the tournament to retrieve.
            entities: A list of strings representing the names of related entities to include.

        Returns:
            A `Tournament` model instance if found, otherwise `None`.
        """
        return await self.tournament_repo.get(session, id, options=tournament_entities(entities))

    async def get_all(
        self,
        session: AsyncSession,
        params: schemas.TournamentPaginationSortSearchParams,
        *,
        visibility: sa.ColumnElement[bool] | None = None,
    ) -> tuple[typing.Sequence[models.Tournament], int]:
        """
        Retrieves a paginated list of `Tournament` model instances based on filtering and sorting parameters.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            params: An instance of `SearchPaginationParams` containing pagination, sorting, and filtering parameters.

        Returns:
            A tuple containing:
            1. A sequence of `Tournament` model instances.
            2. The total count of tournaments matching the filtering criteria.
        """
        query = self.tournament_repo.select().options(*tournament_entities(params.entities))
        total_query = sa.select(sa.func.count(models.Tournament.id))
        if params.sort == "participants_count":
            # Not a column: the count lives in `player`, so `apply_pagination_sort`
            # (which resolves the sort through `Tournament.depth_get_column`) cannot
            # express it. Same grouped-subquery shape as `get_history_tournaments`.
            players_sq = (
                sa.select(
                    models.Player.tournament_id,
                    sa.func.count(models.Player.id).label("n"),
                )
                .group_by(models.Player.tournament_id)
                .subquery()
            )
            n = sa.func.coalesce(players_sq.c.n, 0)
            query = query.join(players_sq, players_sq.c.tournament_id == models.Tournament.id, isouter=True)
            # coalesce, not the raw column: the outer join leaves NULL for a
            # tournament with no players, and NULL ordering in Postgres puts those
            # rows FIRST on `desc()` — the exact opposite of "most participants".
            query = query.order_by(n.desc() if _is_desc(params.order) else n.asc())
            query = params.apply_pagination(query)
        else:
            query = params.apply_pagination_sort(query, models.Tournament)
        query = params.apply_search(query, models.Tournament)
        total_query = params.apply_search(total_query, models.Tournament)

        if params.is_league is not None:
            query = query.where(models.Tournament.is_league.is_(params.is_league))
            total_query = total_query.where(models.Tournament.is_league.is_(params.is_league))

        if params.workspace_id is not None:
            query = query.where(models.Tournament.workspace_id == params.workspace_id)
            total_query = total_query.where(models.Tournament.workspace_id == params.workspace_id)

        if params.status is not None:
            # Applied to the count query too, like every other filter here: a
            # filter missing from the total makes `total` describe a different set
            # than `results`, and the client's "load more" decision is derived
            # from exactly that comparison.
            query = query.where(models.Tournament.status == params.status)
            total_query = total_query.where(models.Tournament.status == params.status)

        # Hidden-tournament visibility filter (issue #115): applied to BOTH the page
        # and count query so hidden tournaments never leak into results OR totals.
        if visibility is not None:
            query = query.where(visibility)
            total_query = total_query.where(visibility)

        # Unconditional tie-breaker. Neither `start_date` nor the participant count
        # is unique, and OFFSET/LIMIT over a non-unique ORDER BY is free to return
        # a row on page 2 that already appeared on page 1 (and drop another
        # entirely). Invisible while the client fetched everything in one
        # `per_page=-1` request; guaranteed to bite as soon as it pages.
        query = query.order_by(models.Tournament.id.desc())

        return await execute_page_with_total(
            session,
            query,
            total_query,
            pk=models.Tournament.id,
            page=params.page,
            only_count=params.only_count,
        )

    async def get_history_tournaments(
        self,
        session: AsyncSession,
        workspace_id: int | None = None,
    ) -> typing.Sequence[tuple[models.Tournament, int, float, float]]:
        """
        Retrieves historical statistics for tournaments, including player count, average SR, and average closeness.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.

        Returns:
            A sequence of tuples containing:
            1. A `Tournament` model instance.
            2. The number of players in the tournament.
            3. The average SR of teams in the tournament.
            4. The average closeness of encounters in the tournament.
        """
        # One pass with grouped subqueries LEFT JOINed on tournament_id instead of
        # three correlated scalar subqueries evaluated per tournament row.
        players_sq = (
            sa.select(
                models.Player.tournament_id,
                sa.func.count(models.Player.id).label("players_count"),
            )
            .group_by(models.Player.tournament_id)
            .subquery()
        )

        teams_sq = (
            sa.select(
                models.Team.tournament_id,
                sa.func.avg(models.Team.avg_sr).label("avg_sr"),
            )
            .group_by(models.Team.tournament_id)
            .subquery()
        )

        encounters_sq = (
            sa.select(
                models.Encounter.tournament_id,
                sa.func.avg(models.Encounter.closeness).label("avg_closeness"),
            )
            .group_by(models.Encounter.tournament_id)
            .subquery()
        )

        query = (
            sa.select(
                models.Tournament,
                # The correlated count() form returned 0 for tournaments without
                # players; LEFT JOIN yields NULL there, so coalesce to keep parity.
                sa.func.coalesce(players_sq.c.players_count, 0),
                teams_sq.c.avg_sr,
                encounters_sq.c.avg_closeness,
            )
            .join(players_sq, players_sq.c.tournament_id == models.Tournament.id, isouter=True)
            .join(teams_sq, teams_sq.c.tournament_id == models.Tournament.id, isouter=True)
            .join(encounters_sq, encounters_sq.c.tournament_id == models.Tournament.id, isouter=True)
            .where(models.Tournament.is_league.is_(False), models.Tournament.is_hidden.is_(False))
            .order_by(models.Tournament.start_date.nulls_last(), models.Tournament.id)
        )
        if workspace_id is not None:
            query = query.where(models.Tournament.workspace_id == workspace_id)
        result = await session.execute(query)
        return result.all()  # type: ignore

    async def get_avg_div_tournaments(
        self,
        session: AsyncSession,
        workspace_id: int | None = None,
    ) -> typing.Sequence[tuple[models.Tournament, enums.HeroClass, int, int]]:
        """
        Retrieves aggregated player rank data for computing per-tournament division averages.

        Returns (tournament, role, rank, players_count) rows — one row per distinct
        (tournament, role, rank) combination with the number of players holding that
        rank, so thousands of per-player rows collapse into a small rank histogram.
        Division computation and normalization to the target grid is done in the flow
        layer using DivisionGridNormalizer so that each tournament's own
        division_grid_version is respected.

        Returns:
            A sequence of tuples containing:
            1. A `Tournament` model instance (with division_grid_version_id available).
            2. The role (e.g., tank, damage, support).
            3. The player's raw rank.
            4. The number of players with that (role, rank) in the tournament.
        """
        query = (
            sa.select(
                models.Tournament,
                models.Player.role,
                models.Player.rank,
                sa.func.count(models.Player.id).label("players_count"),
            )
            .where(
                models.Player.tournament_id == models.Tournament.id,
                models.Tournament.is_league.is_(False),
                models.Tournament.is_hidden.is_(False),
            )
            # Grouping by the Tournament PK lets Postgres project the whole
            # tournament row (functional dependency).
            .group_by(models.Tournament.id, models.Player.role, models.Player.rank)
            .order_by(models.Tournament.start_date.nulls_last(), models.Tournament.id)
        )
        if workspace_id is not None:
            query = query.where(models.Tournament.workspace_id == workspace_id)
        result = await session.execute(query)
        return result.all()  # type: ignore

    async def get_tournaments_overall(
        self, session: AsyncSession, workspace_id: int | None = None
    ) -> tuple[int, int, int, int]:
        """
        Retrieves overall statistics for tournaments, including counts of tournaments, teams, players, and champions.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.

        Returns:
            A tuple containing:
            1. The total number of tournaments.
            2. The total number of teams.
            3. The total number of players.
            4. The total number of champions.
        """
        # Hidden tournaments (issue #115) never contribute to public overall stats.
        ws_filters = [models.Tournament.is_hidden.is_(False)]
        if workspace_id is not None:
            ws_filters.append(models.Tournament.workspace_id == workspace_id)

        tournaments_count_query = sa.select(sa.func.count(models.Tournament.id)).where(
            models.Tournament.is_league.is_(False), *ws_filters
        )

        teams_count_query = (
            sa.select(sa.func.count(models.Team.id))
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(models.Tournament.is_league.is_(False), *ws_filters)
        )

        players_count_query = (
            sa.select(sa.func.count(sa.distinct(models.WorkspaceMember.player_id)))
            .select_from(models.Player)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(models.Tournament.is_league.is_(False), *ws_filters)
        )

        champions_count_query = (
            sa.select(sa.func.count(models.WorkspaceMember.player_id.distinct()))
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.Standing, models.Standing.team_id == models.Player.team_id)
            .outerjoin(
                models.StageItem,
                models.StageItem.id == models.Standing.stage_item_id,
            )
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(
                sa.and_(
                    models.Standing.overall_position == 1,
                    sa.or_(
                        models.Standing.stage_item_id.is_(None),
                        models.StageItem.type != enums.StageItemType.GROUP,
                    ),
                    models.Player.is_substitution.is_(False),
                    models.Tournament.is_league.is_(False),
                    *ws_filters,
                )
            )
        )
        tournaments_count_result = await session.execute(tournaments_count_query)
        teams_count_result = await session.execute(teams_count_query)
        players_count_result = await session.execute(players_count_query)
        champions_count_result = await session.execute(champions_count_query)
        return (
            tournaments_count_result.scalar_one(),
            teams_count_result.scalar_one(),
            players_count_result.scalar_one(),
            champions_count_result.scalar_one(),
        )

    async def get_bulk_tournament(
        self, session: AsyncSession, tournaments_ids: list[int], entities: list[str]
    ) -> typing.Sequence[models.Tournament]:
        """
        Retrieves a list of `Tournament` model instances by their IDs.

        Args:
            session: An SQLAlchemy `AsyncSession` for database interaction.
            tournaments_ids: A list of tournament IDs to retrieve.
            entities: A list of strings representing the names of related entities to include.

        Returns:
            A sequence of `Tournament` model instances.
        """
        return await self.tournament_repo.bulk_get(session, tournaments_ids, options=tournament_entities(entities))


tournament_service = TournamentService()
