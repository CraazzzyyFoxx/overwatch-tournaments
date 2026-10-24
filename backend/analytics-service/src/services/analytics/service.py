import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from shared import models
from shared.core import enums
from shared.repository import AnalyticsAlgorithmRepository, AnalyticsPlayerRepository, TeamRepository
from shared.repository.stats_queries import player_facts
from shared.services.workspace_scope import workspace_scope_filter
from src.services.analytics.encounter_maps import seat_maps


class AnalyticsService:
    def __init__(
        self,
        *,
        algorithms: AnalyticsAlgorithmRepository = AnalyticsAlgorithmRepository(),
        players: AnalyticsPlayerRepository = AnalyticsPlayerRepository(),
        teams: TeamRepository = TeamRepository(),
    ) -> None:
        self.algorithms = algorithms
        self.players = players
        self.teams = teams

    async def get_analytics(
        self,
        session: AsyncSession,
        workspace_id: int | None = None,
        workspace_ids: typing.Sequence[int] | None = None,
        *,
        discipline: str,
    ) -> typing.Sequence[sa.RowMapping]:
        # A team's maps in a duel come from its confirmed games (see ``seat_maps``); a lobby (more than
        # two seats) scores points, not maps, so it only counts as played.
        seat = aliased(models.EncounterTeam, name="seat")
        maps_won, maps_lost = seat_maps(seat)
        points = (
            sa.select(
                models.WorkspaceMember.player_id.label("user_id"),
                models.Player.role.label("role"),
                models.Player.team_id.label("team_id"),
                # ``sum`` over the bigint ``count()`` maps is numeric (Decimal); the ratings math divides by floats.
                sa.cast(sa.func.sum(maps_won), sa.Integer).label("wins"),
                sa.cast(sa.func.sum(maps_lost), sa.Integer).label("losses"),
            )
            .select_from(models.Player)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .join(seat, sa.and_(seat.team_id == models.Player.team_id, seat.active.is_(True)))
            .join(models.Encounter, sa.and_(models.Encounter.id == seat.encounter_id, models.Encounter.slot_count == 2))
            .join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
            .where(
                models.Tournament.id >= 1,
                models.Tournament.discipline == discipline,
                *workspace_scope_filter(workspace_id, workspace_ids),
            )
            .group_by(models.WorkspaceMember.player_id, models.Player.role, models.Player.team_id)
        ).cte("player_points")

        match_seat = aliased(models.EncounterTeam, name="match_seat")
        matches = (
            sa.select(
                match_seat.team_id.label("team_id"),
                sa.func.count(models.Encounter.id).label("match_count"),
            )
            .join(models.Encounter, models.Encounter.id == match_seat.encounter_id)
            .join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
            .where(
                match_seat.active.is_(True),
                models.Tournament.id >= 1,
                models.Tournament.discipline == discipline,
                *workspace_scope_filter(workspace_id, workspace_ids),
            )
            .group_by(match_seat.team_id)
        ).cte("player_matches")

        team_counts = (
            sa.select(
                models.Team.tournament_id.label("tournament_id"),
                sa.func.count(models.Team.id).label("team_count"),
            )
            .join(models.Tournament, models.Team.tournament_id == models.Tournament.id)
            .where(models.Tournament.discipline == discipline, *workspace_scope_filter(workspace_id, workspace_ids))
            .group_by(models.Team.tournament_id)
        ).cte("team_counts")

        # A team's FINAL tournament placement is the overall_position of its LATEST
        # stage standing (the playoff bracket if it advanced, else the group stage),
        # not ``min()`` across stages: an advancing team carries a placeholder
        # overall_position=0 in the group stage, so ``min()`` mis-reads a 13th-place
        # finisher as the champion (inflating placement_score and the placement gate).
        standings = (
            sa.select(
                models.Standing.team_id.label("team_id"),
                models.Standing.tournament_id.label("tournament_id"),
                models.Standing.overall_position.label("overall_position"),
            )
            .join(models.Tournament, models.Standing.tournament_id == models.Tournament.id)
            .where(models.Tournament.discipline == discipline, *workspace_scope_filter(workspace_id, workspace_ids))
            .distinct(models.Standing.team_id, models.Standing.tournament_id)
            .order_by(
                models.Standing.team_id,
                models.Standing.tournament_id,
                models.Standing.stage_id.desc(),
            )
        ).cte("team_standings")

        facts = player_facts(discipline=discipline)
        performance_points = (
            sa.select(
                models.Player.id.label("player_id"),
                sa.func.avg(facts.c.value).label("performance_points"),
            )
            .select_from(models.Player)
            .join(facts, facts.c.workspace_member_id == models.Player.workspace_member_id)
            .join(models.Tournament, facts.c.tournament_id == models.Tournament.id)
            .where(
                facts.c.tournament_team_id == models.Player.team_id,
                facts.c.segment == 0,
                facts.c.entity_id.is_(None),
                facts.c.stat_code == enums.LogStatsName.PerformancePoints.value,
                models.Player.tournament_id == facts.c.tournament_id,
                *workspace_scope_filter(workspace_id, workspace_ids),
            )
            .group_by(models.Player.id)
        ).cte("performance_points")

        query = (
            sa.select(
                models.Team.id.label("team_id"),
                models.Player.id.label("player_id"),
                models.Player.name.label("player_name"),
                models.WorkspaceMember.player_id.label("user_id"),
                models.Player.role.label("role"),
                models.Player.rank.label("rank"),
                models.Tournament.id.label("tournament_id"),
                # Tournament chronology: ids are not chronological, so every per-player history orders by this.
                sa.func.coalesce(models.Tournament.start_date, models.Tournament.created_at).label("started_at"),
                sa.func.coalesce(points.c.wins, 0).label("wins"),
                sa.func.coalesce(points.c.losses, 0).label("losses"),
                sa.func.coalesce(matches.c.match_count, 0).label("match_count"),
                standings.c.overall_position.label("overall_position"),
                team_counts.c.team_count.label("team_count"),
                performance_points.c.performance_points.label("performance_points"),
            )
            .select_from(models.Team)
            .join(models.Player, models.Team.id == models.Player.team_id)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .join(models.Tournament, models.Player.tournament_id == models.Tournament.id)
            .join(
                points,
                sa.and_(
                    models.WorkspaceMember.player_id == points.c.user_id,
                    models.Player.role.is_not_distinct_from(points.c.role),
                    models.Player.team_id == points.c.team_id,
                ),
                isouter=True,
            )
            .join(matches, models.Player.team_id == matches.c.team_id, isouter=True)
            .join(
                standings,
                sa.and_(
                    standings.c.team_id == models.Team.id,
                    standings.c.tournament_id == models.Tournament.id,
                ),
                isouter=True,
            )
            .join(team_counts, team_counts.c.tournament_id == models.Tournament.id, isouter=True)
            .join(performance_points, performance_points.c.player_id == models.Player.id, isouter=True)
            .where(
                models.Tournament.id >= 1,
                models.Player.is_substitution.is_(False),
                models.Tournament.discipline == discipline,
                *workspace_scope_filter(workspace_id, workspace_ids),
            )
            .order_by(models.WorkspaceMember.player_id, models.Player.role, models.Tournament.id)
        )

        result = await session.execute(query)
        return result.mappings().all()

    async def lookback_tournament_ids(
        self,
        session: AsyncSession,
        end_tournament_id: int,
        look_back: int,
        workspace_id: int | None = None,
        workspace_ids: typing.Sequence[int] | None = None,
        *,
        discipline: str,
    ) -> list[int]:
        """The ``look_back`` most recent tournament ids up to the end tournament, by START DATE.

        Chronology is ``(coalesce(start_date, created_at), id)``. Returns the
        explicit id list, not an id interval: ids are not chronological in this
        database (tournament 62 started months before 61), so an ``id BETWEEN``
        window around an out-of-order tournament would pull in events played after
        it. Result is ordered oldest → newest and includes ``end_tournament_id`` itself.
        """
        chrono = sa.func.coalesce(models.Tournament.start_date, models.Tournament.created_at)
        end_key = (
            await session.execute(
                sa.select(chrono, models.Tournament.id).where(models.Tournament.id == end_tournament_id)
            )
        ).one_or_none()
        if end_key is None:
            return [int(end_tournament_id)]
        rows = await session.execute(
            sa.select(models.Tournament.id)
            .where(
                sa.tuple_(chrono, models.Tournament.id) <= sa.tuple_(*end_key),
                # Hidden tournaments are containers, not seasons. The per-workspace
                # scrim container would occupy one of the ``look_back`` slots while
                # contributing no encounters to the replay.
                models.Tournament.is_hidden.is_(False),
                models.Tournament.discipline == discipline,
                *workspace_scope_filter(workspace_id, workspace_ids),
            )
            .order_by(chrono.desc(), models.Tournament.id.desc())
            .limit(max(int(look_back), 1))
        )
        ids = [int(row[0]) for row in rows.all()]
        return list(reversed(ids)) if ids else [int(end_tournament_id)]

    async def get_matches_for_tournaments(
        self,
        session: AsyncSession,
        tournament_ids: typing.Sequence[int],
        workspace_id: int | None = None,
        workspace_ids: typing.Sequence[int] | None = None,
        *,
        discipline: str,
    ) -> typing.Sequence[models.Encounter]:
        """Encounters of the given tournaments in true chronological replay order.

        Companion to :func:`lookback_tournament_ids` — takes the explicit id list a
        date window resolves to (an id interval cannot express one) and orders the
        replay by tournament start date so rating updates happen in the order the
        games were actually played.
        """
        if not tournament_ids:
            return []
        chrono = sa.func.coalesce(models.Tournament.start_date, models.Tournament.created_at)
        query = (
            sa.select(models.Encounter)
            .options(
                sa.orm.selectinload(models.Encounter.teams),
                sa.orm.joinedload(models.Encounter.tournament),
            )
            .join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
            .where(
                models.Encounter.tournament_id.in_([int(t) for t in tournament_ids]),
                # NOT inert, unlike the player-scoped CTEs of ``get_analytics``: this
                # read reaches the encounters through ``joinedload``, so a scrim
                # encounter comes back with two real teams and empty rosters, and
                # ``prepare_openskill_data`` then calls ``PlackettLuce.rate`` with two
                # empty sides -- a hard ValueError for every tournament whose lookback
                # window spans the hidden scrim container. Scope it out at the source.
                models.Tournament.is_hidden.is_(False),
                models.Tournament.discipline == discipline,
                *workspace_scope_filter(workspace_id, workspace_ids),
            )
            .order_by(chrono, models.Encounter.tournament_id, models.Encounter.id)
        )
        result = await session.scalars(query)
        return result.unique().all()  # type: ignore

    async def computed_tournament_ids_after(
        self,
        session: AsyncSession,
        tournament_id: int,
        workspace_id: int | None = None,
        *,
        discipline: str,
    ) -> list[int]:
        """Tournaments of the scope started after ``tournament_id`` that already have v1 rows, oldest first.

        Chronology is ``(coalesce(start_date, created_at), id)``; "has v1 rows" means ``analytics.player_shift`` rows.
        """
        chrono = sa.func.coalesce(models.Tournament.start_date, models.Tournament.created_at)
        key = (
            await session.execute(sa.select(chrono, models.Tournament.id).where(models.Tournament.id == tournament_id))
        ).one()
        rows = await session.execute(
            sa.select(models.Tournament.id)
            .where(
                sa.tuple_(chrono, models.Tournament.id) > sa.tuple_(*key),
                models.Tournament.discipline == discipline,
                *workspace_scope_filter(workspace_id),
                sa.exists().where(models.AnalyticsPlayer.tournament_id == models.Tournament.id),
            )
            .order_by(chrono, models.Tournament.id)
        )
        return [int(row[0]) for row in rows.all()]

    async def ensure_algorithm(self, session: AsyncSession, name: str) -> models.AnalyticsAlgorithm:
        """The algorithm row by name, created on first use: a fresh environment needs no seed rows."""
        return await self.algorithms.ensure(session, name)

    async def list_algorithm_names_by_ids(self, session: AsyncSession, ids: typing.Sequence[int]) -> list[str]:
        return await self.algorithms.list_names_by_ids(session, ids)

    async def get_algorithms(
        self,
        session: AsyncSession,
        ids: list[int] | None = None,
    ) -> typing.Sequence[models.AnalyticsAlgorithm]:
        if ids:
            return await self.algorithms.list_by_ids(session, ids)
        return await self.algorithms.list_all(session)

    async def get_tournament_version_ids(
        self,
        session: AsyncSession,
        workspace_id: int | None = None,
        workspace_ids: typing.Sequence[int] | None = None,
        *,
        discipline: str,
    ) -> dict[int, int | None]:
        """Maps tournament_id -> division_grid_version_id for all analytics-relevant tournaments."""
        result = await session.execute(
            sa.select(models.Tournament.id, models.Tournament.division_grid_version_id).where(
                models.Tournament.id >= 1,
                models.Tournament.discipline == discipline,
                *workspace_scope_filter(workspace_id, workspace_ids),
            )
        )
        return {row[0]: row[1] for row in result.all()}

    async def get_players_by_tournament_id(
        self, session: AsyncSession, tournament_id: int
    ) -> typing.Sequence[models.AnalyticsPlayer]:
        return await self.players.list_by_tournament(session, tournament_id)

    async def get_rosters(
        self, session: AsyncSession, encounters: typing.Iterable[models.Encounter]
    ) -> dict[int, models.Team]:
        """The source teams behind the encounters' live seats, with players and their workspace members.

        A seat names its team by id only (and the id goes NULL once the team is deleted), so
        the rosters a replay rates are read here, in one query for the whole window.
        """
        team_ids = {seat.team_id for encounter in encounters for seat in encounter.teams if seat.team_id is not None}
        if not team_ids:
            return {}
        teams = await session.scalars(
            sa.select(models.Team)
            .options(sa.orm.selectinload(models.Team.players).selectinload(models.Player.workspace_member))
            .where(models.Team.id.in_(team_ids))
        )
        return {team.id: team for team in teams.unique()}

    async def get_teams_with_players(self, session: AsyncSession, tournament_id: int) -> typing.Sequence[models.Team]:
        """Return teams of a tournament with players and player users eagerly loaded."""
        return await self.teams.list_by_tournament(
            session,
            tournament_id,
            options=[
                sa.orm.selectinload(models.Team.players).selectinload(models.Player.workspace_member),
            ],
        )


analytics_service = AnalyticsService()
