"""SQL helpers for user flows.

These queries used to live in `services._internal.encounter.service` and
`services._internal.team.service`. After P3-A they are private to
`services/user/` — the only consumer.
"""

from __future__ import annotations

import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from src import models
from src.core import enums, pagination
from src.core.workspace import workspace_filter

_HERO_JSON = sa.func.jsonb_build_object(
    "id",
    models.Hero.id,
    "created_at",
    models.Hero.created_at,
    "updated_at",
    models.Hero.updated_at,
    "name",
    models.Hero.name,
    "slug",
    models.Hero.slug,
    "image_path",
    models.Hero.image_path,
    "color",
    models.Hero.color,
    "type",
    models.Hero.type,
)


def _team_encounter_match_identity(
    row: typing.Sequence[typing.Any],
) -> tuple[int, int, int | None]:
    team, encounter, match, *_ = row
    return team.id, encounter.id, match.id if match is not None else None


def _encounter_match_identity(
    row: typing.Sequence[typing.Any],
) -> tuple[int, int | None]:
    encounter, match, *_ = row
    return encounter.id, match.id if match is not None else None


async def get_user_encounter_matches_unpaginated(
    session: AsyncSession, user_id: int
) -> typing.Sequence[
    tuple[
        models.Team,
        models.Encounter,
        models.Match | None,
        int | None,
        list[dict] | None,
        int | None,
        float | None,
        float | None,
        int | None,
    ]
]:
    """All (team, encounter, match) rows the user participated in.

    Used to assemble UserTournament.encounters. Loads:
      - Match.map — for `MatchReadWithUserStats.map`
      - Encounter.home_team / away_team + their players (so the encounter
        mapper can identify the viewer side and roster)
      - Encounter.stage / stage_item — to surface the bracket stage label

    Row shape: (team, encounter, match, performance, heroes, impact_rank,
    impact_points, overperformance_score, overperf_pos). ``overperf_pos`` is
    the viewer's rank (1 = best) among all match participants by
    OverperformanceScore, used to compute the MVP-impact badge.
    """
    performance_cte = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.value.label("value"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.match_id == models.Match.id,
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.Performance,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
            )
        )
        .cte("performance_cte")
    )

    impact_rank_cte = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.value.label("value"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.match_id == models.Match.id,
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.ImpactRank,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
            )
        )
        .cte("impact_rank_cte")
    )

    impact_points_cte = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.value.label("value"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.match_id == models.Match.id,
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.ImpactPoints,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
            )
        )
        .cte("impact_points_cte")
    )

    overperf_cte = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.user_id.label("user_id"),
            models.MatchStatistics.value.label("value"),
            sa.func.rank()
            .over(
                partition_by=models.MatchStatistics.match_id,
                order_by=models.MatchStatistics.value.desc(),
            )
            .label("pos"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.name == enums.LogStatsName.OverperformanceScore,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
            )
        )
        .cte("overperf_cte")
    )

    heroes_cte = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            sa.func.jsonb_agg(_HERO_JSON).label("value"),
        )
        .select_from(models.MatchStatistics)
        .join(models.Hero, models.MatchStatistics.hero_id == models.Hero.id)
        .where(
            sa.and_(
                models.MatchStatistics.match_id == models.Match.id,
                models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.hero_id.isnot(None),
                models.MatchStatistics.value > 60,
                models.MatchStatistics.round == 0,
            )
        )
        .group_by(models.MatchStatistics.match_id)
        .cte("heroes_cte")
    )

    query = (
        sa.select(
            models.Team,
            models.Encounter,
            models.Match,
            performance_cte.c.value.label("performance"),
            heroes_cte.c.value.label("heroes"),
            impact_rank_cte.c.value.label("impact_rank"),
            impact_points_cte.c.value.label("impact_points"),
            overperf_cte.c.value.label("overperformance_score"),
            overperf_cte.c.pos.label("overperf_pos"),
        )
        .select_from(models.Player)
        .options(
            joinedload(models.Match.map).joinedload(models.Map.gamemode),
            joinedload(models.Encounter.tournament),
            joinedload(models.Encounter.stage),
            joinedload(models.Encounter.stage_item),
            selectinload(models.Encounter.home_team)
            .selectinload(models.Team.players)
            .selectinload(models.Player.workspace_member),
            selectinload(models.Encounter.away_team)
            .selectinload(models.Team.players)
            .selectinload(models.Player.workspace_member),
        )
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Player.team_id,
                models.Encounter.away_team_id == models.Player.team_id,
            ),
        )
        .join(models.Team, models.Player.team_id == models.Team.id)
        .join(models.Match, models.Encounter.id == models.Match.encounter_id, isouter=True)
        .outerjoin(performance_cte, performance_cte.c.match_id == models.Match.id)
        .outerjoin(heroes_cte, heroes_cte.c.match_id == models.Match.id)
        .outerjoin(impact_rank_cte, impact_rank_cte.c.match_id == models.Match.id)
        .outerjoin(impact_points_cte, impact_points_cte.c.match_id == models.Match.id)
        .outerjoin(
            overperf_cte,
            sa.and_(overperf_cte.c.match_id == models.Match.id, overperf_cte.c.user_id == user_id),
        )
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
        .where(
            sa.and_(
                models.WorkspaceMember.player_id == user_id,
                models.Player.is_substitution.is_(False),
            )
        )
        .order_by(models.Team.id, models.Encounter.id)
    )

    result = await session.execute(query)
    return result.unique(_team_encounter_match_identity).all()  # type: ignore[arg-type]


