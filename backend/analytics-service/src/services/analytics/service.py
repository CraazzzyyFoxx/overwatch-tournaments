import typing

import sqlalchemy as sa
from shared.core import enums
from shared.division_grid import DEFAULT_GRID, DivisionGrid, division_case_expr, load_runtime_grid
from shared.models.division_grid import DivisionGridMapping, DivisionGridMappingRule, DivisionGridVersion
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core.workspace import workspace_scope_filter


async def get_analytics(
    session: AsyncSession,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> typing.Sequence[sa.RowMapping]:
    points_home = (
        sa.select(
            models.Player.user_id.label("user_id"),
            models.Player.role.label("role"),
            models.Player.team_id.label("team_id"),
            sa.func.sum(models.Encounter.home_score).label("wins"),
            sa.func.sum(models.Encounter.away_score).label("losses"),
        )
        .join(models.Encounter, models.Player.team_id == models.Encounter.home_team_id)
        .join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
        .where(
            models.Tournament.id >= 1,
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .group_by(models.Player.user_id, models.Player.role, models.Player.team_id)
    ).cte("player_points_home")

    points_away = (
        sa.select(
            models.Player.user_id.label("user_id"),
            models.Player.role.label("role"),
            models.Player.team_id.label("team_id"),
            sa.func.sum(models.Encounter.away_score).label("wins"),
            sa.func.sum(models.Encounter.home_score).label("losses"),
        )
        .join(models.Encounter, models.Player.team_id == models.Encounter.away_team_id)
        .join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
        .where(
            models.Tournament.id >= 1,
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .group_by(models.Player.user_id, models.Player.role, models.Player.team_id)
    ).cte("player_points_away")

    matches_home = (
        sa.select(
            models.Encounter.home_team_id.label("team_id"),
            sa.func.count(models.Encounter.id).label("match_count"),
        )
        .join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
        .where(
            models.Tournament.id >= 1,
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .group_by(models.Encounter.home_team_id)
    ).cte("player_matches_home")

    matches_away = (
        sa.select(
            models.Encounter.away_team_id.label("team_id"),
            sa.func.count(models.Encounter.id).label("match_count"),
        )
        .join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
        .where(
            models.Tournament.id >= 1,
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .group_by(models.Encounter.away_team_id)
    ).cte("player_matches_away")

    team_counts = (
        sa.select(
            models.Team.tournament_id.label("tournament_id"),
            sa.func.count(models.Team.id).label("team_count"),
        )
        .join(models.Tournament, models.Team.tournament_id == models.Tournament.id)
        .where(*workspace_scope_filter(workspace_id, workspace_ids))
        .group_by(models.Team.tournament_id)
    ).cte("team_counts")

    standings = (
        sa.select(
            models.Standing.team_id.label("team_id"),
            models.Standing.tournament_id.label("tournament_id"),
            sa.func.min(models.Standing.overall_position).label("overall_position"),
        )
        .join(models.Tournament, models.Standing.tournament_id == models.Tournament.id)
        .where(*workspace_scope_filter(workspace_id, workspace_ids))
        .group_by(models.Standing.team_id, models.Standing.tournament_id)
    ).cte("team_standings")

    performance_points = (
        sa.select(
            models.Player.id.label("player_id"),
            sa.func.avg(models.MatchStatistics.value).label("performance_points"),
        )
        .select_from(models.Player)
        .join(models.MatchStatistics, models.MatchStatistics.user_id == models.Player.user_id)
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
        .where(
            models.MatchStatistics.team_id == models.Player.team_id,
            models.MatchStatistics.round == 0,
            models.MatchStatistics.hero_id.is_(None),
            models.MatchStatistics.name == enums.LogStatsName.PerformancePoints,
            models.Player.tournament_id == models.Encounter.tournament_id,
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .group_by(models.Player.id)
    ).cte("performance_points")

    query = (
        sa.select(
            models.Team.id.label("team_id"),
            models.Player.id.label("player_id"),
            models.Player.name.label("player_name"),
            models.Player.user_id.label("user_id"),
            models.Player.role.label("role"),
            models.Player.rank.label("rank"),
            models.Player.is_newcomer.label("is_newcomer"),
            models.Player.is_newcomer_role.label("is_newcomer_role"),
            models.Tournament.id.label("tournament_id"),
            (
                sa.func.coalesce(points_home.c.wins, 0) + sa.func.coalesce(points_away.c.wins, 0)
            ).label("wins"),
            (
                sa.func.coalesce(points_home.c.losses, 0) + sa.func.coalesce(points_away.c.losses, 0)
            ).label("losses"),
            (
                sa.func.coalesce(matches_home.c.match_count, 0)
                + sa.func.coalesce(matches_away.c.match_count, 0)
            ).label("match_count"),
            standings.c.overall_position.label("overall_position"),
            team_counts.c.team_count.label("team_count"),
            performance_points.c.performance_points.label("performance_points"),
            sa.func.lag(models.Player.rank, 1).over(
                partition_by=(models.Player.user_id, models.Player.role),
                order_by=models.Tournament.id,
            ).label("previous_cost"),
            sa.func.lag(models.Player.rank, 2).over(
                partition_by=(models.Player.user_id, models.Player.role),
                order_by=models.Tournament.id,
            ).label("pre_previous_cost"),
            sa.func.lag(division_case_expr(models.Player.rank, DEFAULT_GRID), 1).over(
                partition_by=(models.Player.user_id, models.Player.role),
                order_by=models.Tournament.id,
            ).label("previous_div"),
            sa.func.lag(division_case_expr(models.Player.rank, DEFAULT_GRID), 2).over(
                partition_by=(models.Player.user_id, models.Player.role),
                order_by=models.Tournament.id,
            ).label("pre_previous_div"),
        )
        .select_from(models.Team)
        .join(models.Player, models.Team.id == models.Player.team_id)
        .join(models.Tournament, models.Player.tournament_id == models.Tournament.id)
        .join(
            points_home,
            sa.and_(
                models.Player.user_id == points_home.c.user_id,
                models.Player.role == points_home.c.role,
                models.Player.team_id == points_home.c.team_id,
            ),
            isouter=True,
        )
        .join(
            points_away,
            sa.and_(
                models.Player.user_id == points_away.c.user_id,
                models.Player.role == points_away.c.role,
                models.Player.team_id == points_away.c.team_id,
            ),
            isouter=True,
        )
        .join(matches_home, models.Player.team_id == matches_home.c.team_id, isouter=True)
        .join(matches_away, models.Player.team_id == matches_away.c.team_id, isouter=True)
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
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(models.Player.user_id, models.Player.role, models.Tournament.id)
    )

    result = await session.execute(query)
    return result.mappings().all()


async def get_matches(
    session: AsyncSession,
    start_range: int,
    end_range: int,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> typing.Sequence[models.Encounter]:
    query = (
        sa.select(models.Encounter)
        .options(
            sa.orm.joinedload(models.Encounter.home_team),
            sa.orm.joinedload(models.Encounter.away_team),
            sa.orm.joinedload(models.Encounter.home_team).joinedload(models.Team.players),
            sa.orm.joinedload(models.Encounter.away_team).joinedload(models.Team.players),
            sa.orm.joinedload(models.Encounter.home_team)
            .joinedload(models.Team.players)
            .joinedload(models.Player.user),
            sa.orm.joinedload(models.Encounter.away_team)
            .joinedload(models.Team.players)
            .joinedload(models.Player.user),
            sa.orm.joinedload(models.Encounter.tournament),
        )
        .join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id)
        .where(
            models.Encounter.tournament_id.between(start_range, end_range),
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(models.Encounter.tournament_id, models.Encounter.id)
    )
    result = await session.scalars(query)
    return result.unique().all()  # type: ignore


async def lookback_start_tournament_id(
    session: AsyncSession,
    end_tournament_id: int,
    look_back: int,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> int:
    """Chronological start id for an OpenSkill lookback window.

    Returns the smallest tournament id among the ``look_back`` most recent
    tournaments with ``id <= end_tournament_id`` (within scope). Replaces the
    old ``end_tournament_id - look_back`` arithmetic: tournament ids are sparse
    (cancelled events, cross-workspace gaps), so a numeric offset silently
    shrank — or emptied — the history window and biased the OpenSkill ratings.
    Falls back to ``end_tournament_id`` when no rows match.
    """
    rows = await session.scalars(
        sa.select(models.Tournament.id)
        .where(
            models.Tournament.id <= end_tournament_id,
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
        .order_by(models.Tournament.id.desc())
        .limit(max(int(look_back), 1))
    )
    ids = [int(i) for i in rows.all()]
    return min(ids) if ids else int(end_tournament_id)


async def get_performance_merit(session: AsyncSession) -> dict[int, float]:
    """Return ``{player_id: local_zscore}`` from materialised Performance v2 rows.

    ``local_zscore`` is the player's **context-adjusted individual** impact —
    their contribution to winning above what their team's and opponents' strength
    predicted (the Performance v2 target is ``won − baseline_win_prob`` fit over
    team/opp mu), standardised against the same-role + nearby-division cohort.
    Used as the individual core of the Linear shift signal so team strength
    enters as *context*, not as the signal. Players without a Performance v2 row
    are simply absent; callers fall back to the context-blind log residual.
    """
    rows = await session.execute(
        sa.select(
            models.AnalyticsPerformance.player_id,
            models.AnalyticsPerformance.local_zscore,
        ).where(models.AnalyticsPerformance.local_zscore.isnot(None))
    )
    return {int(player_id): float(zscore) for player_id, zscore in rows.all()}


async def get_algorithm(session: AsyncSession, name: str) -> models.AnalyticsAlgorithm:
    query = sa.select(models.AnalyticsAlgorithm).where(models.AnalyticsAlgorithm.name == name)
    result = await session.execute(query)
    return result.scalar_one()  # type: ignore


async def get_algorithms(
    session: AsyncSession,
    ids: list[int] | None = None,
) -> typing.Sequence[models.AnalyticsAlgorithm]:
    query = sa.select(models.AnalyticsAlgorithm)
    if ids is not None:
        query = query.where(models.AnalyticsAlgorithm.id.in_(ids))
    query = query.order_by(models.AnalyticsAlgorithm.id)
    result = await session.execute(query)
    return result.scalars().all()


async def get_tournament_version_ids(
    session: AsyncSession,
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> dict[int, int | None]:
    """Maps tournament_id -> division_grid_version_id for all analytics-relevant tournaments."""
    result = await session.execute(
        sa.select(models.Tournament.id, models.Tournament.division_grid_version_id)
        .where(
            models.Tournament.id >= 1,
            *workspace_scope_filter(workspace_id, workspace_ids),
        )
    )
    return {row[0]: row[1] for row in result.all()}


async def get_grid_versions(
    session: AsyncSession,
    version_ids: set[int],
) -> dict[int, DivisionGrid]:
    """Loads DivisionGrid runtime objects keyed by version_id."""
    if not version_ids:
        return {}
    result = await session.execute(
        sa.select(DivisionGridVersion)
        .options(sa.orm.selectinload(DivisionGridVersion.tiers))
        .where(DivisionGridVersion.id.in_(version_ids))
    )
    return {v.id: load_runtime_grid(v) for v in result.scalars().unique().all()}


async def get_primary_division_mappings(
    session: AsyncSession,
    pairs: list[tuple[int, int]],
) -> dict[tuple[int, int], dict[int, int]]:
    """
    For each (source_version_id, target_version_id) pair, returns
    {source_tier_number -> target_tier_number} using the primary mapping rule.
    Pairs with no mapping in the DB are silently omitted.
    """
    if not pairs:
        return {}

    source_ids = [p[0] for p in pairs]
    target_ids = [p[1] for p in pairs]

    mappings_result = await session.execute(
        sa.select(DivisionGridMapping)
        .options(
            sa.orm.selectinload(DivisionGridMapping.rules).selectinload(DivisionGridMappingRule.source_tier),
            sa.orm.selectinload(DivisionGridMapping.rules).selectinload(DivisionGridMappingRule.target_tier),
        )
        .where(
            DivisionGridMapping.source_version_id.in_(source_ids),
            DivisionGridMapping.target_version_id.in_(target_ids),
        )
    )

    pairs_set = set(pairs)
    out: dict[tuple[int, int], dict[int, int]] = {}
    for mapping in mappings_result.scalars().unique().all():
        key = (mapping.source_version_id, mapping.target_version_id)
        if key not in pairs_set:
            continue
        tier_map: dict[int, int] = {}
        for rule in mapping.rules:
            source_num = rule.source_tier.number
            target_num = rule.target_tier.number
            if rule.is_primary or source_num not in tier_map:
                tier_map[source_num] = target_num
        out[key] = tier_map
    return out


async def get_players_by_tournament_id(
    session: AsyncSession, tournament_id: int
) -> typing.Sequence[models.AnalyticsPlayer]:
    query = (
        sa.select(models.AnalyticsPlayer)
        .join(models.Player, models.AnalyticsPlayer.player_id == models.Player.id)
        .where(models.AnalyticsPlayer.tournament_id == tournament_id)
    )
    result = await session.execute(query)
    return result.scalars().all()  # type: ignore


async def get_teams_with_players(
    session: AsyncSession, tournament_id: int
) -> typing.Sequence[models.Team]:
    """Return teams of a tournament with players and player users eagerly loaded.

    Inlined replacement for parser-service ``team_service.get_by_tournament(
    session, tid, ["players", "players.user"])`` so analytics-service does not
    depend on parser-service internals.
    """
    query = (
        sa.select(models.Team)
        .where(models.Team.tournament_id == tournament_id)
        .options(
            sa.orm.selectinload(models.Team.players).selectinload(models.Player.user),
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().all()
