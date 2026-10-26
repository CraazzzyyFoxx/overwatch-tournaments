import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core import enums, pagination, utils
from shared.repository import TournamentRepository
from shared.services.tournament.visibility import completed_encounters_clauses, visible_tournaments_predicate
from src import schemas
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
    """Loader options for a tournament's requested relations; ``child`` chains them under a parent load.

    The grid version is ``lazy="selectin"`` on the model (two statements, tiers included, per load), so a read
    that did not ask for it (``division_grid_version`` or a nested ``division_grid_version.*``, as ``to_pydantic``
    reads it) raises on access instead of paying for it.
    """
    entities = []
    if "stages" in in_entities:
        stage_entity = child.selectinload(models.Tournament.stages) if child else selectinload(models.Tournament.stages)
        entities.append(stage_entity)
    if any(entity.partition(".")[0] == "division_grid_version" for entity in in_entities):
        entities.append(utils.join_entity(child, models.Tournament.division_grid_version))
    else:
        entities.append(
            child.raiseload(models.Tournament.division_grid_version)
            if child
            else raiseload(models.Tournament.division_grid_version)
        )
    return entities


class TournamentService:
    def __init__(self, *, tournament_repo: TournamentRepository = TournamentRepository()) -> None:
        self.tournament_repo = tournament_repo

    async def get(self, session: AsyncSession, id: int, entities: list[str]) -> models.Tournament | None:
        """Return the tournament by id with ``entities`` loaded, or None."""
        return await self.tournament_repo.get(session, id, options=tournament_entities(entities))

    async def get_all(
        self,
        session: AsyncSession,
        params: schemas.TournamentPaginationSortSearchParams,
        *,
        visibility: sa.ColumnElement[bool] | None = None,
    ) -> tuple[typing.Sequence[models.Tournament], int]:
        """Return one page of tournaments and the total matching count; ``visibility`` filters both."""
        query = self.tournament_repo.select().options(*tournament_entities(params.entities))
        total_query = sa.select(sa.func.count(models.Tournament.id))
        if params.sort == "participants_count":
            # Not a column: the count lives in `player`, so `apply_pagination_sort`
            # (which resolves the sort through `Tournament.depth_get_column`) cannot
            # express it.
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

        if params.discipline is not None:
            query = query.where(models.Tournament.discipline == params.discipline)
            total_query = total_query.where(models.Tournament.discipline == params.discipline)

        if params.status:
            # Applied to the count query too, like every other filter here: a
            # filter missing from the total makes `total` describe a different set
            # than `results`, and the client's "load more" decision is derived
            # from exactly that comparison.
            query = query.where(models.Tournament.status.in_(params.status))
            total_query = total_query.where(models.Tournament.status.in_(params.status))

        # Hidden-tournament visibility filter: applied to BOTH the page and count
        # query so hidden tournaments never leak into results OR totals.
        if visibility is not None:
            query = query.where(visibility)
            total_query = total_query.where(visibility)

        # Unconditional tie-breaker. Neither `start_date` nor the participant count
        # is unique, and OFFSET/LIMIT over a non-unique ORDER BY is free to return
        # a row on page 2 that already appeared on page 1 (and drop another entirely).
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
        """Return (tournament, players_count, avg team SR, avg encounter closeness) per non-league tournament."""
        # Grouped subqueries LEFT JOINed on tournament_id: one pass, not a
        # correlated subquery per tournament row.
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
                # LEFT JOIN yields NULL for a tournament without players; report 0.
                sa.func.coalesce(players_sq.c.players_count, 0),
                teams_sq.c.avg_sr,
                encounters_sq.c.avg_closeness,
            )
            .join(players_sq, players_sq.c.tournament_id == models.Tournament.id, isouter=True)
            .join(teams_sq, teams_sq.c.tournament_id == models.Tournament.id, isouter=True)
            .join(encounters_sq, encounters_sq.c.tournament_id == models.Tournament.id, isouter=True)
            .where(models.Tournament.is_league.is_(False), visible_tournaments_predicate(None))
            .order_by(models.Tournament.start_date.nulls_last(), models.Tournament.id)
        )
        if workspace_id is not None:
            query = query.where(models.Tournament.workspace_id == workspace_id)
        result = await session.execute(query)
        return result.all()  # type: ignore

    async def get_avg_div_tournaments(
        self,
        session: AsyncSession,
        discipline: str,
        workspace_id: int | None = None,
    ) -> typing.Sequence[tuple[models.Tournament, str | None, int, int]]:
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
            2. The top-level role code on the game's rated dimension (None for an open slot).
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
                # An unranked player has no division to average.
                models.Player.rank.is_not(None),
                models.Tournament.is_league.is_(False),
                visible_tournaments_predicate(None),
                models.Tournament.discipline == discipline,
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
    ) -> schemas.OverallStatistics:
        """Return tournament/team/player/champion counts and played volume (encounters, maps, days, hours).

        ``workspace_id`` restricts every count to one workspace; None means the platform. Every count is over the
        tournaments an anonymous viewer may see, leagues included: the set ``/tournaments`` lists and
        ``/encounters`` counts, so the platform totals never disagree with them.
        """
        ws_filter = [models.Tournament.workspace_id == workspace_id] if workspace_id is not None else []
        tournament_scope = [visible_tournaments_predicate(None), *ws_filter]

        tournaments_count_query = sa.select(sa.func.count(models.Tournament.id)).where(*tournament_scope)

        teams_count_query = (
            sa.select(sa.func.count(models.Team.id))
            .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
            .where(*tournament_scope)
        )

        players_count_query = (
            sa.select(sa.func.count(sa.distinct(models.WorkspaceMember.player_id)))
            .select_from(models.Player)
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .where(*tournament_scope)
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
                    *tournament_scope,
                )
            )
        )

        # Played volume. ``encounters`` is the shared public "completed encounters" definition: the number the
        # ``/encounters`` hero states.
        encounters_count_query = (
            sa.select(sa.func.count(models.Encounter.id))
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(*completed_encounters_clauses(), *ws_filter)
        )

        # Generic played volume includes every discipline owned by the tournament.
        maps_and_time_query = (
            sa.select(
                sa.func.count(models.StatsMatch.id),
                sa.func.coalesce(sa.func.sum(models.StatsMatch.duration_s), 0.0),
            )
            .select_from(models.StatsMatch)
            .join(
                models.Encounter,
                sa.and_(
                    models.Encounter.id == models.StatsMatch.encounter_id,
                    models.Encounter.workspace_id == models.StatsMatch.workspace_id,
                    models.Encounter.discipline == models.StatsMatch.discipline,
                ),
            )
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .where(*tournament_scope)
        )

        # Calendar days the tournaments COVER, not the sum of their lengths: two
        # tournaments running the same weekend are three days, not six. Expanding
        # each [start, end] range to its dates and counting the distinct union is
        # what makes the overlap collapse.
        tournament_days = (
            sa.select(
                sa.cast(
                    sa.func.generate_series(
                        sa.cast(models.Tournament.start_date, sa.Date),
                        sa.cast(models.Tournament.end_date, sa.Date),
                        sa.text("interval '1 day'"),
                    ),
                    sa.Date,
                ).label("day")
            )
            .where(
                models.Tournament.start_date.isnot(None),
                models.Tournament.end_date.isnot(None),
                *tournament_scope,
            )
            .subquery()
        )
        days_count_query = sa.select(sa.func.count(sa.distinct(tournament_days.c.day)))

        tournaments_count_result = await session.execute(tournaments_count_query)
        teams_count_result = await session.execute(teams_count_query)
        players_count_result = await session.execute(players_count_query)
        champions_count_result = await session.execute(champions_count_query)
        encounters_count_result = await session.execute(encounters_count_query)
        maps_count, total_seconds = (await session.execute(maps_and_time_query)).one()
        days_count_result = await session.execute(days_count_query)
        return schemas.OverallStatistics(
            tournaments=tournaments_count_result.scalar_one(),
            teams=teams_count_result.scalar_one(),
            players=players_count_result.scalar_one(),
            champions=champions_count_result.scalar_one(),
            encounters=encounters_count_result.scalar_one(),
            maps=maps_count,
            days=days_count_result.scalar_one(),
            hours=int((total_seconds or 0) // 3600),
        )


tournament_service = TournamentService()