async def get_user_encounters_paginated(
    session: AsyncSession,
    user_id: int,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
    *,
    result: str | None = None,
    stage: str | None = None,
    mvp1: bool = False,
    has_logs: bool | None = None,
    opponent: str | None = None,
) -> tuple[
    typing.Sequence[
        tuple[
            models.Encounter,
            models.Match | None,
            int | None,
            list[dict] | None,
            int | None,
            float | None,
            float | None,
            int | None,
        ]
    ],
    int,
]:
    """Paginated user encounters with the viewer's per-match performance + heroes.

    Loads `Encounter.tournament`, `Encounter.home_team`, `Encounter.away_team`
    and `Match.map` so the mapper can populate the narrow EncounterReadWithUserStats
    shape without any further round-trips.

    Row shape: (encounter, match, performance, heroes, impact_rank,
    impact_points, overperformance_score, overperf_pos). ``overperf_pos`` is
    the viewer's rank (1 = best) among all match participants by
    OverperformanceScore, used to compute the MVP-impact badge.
    """
    user_player_filter = sa.and_(
        models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id),
        models.Player.is_substitution.is_(False),
    )

    total_query = (
        sa.select(sa.func.count(models.Encounter.id))
        .join(
            models.Player,
            sa.or_(
                models.Encounter.home_team_id == models.Player.team_id,
                models.Encounter.away_team_id == models.Player.team_id,
            ),
        )
        .where(user_player_filter)
    )

    encounters_query = (
        sa.select(models.Encounter, models.Player.id.label("player_id"))
        .select_from(models.Player)
        .join(
            models.Encounter,
            sa.or_(
                models.Encounter.home_team_id == models.Player.team_id,
                models.Encounter.away_team_id == models.Player.team_id,
            ),
        )
        .where(user_player_filter)
    )

    if workspace_id is not None:
        total_query = total_query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id).where(
            *workspace_filter(workspace_id)
        )
        encounters_query = encounters_query.join(
            models.Tournament, models.Encounter.tournament_id == models.Tournament.id
        ).where(*workspace_filter(workspace_id))

    def apply_filters(q: sa.Select) -> sa.Select:
        """Apply the Matches-tab filters server-side. Both the count and the
        result query must get identical filters so pagination stays correct.
        `models.Player.team_id` is the viewer's team for the encounter (joined
        above), which lets us express win/loss and opponent-name conditions."""
        if has_logs is not None:
            q = q.where(models.Encounter.has_logs.is_(has_logs))

        if result == "win":
            q = q.where(
                sa.or_(
                    sa.and_(
                        models.Encounter.home_team_id == models.Player.team_id,
                        models.Encounter.home_score > models.Encounter.away_score,
                    ),
                    sa.and_(
                        models.Encounter.away_team_id == models.Player.team_id,
                        models.Encounter.away_score > models.Encounter.home_score,
                    ),
                )
            )
        elif result == "loss":
            q = q.where(
                sa.or_(
                    sa.and_(
                        models.Encounter.home_team_id == models.Player.team_id,
                        models.Encounter.home_score < models.Encounter.away_score,
                    ),
                    sa.and_(
                        models.Encounter.away_team_id == models.Player.team_id,
                        models.Encounter.away_score < models.Encounter.home_score,
                    ),
                )
            )
        elif result == "draw":
            q = q.where(models.Encounter.home_score == models.Encounter.away_score)

        if stage in ("group", "playoffs", "finals"):
            stage_item = sa.orm.aliased(models.StageItem)
            stage_obj = sa.orm.aliased(models.Stage)
            q = q.outerjoin(stage_item, models.Encounter.stage_item_id == stage_item.id).outerjoin(
                stage_obj, models.Encounter.stage_id == stage_obj.id
            )
            stage_name = sa.func.coalesce(stage_item.name, stage_obj.name)
            if stage == "finals":
                q = q.where(stage_name.ilike("%final%"))
            elif stage == "playoffs":
                q = q.where(sa.or_(stage_name.ilike("%playoff%"), stage_name.ilike("%bracket%")))
            else:
                q = q.where(sa.or_(stage_name.ilike("%group%"), stage_name.op("~*")("^[a-h]$")))

        if mvp1:
            mvp_subq = (
                sa.select(models.Match.encounter_id)
                .join(models.MatchStatistics, models.MatchStatistics.match_id == models.Match.id)
                .where(
                    models.MatchStatistics.user_id == user_id,
                    models.MatchStatistics.name == enums.LogStatsName.Performance,
                    models.MatchStatistics.hero_id.is_(None),
                    models.MatchStatistics.round == 0,
                    models.MatchStatistics.value == 1,
                )
            )
            q = q.where(models.Encounter.id.in_(mvp_subq))

        if opponent:
            home_t = sa.orm.aliased(models.Team)
            away_t = sa.orm.aliased(models.Team)
            like = f"%{opponent}%"
            q = q.outerjoin(home_t, models.Encounter.home_team_id == home_t.id).outerjoin(
                away_t, models.Encounter.away_team_id == away_t.id
            )
            q = q.where(
                sa.or_(
                    sa.and_(models.Encounter.home_team_id == models.Player.team_id, away_t.name.ilike(like)),
                    sa.and_(models.Encounter.away_team_id == models.Player.team_id, home_t.name.ilike(like)),
                )
            )

        return q

    total_query = apply_filters(total_query)
    encounters_query = apply_filters(encounters_query)

    encounters_query = params.apply_pagination_sort(encounters_query)
    encounters_query = encounters_query.subquery()

    paginated_match_ids = (
        sa.select(models.Match.id.label("match_id"))
        .select_from(encounters_query)
        .join(models.Match, models.Match.encounter_id == encounters_query.c.id)
        .cte("paginated_match_ids")
    )

    performance_cte = (
        sa.select(
            models.MatchStatistics.match_id,
            models.MatchStatistics.value.label("performance"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.Performance,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
                models.MatchStatistics.match_id.in_(sa.select(paginated_match_ids.c.match_id)),
            )
        )
        .cte("performance_cte")
    )

    heroes_cte = (
        sa.select(
            models.MatchStatistics.match_id,
            sa.func.jsonb_agg(_HERO_JSON).label("heroes"),
        )
        .join(models.Hero, models.MatchStatistics.hero_id == models.Hero.id)
        .where(
            sa.and_(
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.HeroTimePlayed,
                models.MatchStatistics.hero_id.isnot(None),
                models.MatchStatistics.value > 60,
                models.MatchStatistics.round == 0,
                models.MatchStatistics.match_id.in_(sa.select(paginated_match_ids.c.match_id)),
            )
        )
        .group_by(models.MatchStatistics.match_id)
        .cte("heroes_cte")
    )

    impact_rank_cte = (
        sa.select(
            models.MatchStatistics.match_id,
            models.MatchStatistics.value.label("impact_rank"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.ImpactRank,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
                models.MatchStatistics.match_id.in_(sa.select(paginated_match_ids.c.match_id)),
            )
        )
        .cte("impact_rank_cte")
    )

    impact_points_cte = (
        sa.select(
            models.MatchStatistics.match_id,
            models.MatchStatistics.value.label("impact_points"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.user_id == user_id,
                models.MatchStatistics.name == enums.LogStatsName.ImpactPoints,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
                models.MatchStatistics.match_id.in_(sa.select(paginated_match_ids.c.match_id)),
            )
        )
        .cte("impact_points_cte")
    )

    overperf_cte = (
        sa.select(
            models.MatchStatistics.match_id.label("match_id"),
            models.MatchStatistics.user_id.label("user_id"),
            models.MatchStatistics.value.label("overperformance_score"),
            sa.func.rank()
            .over(
                partition_by=models.MatchStatistics.match_id,
                order_by=models.MatchStatistics.value.desc(),
            )
            .label("overperf_pos"),
        )
        .where(
            sa.and_(
                models.MatchStatistics.name == enums.LogStatsName.OverperformanceScore,
                models.MatchStatistics.hero_id.is_(None),
                models.MatchStatistics.round == 0,
                models.MatchStatistics.match_id.in_(sa.select(paginated_match_ids.c.match_id)),
            )
        )
        .cte("overperf_cte")
    )

    query = (
        sa.select(
            models.Encounter,
            models.Match,
            performance_cte.c.performance,
            heroes_cte.c.heroes,
            impact_rank_cte.c.impact_rank,
            impact_points_cte.c.impact_points,
            overperf_cte.c.overperformance_score,
            overperf_cte.c.overperf_pos,
        )
        .select_from(encounters_query)
        .options(
            joinedload(models.Encounter.tournament),
            joinedload(models.Encounter.stage),
            joinedload(models.Encounter.stage_item),
            selectinload(models.Encounter.home_team)
            .selectinload(models.Team.players)
            .selectinload(models.Player.workspace_member),
            selectinload(models.Encounter.away_team)
            .selectinload(models.Team.players)
            .selectinload(models.Player.workspace_member),
            joinedload(models.Match.map).joinedload(models.Map.gamemode),
        )
        .join(models.Encounter, encounters_query.c.id == models.Encounter.id)
        .join(models.Match, models.Encounter.id == models.Match.encounter_id, isouter=True)
        .join(performance_cte, performance_cte.c.match_id == models.Match.id, isouter=True)
        .join(heroes_cte, heroes_cte.c.match_id == models.Match.id, isouter=True)
        .join(impact_rank_cte, impact_rank_cte.c.match_id == models.Match.id, isouter=True)
        .join(impact_points_cte, impact_points_cte.c.match_id == models.Match.id, isouter=True)
        .join(
            overperf_cte,
            sa.and_(overperf_cte.c.match_id == models.Match.id, overperf_cte.c.user_id == user_id),
            isouter=True,
        )
    )
    query = params.apply_sort(query)
    result = await session.execute(query)
    total_result = await session.execute(total_query)
    # Custom identity — the row contains a `jsonb_agg` list (heroes) which
    # isn't hashable, so the default `.unique()` blows up.
    return (
        result.unique(_encounter_match_identity).all(),  # type: ignore[arg-type]
        total_result.scalar_one(),
    )


