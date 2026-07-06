"""Achievement flows v2 — reads from AchievementRule + AchievementEvaluationResult.

Drop-in replacement for flows.py. Uses service_v2 under the hood.
"""

import typing

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.achievements.achievement import AchievementRule
from src import schemas
from src.core import errors, pagination
from src.services.hero import flows as hero_flows
from src.services.user import flows as user_flows

from . import _mappers, _repositories
from . import service_v2 as service


async def to_pydantic(
    session: AsyncSession,
    rule: AchievementRule,
    rarity: float,
    entities: list[str],
) -> schemas.AchievementRead:
    hero = None
    count = None
    if "hero" in entities and rule.hero:
        hero = await hero_flows.to_pydantic(session, rule.hero, [])
    if "count" in entities:
        count = await service.get_count_users(session, [rule.id])

    return schemas.AchievementRead(
        **rule.to_dict(),
        rarity=rarity or 0.0,
        hero=hero,
        count=count.get(rule.id) if count else None,
    )


async def bulk_to_pydantic(
    session: AsyncSession,
    rules: typing.Sequence[tuple[AchievementRule, float]],
    entities: list[str],
) -> list[schemas.AchievementRead]:
    output: list[schemas.AchievementRead] = []
    count = None

    if "count" in entities:
        rule_ids = [rule.id for rule, _ in rules]
        count = await service.get_count_users(session, rule_ids)

    for rule, rarity in rules:
        hero = None
        if "hero" in entities and rule.hero:
            hero = await hero_flows.to_pydantic(session, rule.hero, [])

        output.append(
            schemas.AchievementRead(
                **rule.to_dict(),
                rarity=rarity or 0.0,
                hero=hero,
                count=count.get(rule.id) if count else None,
            )
        )

    return output


async def get(
    session: AsyncSession,
    achievement_id: int,
    entities: list[str],
    workspace_id: int | None = None,
) -> schemas.AchievementRead:
    result = await service.get(session, achievement_id, entities, workspace_id=workspace_id)

    if not result:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Achievement not found with id={achievement_id}",
                )
            ],
        )

    return await to_pydantic(session, result[0], result[1], entities)


async def get_all(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
    workspace_id: int | None = None,
) -> pagination.Paginated[schemas.AchievementRead]:
    rules, total = await service.get_all(session, params, workspace_id=workspace_id)
    return pagination.Paginated(
        total=total,
        per_page=params.per_page,
        page=params.page,
        results=await bulk_to_pydantic(session, rules, params.entities),
    )


async def get_user_achievements(
    session: AsyncSession,
    user_id: int,
    entities: list[str],
    tournament_id: int | None = None,
    without_tournament: bool = False,
    workspace_id: int | None = None,
    include_locked: bool = False,
) -> list[schemas.UserAchievementRead]:
    user = await user_flows.get(session, user_id, [])
    results = await service.get_user_results(
        session,
        user,
        workspace_id=workspace_id,
        tournament_id=tournament_id,
        without_tournament=without_tournament,
    )

    cache: dict[int, schemas.UserAchievementRead] = {}

    for result_row in results:
        rule_id = result_row.rule.id
        rule = result_row.rule

        if rule_id not in cache:
            cache[rule_id] = schemas.UserAchievementRead(
                **rule.to_dict(),
                rarity=result_row.rarity or 0.0,
                count=1,
                tournaments_ids=([result_row.tournament_id] if result_row.tournament_id else []),
                matches_ids=[result_row.match_id] if result_row.match_id else [],
                tournaments=[],
                matches=[],
                hero=None,
            )
        else:
            cache[rule_id].count += 1
            if result_row.tournament_id and result_row.tournament_id not in cache[rule_id].tournaments_ids:
                cache[rule_id].tournaments_ids.append(result_row.tournament_id)
            if result_row.match_id and result_row.match_id not in cache[rule_id].matches_ids:
                cache[rule_id].matches_ids.append(result_row.match_id)

    for achievement in cache.values():
        achievement.tournaments_ids.sort()
        achievement.matches_ids.sort()

    # Append not-yet-earned rules as locked entries (count=0). Only meaningful for
    # the global view — a per-tournament filter scopes to what was earned there.
    if include_locked and tournament_id is None and not without_tournament:
        all_rules = await service.get_all_rules_with_rarity(session, workspace_id=workspace_id)
        for rule, rarity in all_rules:
            if rule.id in cache:
                continue
            cache[rule.id] = schemas.UserAchievementRead(
                **rule.to_dict(),
                rarity=rarity or 0.0,
                count=0,
                tournaments_ids=[],
                matches_ids=[],
                tournaments=[],
                matches=[],
                hero=None,
            )

    # Bulk-fetch tournaments and matches in one DB hit each, then map back to
    # achievements. Previous loop did one round-trip per (achievement, tid),
    # which was O(N*M) — hot on the user-achievements endpoint.
    if "tournaments" in entities:
        unique_tournament_ids = sorted({tid for achievement in cache.values() for tid in achievement.tournaments_ids})
        if unique_tournament_ids:
            tournaments = await _repositories.get_tournaments_bulk(session, unique_tournament_ids)
            tournaments_map = {t.id: _mappers.to_tournament_link(t) for t in tournaments}
            for achievement in cache.values():
                achievement.tournaments = [
                    tournaments_map[tid] for tid in achievement.tournaments_ids if tid in tournaments_map
                ]

    if "matches" in entities:
        unique_match_ids = sorted({mid for achievement in cache.values() for mid in achievement.matches_ids})
        if unique_match_ids:
            matches = await _repositories.get_matches_bulk(session, unique_match_ids)
            matches_map = {m.id: _mappers.to_match_link(m) for m in matches}
            for achievement in cache.values():
                achievement.matches = [matches_map[mid] for mid in achievement.matches_ids if mid in matches_map]

    return list(cache.values())


async def get_achievement_users(
    session: AsyncSession,
    rule_id: int,
    params: pagination.PaginationParams,
) -> pagination.Paginated[schemas.AchievementEarned]:
    users, total = await service.get_users_for_rule(session, rule_id, params)
    results: list[schemas.AchievementEarned] = []
    tournament_to_fetch: list[int] = []
    matches_to_fetch: list[int] = []

    for _, _, last_tournament_id, last_match_id in users:
        if last_tournament_id:
            tournament_to_fetch.append(last_tournament_id)
        if last_match_id:
            matches_to_fetch.append(last_match_id)

    tournaments = await _repositories.get_tournaments_bulk(session, tournament_to_fetch)
    matches = await _repositories.get_matches_bulk(session, matches_to_fetch)

    tournaments_map = {t.id: t for t in tournaments}
    matches_map = {m.id: m for m in matches}

    for user, count, last_tournament_id, last_match_id in users:
        last_tournament = tournaments_map.get(last_tournament_id) if last_tournament_id else None
        last_match = matches_map.get(last_match_id) if last_match_id else None

        results.append(
            schemas.AchievementEarned(
                user=await user_flows.to_pydantic(session, user, []),
                count=count,
                last_tournament=_mappers.to_tournament_link(last_tournament) if last_tournament else None,
                last_match=_mappers.to_match_link(last_match) if last_match else None,
            )
        )

    return pagination.Paginated(
        total=total,
        per_page=params.per_page,
        page=params.page,
        results=results,
    )
