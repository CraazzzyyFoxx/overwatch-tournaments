"""Achievement service v2 based on rules + effective achievement rows."""

from __future__ import annotations

import typing
from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared.models.achievements.achievement import AchievementRule
from shared.services.achievement_effective import build_effective_achievement_rows_subquery
from src import models
from src.core import config, pagination, utils

# Cache-key prefix for the per-workspace rarity aggregate. Invalidated broadly on
# ``TournamentChangedEvent`` (see ``services.tournament_events``) — earned
# achievements and the player denominator both move with tournament/match data.
_RARITY_MAP_CACHE_KEY = "backend:achievement_rarity_map:{workspace_id}"

# Subquery to count distinct users (players) in a workspace
_player_count_subq = (
    sa.select(sa.func.count(models.WorkspaceMember.player_id.distinct()))
    .select_from(models.Player)
    .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
    .scalar_subquery()
)


@dataclass(slots=True)
class UserAchievementRow:
    rule: AchievementRule
    tournament_id: int | None
    match_id: int | None
    qualified_at: datetime
    rarity: float | None


def _player_count_for_workspace(workspace_id: int) -> sa.ScalarSelect:
    """Count distinct players within a specific workspace."""
    return (
        sa.select(sa.func.count(models.WorkspaceMember.player_id.distinct()))
        .select_from(models.Player)
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
        .where(models.Tournament.workspace_id == workspace_id)
    ).scalar_subquery()


def _effective_rows_subq(
    *,
    workspace_id: int | None = None,
    rule_ids: list[int] | None = None,
    user_ids: list[int] | None = None,
    name: str = "effective_achievement_rows",
) -> sa.Subquery:
    return build_effective_achievement_rows_subquery(
        workspace_id=workspace_id,
        achievement_rule_ids=rule_ids,
        user_ids=user_ids,
        name=name,
    )


def get_rarity_subq(
    workspace_id: int | None = None,
    rule_id: int | None = None,
) -> sa.Subquery:
    """Rarity = distinct users earned / total players (optionally per workspace)."""
    denominator = _player_count_for_workspace(workspace_id) if workspace_id else _player_count_subq
    effective_rows = _effective_rows_subq(
        workspace_id=workspace_id,
        rule_ids=[rule_id] if rule_id is not None else None,
        name="rarity_effective_rows",
    )

    return (
        sa.select(
            effective_rows.c.achievement_rule_id,
            (sa.func.count(sa.distinct(effective_rows.c.user_id)) / sa.func.nullif(denominator, 0)).label("rarity"),
        )
        .group_by(effective_rows.c.achievement_rule_id)
        .subquery()
    )