def _user_win_case():
    """1 when the viewer's team (Player.team_id) won the encounter, else 0."""
    ut = models.Player.team_id
    return sa.case(
        (
            sa.or_(
                sa.and_(models.Encounter.home_team_id == ut, models.Encounter.home_score > models.Encounter.away_score),
                sa.and_(models.Encounter.away_team_id == ut, models.Encounter.away_score > models.Encounter.home_score),
            ),
            1,
        ),
        else_=0,
    )


def _user_loss_case():
    """1 when the viewer's team (Player.team_id) lost the encounter, else 0."""
    ut = models.Player.team_id
    return sa.case(
        (
            sa.or_(
                sa.and_(models.Encounter.home_team_id == ut, models.Encounter.home_score < models.Encounter.away_score),
                sa.and_(models.Encounter.away_team_id == ut, models.Encounter.away_score < models.Encounter.home_score),
            ),
            1,
        ),
        else_=0,
    )


_USER_ENCOUNTER_JOIN = sa.or_(
    models.Encounter.home_team_id == models.Player.team_id,
    models.Encounter.away_team_id == models.Player.team_id,
)


def _user_player_where(user_id: int):
    return (
        models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id),
        models.Player.is_substitution.is_(False),
    )


async def get_user_opponents(
    session: AsyncSession,
    user_id: int,
    workspace_id: int | None = None,
    *,
    limit: int = 8,
):
    """Most-fought opponents across ALL of the user's encounters: opponent team
    name + win/loss/draw record, ordered by number of meetings (desc)."""
    user_team = models.Player.team_id
    home_t = sa.orm.aliased(models.Team)
    away_t = sa.orm.aliased(models.Team)
    opp_name = sa.case(
        (models.Encounter.home_team_id == user_team, away_t.name),
        else_=home_t.name,
    )
    draw = sa.case((models.Encounter.home_score == models.Encounter.away_score, 1), else_=0)

    query = (
        sa.select(
            opp_name.label("name"),
            sa.func.sum(_user_win_case()).label("wins"),
            sa.func.sum(_user_loss_case()).label("losses"),
            sa.func.sum(draw).label("draws"),
        )
        .select_from(models.Player)
        .join(models.Encounter, _USER_ENCOUNTER_JOIN)
        .join(home_t, models.Encounter.home_team_id == home_t.id)
        .join(away_t, models.Encounter.away_team_id == away_t.id)
        .where(*_user_player_where(user_id))
    )

    if workspace_id is not None:
        query = query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id).where(
            *workspace_filter(workspace_id)
        )

    query = query.group_by(opp_name).order_by(sa.func.count(models.Encounter.id).desc()).limit(limit)

    return (await session.execute(query)).all()


