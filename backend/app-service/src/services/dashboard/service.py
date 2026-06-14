import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models


async def get_counts(
    session: AsyncSession,
    workspace_id: int | None = None,
) -> dict[str, int]:
    ws_filters: list = []
    if workspace_id is not None:
        ws_filters.append(models.Tournament.workspace_id == workspace_id)

    tournaments_total = sa.select(sa.func.count(models.Tournament.id)).where(*ws_filters)
    tournaments_active = sa.select(sa.func.count(models.Tournament.id)).where(
        models.Tournament.is_finished.is_(False), *ws_filters
    )
    teams_total = (
        sa.select(sa.func.count(models.Team.id))
        .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
        .where(*ws_filters)
    )
    players_total = (
        sa.select(sa.func.count(models.Player.id))
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(*ws_filters)
    )
    encounters_total = (
        sa.select(sa.func.count(models.Encounter.id))
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(*ws_filters)
    )
    heroes_total = sa.select(sa.func.count(models.Hero.id))
    gamemodes_total = sa.select(sa.func.count(models.Gamemode.id))
    maps_total = sa.select(sa.func.count(models.Map.id))

    results = await session.execute(
        sa.select(
            tournaments_total.scalar_subquery(),
            tournaments_active.scalar_subquery(),
            teams_total.scalar_subquery(),
            players_total.scalar_subquery(),
            encounters_total.scalar_subquery(),
            heroes_total.scalar_subquery(),
            gamemodes_total.scalar_subquery(),
            maps_total.scalar_subquery(),
        )
    )
    row = results.one()
    return {
        "tournaments_total": row[0] or 0,
        "tournaments_active": row[1] or 0,
        "teams_total": row[2] or 0,
        "players_total": row[3] or 0,
        "encounters_total": row[4] or 0,
        "heroes_total": row[5] or 0,
        "gamemodes_total": row[6] or 0,
        "maps_total": row[7] or 0,
    }


async def get_issues(
    session: AsyncSession,
    workspace_id: int | None = None,
) -> dict[str, int]:
    ws_filters: list = []
    if workspace_id is not None:
        ws_filters.append(models.Tournament.workspace_id == workspace_id)

    encounters_missing_logs = (
        sa.select(sa.func.count(models.Encounter.id))
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(models.Encounter.has_logs.is_(False), *ws_filters)
    )

    # Teams that have zero players
    teams_with_players = (
        sa.select(models.Player.team_id).group_by(models.Player.team_id)
    )
    teams_without_players_q = (
        sa.select(sa.func.count(models.Team.id))
        .join(models.Tournament, models.Tournament.id == models.Team.tournament_id)
        .where(models.Team.id.not_in(teams_with_players), *ws_filters)
    )

    # Tournaments that have zero stages
    tournaments_with_stages = (
        sa.select(models.Stage.tournament_id)
        .group_by(models.Stage.tournament_id)
    )
    tournaments_without_stages_q = sa.select(sa.func.count(models.Tournament.id)).where(
        models.Tournament.id.not_in(tournaments_with_stages), *ws_filters
    )

    # Users that have no discord, battle_tag, or twitch identities
    users_with_discord = sa.select(models.UserDiscord.user_id)
    users_with_btag = sa.select(models.UserBattleTag.user_id)
    users_with_twitch = sa.select(models.UserTwitch.user_id)
    users_with_any = users_with_discord.union(users_with_btag, users_with_twitch)
    users_without_identities_q = sa.select(sa.func.count(models.User.id)).where(
        models.User.id.not_in(users_with_any)
    )

    results = await session.execute(
        sa.select(
            encounters_missing_logs.scalar_subquery(),
            teams_without_players_q.scalar_subquery(),
            tournaments_without_stages_q.scalar_subquery(),
            users_without_identities_q.scalar_subquery(),
        )
    )
    row = results.one()
    return {
        "encounters_missing_logs": row[0] or 0,
        "teams_without_players": row[1] or 0,
        "tournaments_without_stages": row[2] or 0,
        "users_without_identities": row[3] or 0,
    }


async def get_active_tournament_stats(
    session: AsyncSession,
    workspace_id: int | None = None,
) -> dict | None:
    ws_filters: list = []
    if workspace_id is not None:
        ws_filters.append(models.Tournament.workspace_id == workspace_id)

    # Find the most recent non-finished tournament
    active_q = (
        sa.select(models.Tournament.id)
        .where(models.Tournament.is_finished.is_(False), *ws_filters)
        .order_by(models.Tournament.id.desc())
        .limit(1)
    )
    result = await session.execute(active_q)
    tournament_id = result.scalar_one_or_none()
    if tournament_id is None:
        return None

    # Get encounter stats for the active tournament
    stats_q = sa.select(
        sa.func.count(models.Encounter.id),
        sa.func.count(models.Encounter.id).filter(models.Encounter.has_logs.is_(False)),
    ).where(models.Encounter.tournament_id == tournament_id)

    stats_result = await session.execute(stats_q)
    row = stats_result.one()
    total = row[0] or 0
    missing = row[1] or 0
    coverage = round(((total - missing) / total) * 100) if total > 0 else 100

    return {
        "tournament_id": tournament_id,
        "encounters_total": total,
        "encounters_missing_logs": missing,
        "log_coverage_percent": coverage,
    }