def rule_entity(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """Loading options for AchievementRule relationships."""
    entities = []
    if "hero" in in_entities:
        entities.append(utils.join_entity(child, AchievementRule.hero))
    return entities


async def get(
    session: AsyncSession,
    id: int,
    entities: list[str],
    workspace_id: int | None = None,
) -> tuple[AchievementRule, float] | None:
    """Retrieve a single achievement rule by ID with rarity."""
    rarity_subq = get_rarity_subq(workspace_id=workspace_id, rule_id=id)

    query = (
        sa.select(AchievementRule, rarity_subq.c.rarity)
        .options(*rule_entity(entities))
        .outerjoin(
            rarity_subq,
            AchievementRule.id == rarity_subq.c.achievement_rule_id,
        )
        .where(
            AchievementRule.id == id,
            AchievementRule.enabled.is_(True),
        )
    )

    if workspace_id is not None:
        query = query.where(AchievementRule.workspace_id == workspace_id)

    result = await session.execute(query)
    return result.first()


async def get_all(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
) -> tuple[typing.Sequence[tuple[AchievementRule, float]], int]:
    """Paginated list of achievement rules with rarity."""
    count_filter = [AchievementRule.enabled.is_(True)]
    if workspace_id:
        count_filter.append(AchievementRule.workspace_id == workspace_id)

    count_query = sa.select(sa.func.count(AchievementRule.id)).where(*count_filter)

    rarity_subq = get_rarity_subq(workspace_id=workspace_id)
    query = (
        sa.select(AchievementRule, rarity_subq.c.rarity.label("rarity"))
        .options(*rule_entity(params.entities))
        .outerjoin(
            rarity_subq,
            AchievementRule.id == rarity_subq.c.achievement_rule_id,
        )
        .where(AchievementRule.enabled.is_(True))
    )
    if workspace_id:
        query = query.where(AchievementRule.workspace_id == workspace_id)

    query = params.apply_pagination_sort(query)
    count = await session.execute(count_query)
    results = await session.execute(query)
    return results.all(), count.scalar()


@cache(ttl=config.settings.achievements_cache_ttl, key=_RARITY_MAP_CACHE_KEY)
async def _get_rarity_map(
    session: AsyncSession,
    *,
    workspace_id: int | None = None,
) -> dict[int, float]:
    """Rarity per achievement rule for a workspace: ``{rule_id: rarity}``.

    This is the expensive, profile-independent aggregate (UNION ALL + correlated
    EXISTS + GROUP BY over the *whole* workspace history, plus the player-count
    denominator). It does not depend on whose profile is being viewed, so it is
    cached per ``workspace_id`` (TTL ``achievements_cache_ttl``) instead of being
    recomputed on every "Achievements" tab open. Invalidated on
    ``TournamentChangedEvent`` (services.tournament_events).
    """
    rarity_subq = get_rarity_subq(workspace_id=workspace_id)
    result = await session.execute(sa.select(rarity_subq.c.achievement_rule_id, rarity_subq.c.rarity))
    return {rule_id: float(rarity) for rule_id, rarity in result.all() if rarity is not None}


async def get_all_rules_with_rarity(
    session: AsyncSession,
    workspace_id: int | None = None,
) -> typing.Sequence[tuple[AchievementRule, float | None]]:
    """All enabled rules with rarity, unpaginated — used to derive locked achievements.

    Rarity comes from the cached per-workspace map (``_get_rarity_map``); only the
    cheap enabled-rules lookup runs per call.
    """
    rarity_map = await _get_rarity_map(session, workspace_id=workspace_id)

    query = sa.select(AchievementRule).where(AchievementRule.enabled.is_(True))
    if workspace_id:
        query = query.where(AchievementRule.workspace_id == workspace_id)

    rules = (await session.execute(query)).scalars().all()
    return [(rule, rarity_map.get(rule.id)) for rule in rules]


async def get_count_users(
    session: AsyncSession,
    rule_ids: list[int],
) -> dict[int, int]:
    """Count distinct users per achievement rule."""
    if not rule_ids:
        return {}

    effective_rows = _effective_rows_subq(
        rule_ids=rule_ids,
        name="count_effective_rows",
    )
    query = sa.select(
        effective_rows.c.achievement_rule_id,
        sa.func.count(sa.distinct(effective_rows.c.user_id)).label("count"),
    ).group_by(effective_rows.c.achievement_rule_id)
    results = await session.execute(query)
    return {row[0]: row[1] for row in results.all()}


async def get_users_for_rule(
    session: AsyncSession,
    rule_id: int,
    params: pagination.PaginationParams,
) -> tuple[list[tuple[models.User, int, int | None, int | None]], int]:
    """Paginated list of users who earned a specific achievement."""
    effective_rows = _effective_rows_subq(
        rule_ids=[rule_id],
        name="rule_users_effective_rows",
    )

    total_query = sa.select(sa.func.count(sa.distinct(effective_rows.c.user_id)))

    query = (
        sa.select(
            models.User,
            sa.func.count().label("total"),
            sa.func.max(effective_rows.c.tournament_id).label("last_tournament_id"),
            sa.func.max(effective_rows.c.match_id).label("last_match_id"),
        )
        .select_from(effective_rows)
        .join(models.User, models.User.id == effective_rows.c.user_id)
        .group_by(models.User.id)
        .order_by(sa.desc(sa.text("total")))
    )
    query = params.apply_pagination(query)

    results = await session.execute(query)
    total = await session.scalar(total_query)
    return [(r[0], r[1], r[2], r[3]) for r in results], total or 0


async def get_user_results(
    session: AsyncSession,
    user: models.User,
    workspace_id: int | None = None,
    tournament_id: int | None = None,
    without_tournament: bool = False,
) -> list[UserAchievementRow]:
    """Retrieve all effective achievement results for a user, with rarity."""
    effective_rows = _effective_rows_subq(
        workspace_id=workspace_id,
        user_ids=[user.id],
        name="user_effective_rows",
    )
    rarity_subq = get_rarity_subq(workspace_id=workspace_id)

    query = (
        sa.select(
            AchievementRule,
            effective_rows.c.tournament_id,
            effective_rows.c.match_id,
            effective_rows.c.qualified_at,
            rarity_subq.c.rarity,
        )
        .select_from(effective_rows)
        .join(AchievementRule, AchievementRule.id == effective_rows.c.achievement_rule_id)
        .outerjoin(
            rarity_subq,
            AchievementRule.id == rarity_subq.c.achievement_rule_id,
        )
        .where(AchievementRule.enabled.is_(True))
        .order_by(sa.asc(rarity_subq.c.rarity), AchievementRule.id.asc())
    )

    if tournament_id is not None:
        query = query.where(effective_rows.c.tournament_id == tournament_id)

    if without_tournament:
        query = query.where(effective_rows.c.tournament_id.is_(None))

    results = await session.execute(query)
    return [
        UserAchievementRow(
            rule=row[0],
            tournament_id=row[1],
            match_id=row[2],
            qualified_at=row[3],
            rarity=row[4],
        )
        for row in results.all()
    ]