async def get_user_stage_breakdown(
    session: AsyncSession,
    user_id: int,
    workspace_id: int | None = None,
):
    """Per-stage (group / playoffs / finals) win-loss record across ALL of the
    user's encounters. Rows whose stage doesn't classify get a NULL `kind` and
    are ignored by the caller."""
    stage_item = sa.orm.aliased(models.StageItem)
    stage_obj = sa.orm.aliased(models.Stage)
    stage_name = sa.func.coalesce(stage_item.name, stage_obj.name)
    stage_kind = sa.case(
        (stage_name.ilike("%final%"), "finals"),
        (sa.or_(stage_name.ilike("%playoff%"), stage_name.ilike("%bracket%")), "playoffs"),
        (sa.or_(stage_name.ilike("%group%"), stage_name.op("~*")("^[a-h]$")), "group"),
        else_=None,
    )

    query = (
        sa.select(
            stage_kind.label("kind"),
            sa.func.sum(_user_win_case()).label("w"),
            sa.func.sum(_user_loss_case()).label("l"),
        )
        .select_from(models.Player)
        .join(models.Encounter, _USER_ENCOUNTER_JOIN)
        .outerjoin(stage_item, models.Encounter.stage_item_id == stage_item.id)
        .outerjoin(stage_obj, models.Encounter.stage_id == stage_obj.id)
        .where(*_user_player_where(user_id))
    )

    if workspace_id is not None:
        query = query.join(models.Tournament, models.Encounter.tournament_id == models.Tournament.id).where(
            *workspace_filter(workspace_id)
        )

    query = query.group_by(stage_kind)

    return (await session.execute(query)).all()


async def count_teams_by_tournament_bulk(session: AsyncSession, tournaments_ids: list[int]) -> dict[int, int]:
    """Number of teams per tournament — used to compute `count_teams`."""
    if not tournaments_ids:
        return {}
    query = (
        sa.select(models.Team.tournament_id, sa.func.count(models.Team.id))
        .where(models.Team.tournament_id.in_(tournaments_ids))
        .group_by(models.Team.tournament_id)
    )
    result = await session.execute(query)
    return dict(result.all())


async def get_player_by_user_and_tournament(
    session: AsyncSession, user_id: int, tournament_id: int
) -> models.Player | None:
    """Look up a user's Player row for a specific tournament.

    Loads `team` + `team.tournament` (+ its `division_grid_version`) +
    `team.standings` for the stats page. The grid version is eager-loaded so the
    last-tournament card can render the division on the tournament's own grid
    without triggering a lazy load outside the async greenlet.
    """
    query = (
        sa.select(models.Player)
        .options(
            joinedload(models.Player.team)
            .joinedload(models.Team.tournament)
            .joinedload(models.Tournament.division_grid_version),
            joinedload(models.Player.team).selectinload(models.Team.standings),
        )
        .where(
            sa.and_(
                models.Player.workspace_member.has(models.WorkspaceMember.player_id == user_id),
                models.Player.tournament_id == tournament_id,
            )
        )
    )
    result = await session.execute(query)
    return result.unique().scalars().first()
