import asyncio
import typing
from datetime import UTC, datetime
from statistics import mean

from cashews import cache
from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.services.division_grid_access import build_workspace_division_grid_normalizer
from shared.services.division_grid_normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
)
from shared.services.division_grid_resolution import (
    resolve_tournament_division,
    resolve_workspace_division,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config, enums, errors, pagination, utils
from src.core.workspace import get_division_grid_version
from src.services.hero import flows as hero_flows
from src.services.map import flows as map_flows
from src.services.statistics import service as statistics_service

from . import _mappers, _repositories

from . import service

tournament_stats = [
    enums.LogStatsName.HeroDamageDealt,
    enums.LogStatsName.KD,
    enums.LogStatsName.Eliminations,
    enums.LogStatsName.Assists,
    enums.LogStatsName.KDA,
    enums.LogStatsName.DamageDelta,
    enums.LogStatsName.Deaths,
    enums.LogStatsName.Performance,
]

overview_hero_metrics_order = [
    enums.LogStatsName.Eliminations,
    enums.LogStatsName.FinalBlows,
    enums.LogStatsName.HeroDamageDealt,
    enums.LogStatsName.HealingDealt,
]


# Computed once at import — COMPARE_METRIC_DEFINITIONS is module-level
# constant; rebuilding these dicts per request was pure waste.
_METRIC_DIRECTION_MAP: dict[str, bool] = {
    key: higher_is_better for key, _label, higher_is_better in service.COMPARE_METRIC_DEFINITIONS
}
_METRIC_LABEL_MAP: dict[str, str] = {
    key: label for key, label, _higher_is_better in service.COMPARE_METRIC_DEFINITIONS
}


def _build_baseline_average_row(rows: list[dict[str, typing.Any]]) -> dict[str, float | None]:
    baseline: dict[str, float | None] = {}
    for key, _label, _higher_is_better in service.COMPARE_METRIC_DEFINITIONS:
        values = [row.get(key) for row in rows if row.get(key) is not None]
        if not values:
            baseline[key] = None
        else:
            baseline[key] = float(sum(float(value) for value in values) / len(values))
    return baseline


def _compute_rank_and_percentile(
    rows: list[dict[str, typing.Any]],
    key: str,
    subject_value: float | int | None,
    higher_is_better: bool,
) -> tuple[int | None, float | None]:
    if subject_value is None:
        return None, None

    values = [row.get(key) for row in rows if row.get(key) is not None]
    if not values:
        return None, None

    if higher_is_better:
        better_count = sum(1 for value in values if float(value) > float(subject_value))
    else:
        better_count = sum(1 for value in values if float(value) < float(subject_value))

    rank = better_count + 1
    total = len(values)
    if total == 1:
        percentile = 100.0
    else:
        percentile = ((total - rank) / (total - 1)) * 100

    return rank, round(percentile, 2)


def _compute_better_worse(
    subject_value: float | int | None,
    baseline_value: float | int | None,
    higher_is_better: bool,
) -> typing.Literal["better", "worse", "equal"] | None:
    if subject_value is None or baseline_value is None:
        return None

    subject = float(subject_value)
    baseline = float(baseline_value)

    if subject == baseline:
        return "equal"

    if higher_is_better:
        return "better" if subject > baseline else "worse"

    return "better" if subject < baseline else "worse"


async def to_pydantic(session: AsyncSession, user: models.User, entities: list[str]) -> schemas.UserRead:
    """
    Converts a `User` model instance to a Pydantic `UserRead` schema, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user: The `User` model instance to convert.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `UserRead` schema instance.
    """
    battle_tags = []
    twitch = []
    discord = []

    unresolved = datetime(1, 1, 1, tzinfo=UTC)
    if "battle_tag" in entities:
        battle_tags = [schemas.UserBattleTagRead.model_validate(tag, from_attributes=True) for tag in user.battle_tag]
    if "twitch" in entities:
        twitch = [
            schemas.UserTwitchRead.model_validate(twitch, from_attributes=True)
            for twitch in sorted(
                user.twitch,
                key=lambda x: unresolved if x.updated_at is None else x.updated_at,
                reverse=True,
            )
        ]
    if "discord" in entities:
        discord = [
            schemas.UserDiscordRead.model_validate(discord, from_attributes=True)
            for discord in sorted(
                user.discord,
                key=lambda x: unresolved if x.updated_at is None else x.updated_at,
                reverse=True,
            )
        ]

    return schemas.UserRead(
        id=user.id,
        name=user.name,
        battle_tag=battle_tags,
        twitch=twitch,
        discord=discord,
    )


async def get(session: AsyncSession, user_id: int, entities: list[str]) -> models.User:
    """
    Retrieves a `User` model instance by its ID, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `User` model instance.

    Raises:
        errors.ApiHTTPException: If the user is not found.
    """
    user = await service.get(session, user_id, entities)
    if not user:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="not_found", msg=f"User with id {user_id} not found.")],
        )
    return user


async def get_by_battle_tag(session: AsyncSession, battle_tag: str, entities: list[str]) -> schemas.UserRead:
    """
    Retrieves a `User` model instance by its battle tag and converts it to a `UserRead` schema.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        battle_tag: The battle tag of the user to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `UserRead` schema instance.

    Raises:
        errors.ApiHTTPException: If the user is not found.
    """
    user = await service.find_by_battle_tag(session, battle_tag, entities)
    if not user:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"User with battle tag {battle_tag} not found.",
                )
            ],
        )
    return await to_pydantic(session, user, entities)


async def get_by_discord(session: AsyncSession, discord: str, entities: list[str]) -> schemas.UserRead:
    """
    Retrieves a `User` model instance by its Discord ID and converts it to a `UserRead` schema.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        discord: The Discord ID of the user to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `UserRead` schema instance.

    Raises:
        errors.ApiHTTPException: If the user is not found.
    """
    user = await service.get_by_discord(session, discord, entities)
    if not user:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="not_found", msg=f"User with discord {discord} not found.")],
        )
    return await to_pydantic(session, user, entities)


async def get_all(
    session: AsyncSession, params: pagination.PaginationSortSearchParams
) -> pagination.Paginated[schemas.UserRead]:
    """
    Retrieves a paginated list of `User` model instances and converts them to `UserRead` schemas.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        params: An instance of `SearchPaginationParams` containing pagination and filtering parameters.

    Returns:
        A `Paginated` instance containing `UserRead` schemas.
    """
    users, total = await service.get_all(session, params)
    return pagination.Paginated(
        page=params.page,
        per_page=params.per_page,
        total=total,
        results=[await to_pydantic(session, user, params.entities) for user in users],
    )


async def get_overview(
    session: AsyncSession,
    params: schemas.UserOverviewParams,
    workspace_id: int | None = None,
    *,
    grid: DivisionGrid,
    normalizer: DivisionGridNormalizer | None = None,
) -> pagination.Paginated[schemas.UserOverviewRow]:
    if params.div_min is not None and params.div_max is not None and params.div_min > params.div_max:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="invalid_filter",
                    msg="div_min must be less than or equal to div_max.",
                )
            ],
        )

    users, total = await service.get_overview_users(session, params, grid)
    if not users:
        return pagination.Paginated(
            page=params.page,
            per_page=params.per_page,
            total=total,
            results=[],
        )

    user_ids = [user.id for user in users]
    raw_roles_map = await service.get_overview_role_divisions(session, user_ids)
    tournaments_count_map = await service.get_overview_tournaments_count(session, user_ids, workspace_id=workspace_id)
    achievements_count_map = await service.get_overview_achievements_count(session, user_ids)
    averages_map = await service.get_overview_averages(session, user_ids)
    top_heroes_map = await service.get_overview_top_heroes(session, user_ids)
    hero_metrics_map = await service.get_overview_top_hero_metrics(session, top_heroes_map)

    rows: list[schemas.UserOverviewRow] = []
    for user in users:
        roles = [
            schemas.UserOverviewRoleDivision(
                role=role,
                division=resolve_workspace_division(
                    rank,
                    source_version_id=version_id,
                    fallback_grid=grid,
                    normalizer=normalizer,
                ),
            )
            for role, rank, version_id in raw_roles_map.get(user.id, [])
        ]

        top_heroes: list[schemas.UserOverviewHero] = []
        for hero, playtime_seconds in top_heroes_map.get(user.id, []):
            metrics_payload: list[schemas.UserOverviewHeroMetric] = []
            metrics = hero_metrics_map.get((user.id, hero.id), {})
            for metric_name in overview_hero_metrics_order:
                metric_value = metrics.get(metric_name)
                if metric_value is None:
                    continue
                metrics_payload.append(
                    schemas.UserOverviewHeroMetric(
                        name=metric_name,
                        avg_10=round(metric_value, 2),
                    )
                )

            top_heroes.append(
                schemas.UserOverviewHero(
                    hero=await hero_flows.to_pydantic(session, hero, []),
                    playtime_seconds=round(playtime_seconds, 2),
                    metrics=metrics_payload,
                )
            )

        avg_placement, avg_playoff_placement, avg_group_placement, avg_closeness = averages_map.get(
            user.id,
            (None, None, None, None),
        )

        rows.append(
            schemas.UserOverviewRow(
                id=user.id,
                name=user.name,
                roles=roles,
                top_heroes=top_heroes,
                tournaments_count=tournaments_count_map.get(user.id, 0),
                achievements_count=achievements_count_map.get(user.id, 0),
                averages=schemas.UserOverviewAverages(
                    avg_closeness=round(avg_closeness, 2) if avg_closeness is not None else None,
                    avg_placement=round(avg_placement, 2) if avg_placement is not None else None,
                    avg_playoff_placement=(
                        round(avg_playoff_placement, 2) if avg_playoff_placement is not None else None
                    ),
                    avg_group_placement=round(avg_group_placement, 2) if avg_group_placement is not None else None,
                ),
            )
        )

    return pagination.Paginated(
        page=params.page,
        per_page=params.per_page,
        total=total,
        results=rows,
    )


async def get_overview_stats(
    session: AsyncSession,
    params: "schemas.UserOverviewStatsQueryParams",
    *,
    grid: DivisionGrid,
) -> "schemas.UserOverviewStats":
    if params.div_min is not None and params.div_max is not None and params.div_min > params.div_max:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="invalid_filter",
                    msg="div_min must be less than or equal to div_max.",
                )
            ],
        )

    payload = await service.get_overview_stats(
        session,
        role=params.role,
        div_min=params.div_min,
        div_max=params.div_max,
        query=params.query,
        grid=grid,
    )
    return schemas.UserOverviewStats(**payload)


async def get_catalog(
    session: AsyncSession,
    params: "schemas.UserCatalogParams",
    *,
    grid: DivisionGrid,
    normalizer: DivisionGridNormalizer | None = None,
) -> "schemas.UserCatalogResponse":
    if params.div_min is not None and params.div_max is not None and params.div_min > params.div_max:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[
                errors.ApiExc(
                    code="invalid_filter",
                    msg="div_min must be less than or equal to div_max.",
                )
            ],
        )

    letters_with_users, total_users, available_letters = await service.get_catalog_users(
        session,
        role=params.role,
        div_min=params.div_min,
        div_max=params.div_max,
        query=params.query,
        letter=params.letter,
        per_letter=params.per_letter,
        max_letters=params.max_letters,
        grid=grid,
    )

    flat_users = [user for _letter, bucket in letters_with_users for user in bucket]
    if not flat_users:
        return schemas.UserCatalogResponse(
            letters=[],
            total=total_users,
            available_letters=available_letters,
        )

    user_ids = [user.id for user in flat_users]
    raw_roles_map = await service.get_overview_role_divisions(session, user_ids)
    tournaments_count_map = await service.get_overview_tournaments_count(session, user_ids)
    achievements_count_map = await service.get_overview_achievements_count(session, user_ids)
    averages_map = await service.get_overview_averages(session, user_ids)
    top_heroes_map = await service.get_overview_top_heroes(session, user_ids, limit=3)
    hero_metrics_map = await service.get_overview_top_hero_metrics(session, top_heroes_map)

    catalog_letters: list[schemas.UserCatalogLetter] = []
    for letter_label, users in letters_with_users:
        entries: list[schemas.UserCatalogEntry] = []
        for user in users:
            roles = [
                schemas.UserOverviewRoleDivision(
                    role=role,
                    division=resolve_workspace_division(
                        rank,
                        source_version_id=version_id,
                        fallback_grid=grid,
                        normalizer=normalizer,
                    ),
                )
                for role, rank, version_id in raw_roles_map.get(user.id, [])
            ]

            top_heroes: list[schemas.UserOverviewHero] = []
            for hero, playtime_seconds in top_heroes_map.get(user.id, []):
                metrics_payload: list[schemas.UserOverviewHeroMetric] = []
                metrics = hero_metrics_map.get((user.id, hero.id), {})
                for metric_name in overview_hero_metrics_order:
                    metric_value = metrics.get(metric_name)
                    if metric_value is None:
                        continue
                    metrics_payload.append(
                        schemas.UserOverviewHeroMetric(
                            name=metric_name,
                            avg_10=round(metric_value, 2),
                        )
                    )
                top_heroes.append(
                    schemas.UserOverviewHero(
                        hero=await hero_flows.to_pydantic(session, hero, []),
                        playtime_seconds=round(playtime_seconds, 2),
                        metrics=metrics_payload,
                    )
                )

            avg_placement, _, _, _ = averages_map.get(user.id, (None, None, None, None))

            entries.append(
                schemas.UserCatalogEntry(
                    id=user.id,
                    name=user.name,
                    roles=roles,
                    top_heroes=top_heroes,
                    tournaments_count=tournaments_count_map.get(user.id, 0),
                    achievements_count=achievements_count_map.get(user.id, 0),
                    avg_placement=round(avg_placement, 2) if avg_placement is not None else None,
                )
            )

        catalog_letters.append(
            schemas.UserCatalogLetter(
                letter=letter_label,
                count=len(entries),
                users=entries,
            )
        )

    return schemas.UserCatalogResponse(
        letters=catalog_letters,
        total=total_users,
        available_letters=available_letters,
    )


async def get_compare(
    session: AsyncSession,
    id: int,
    params: schemas.UserCompareParams,
    *,
    grid: DivisionGrid,
) -> schemas.UserCompareResponse:
    if params.div_min is not None and params.div_max is not None and params.div_min > params.div_max:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="invalid_filter", msg="div_min must be less than or equal to div_max.")],
        )

    mode = params.baseline
    resolved_role = params.role
    resolved_div_min = params.div_min
    resolved_div_max = params.div_max
    compare_role = resolved_role if mode == "cohort" else None
    compare_div_min = resolved_div_min if mode == "cohort" else None
    compare_div_max = resolved_div_max if mode == "cohort" else None

    if mode == "target_user" and not params.target_user_id:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="invalid_filter", msg="target_user_id is required for baseline=target_user.")],
        )

    subject = await get(session, id, [])

    subject_rows = await service.get_compare_population(
        session,
        user_ids=[subject.id],
        role=compare_role,
        div_min=compare_div_min,
        div_max=compare_div_max,
        tournament_id=params.tournament_id,
        grid=grid,
    )
    if not subject_rows:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[errors.ApiExc(code="not_found", msg="Subject user has no stats for selected cohort filters.")],
        )
    subject_row = subject_rows[0]

    baseline_target: schemas.UserCompareUser | None = None
    sample_size = 0
    population_rows: list[dict[str, typing.Any]] = []

    if mode == "target_user":
        target_user = await get(session, params.target_user_id, [])
        target_rows = await service.get_compare_population(
            session,
            user_ids=[target_user.id],
            tournament_id=params.tournament_id,
            grid=grid,
        )
        if not target_rows:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"User with id {target_user.id} not found.")],
            )
        baseline_row = target_rows[0]
        sample_size = 1
        baseline_target = schemas.UserCompareUser(id=target_user.id, name=target_user.name)
    else:
        population_rows = await service.get_compare_population(
            session,
            role=compare_role,
            div_min=compare_div_min,
            div_max=compare_div_max,
            tournament_id=params.tournament_id,
            grid=grid,
        )
        if not population_rows:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg="No users found for selected baseline filters.")],
            )
        baseline_row = _build_baseline_average_row(population_rows)
        sample_size = len(population_rows)

    labels = _METRIC_LABEL_MAP
    directions = _METRIC_DIRECTION_MAP

    metrics: list[schemas.UserCompareMetric] = []
    for key, _label, _higher_is_better in service.COMPARE_METRIC_DEFINITIONS:
        subject_value = subject_row.get(key)
        baseline_value = baseline_row.get(key)

        delta = None
        delta_percent = None
        if subject_value is not None and baseline_value is not None:
            delta = float(subject_value) - float(baseline_value)
            if float(baseline_value) != 0:
                delta_percent = (delta / abs(float(baseline_value))) * 100

        rank = None
        percentile = None
        if mode != "target_user":
            rank, percentile = _compute_rank_and_percentile(
                population_rows,
                key,
                subject_value,
                directions[key],
            )

        metrics.append(
            schemas.UserCompareMetric(
                key=key,
                label=labels[key],
                subject_value=subject_value,
                baseline_value=baseline_value,
                delta=round(delta, 4) if delta is not None else None,
                delta_percent=round(delta_percent, 2) if delta_percent is not None else None,
                better_worse=_compute_better_worse(subject_value, baseline_value, directions[key]),
                higher_is_better=directions[key],
                subject_rank=rank,
                subject_percentile=percentile,
            )
        )

    return schemas.UserCompareResponse(
        subject=schemas.UserCompareUser(id=subject.id, name=subject.name),
        baseline=schemas.UserCompareBaselineInfo(
            mode=mode,
            sample_size=sample_size,
            target_user=baseline_target,
            role=resolved_role if mode == "cohort" else None,
            div_min=resolved_div_min if mode == "cohort" else None,
            div_max=resolved_div_max if mode == "cohort" else None,
        ),
        metrics=metrics,
    )


async def get_hero_compare(
    session: AsyncSession,
    id: int,
    params: schemas.UserHeroCompareParams,
    *,
    grid: DivisionGrid,
) -> schemas.UserHeroCompareResponse:
    if params.div_min is not None and params.div_max is not None and params.div_min > params.div_max:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="invalid_filter", msg="div_min must be less than or equal to div_max.")],
        )

    mode = params.baseline
    resolved_role = params.role
    resolved_div_min = params.div_min
    resolved_div_max = params.div_max
    compare_role = resolved_role if mode == "cohort" else None
    compare_div_min = resolved_div_min if mode == "cohort" else None
    compare_div_max = resolved_div_max if mode == "cohort" else None

    if mode == "target_user" and not params.target_user_id:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="invalid_filter", msg="target_user_id is required for baseline=target_user.")],
        )

    subject = await get(session, id, [])
    target: schemas.UserCompareUser | None = None
    baseline_target: schemas.UserCompareUser | None = None
    sample_size = 0

    requested_stats = [stat for stat in params.stats if stat != enums.LogStatsName.HeroTimePlayed]
    if not requested_stats:
        requested_stats = list(service.DEFAULT_HERO_COMPARE_STATS)

    left_playtime, left_stats = await service.get_user_hero_compare_stats(
        session,
        user_id=subject.id,
        hero_id=params.left_hero_id,
        map_id=params.map_id,
        stats=requested_stats,
        role=compare_role,
        div_min=compare_div_min,
        div_max=compare_div_max,
        tournament_id=params.tournament_id,
        grid=grid,
    )
    if left_playtime < 600:
        left_stats = {}

    if mode == "target_user":
        target_model = await get(session, params.target_user_id, [])
        right_playtime, right_stats = await service.get_user_hero_compare_stats(
            session,
            user_id=target_model.id,
            hero_id=params.right_hero_id,
            map_id=params.map_id,
            stats=requested_stats,
            tournament_id=params.tournament_id,
            grid=grid,
        )
        if right_playtime < 600:
            right_stats = {}
        target = schemas.UserCompareUser(id=target_model.id, name=target_model.name)
        baseline_target = target
        sample_size = 1
    else:
        population_users = await service.get_compare_population_users(
            session,
            role=compare_role,
            div_min=compare_div_min,
            div_max=compare_div_max,
            tournament_id=params.tournament_id,
            grid=grid,
        )
        if not population_users:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg="No users found for selected baseline filters.")],
            )

        population_user_ids = [user_id for user_id, _ in population_users]
        baseline_playtime_by_user, baseline_stats_by_user = await service.get_users_hero_compare_stats(
            session,
            user_ids=population_user_ids,
            hero_id=params.right_hero_id,
            map_id=params.map_id,
            stats=requested_stats,
            role=compare_role,
            div_min=compare_div_min,
            div_max=compare_div_max,
            tournament_id=params.tournament_id,
            grid=grid,
        )

        sample_user_ids = [user_id for user_id, playtime in baseline_playtime_by_user.items() if playtime >= 600]
        if not sample_user_ids:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg="No users found for selected hero/map filters.")],
            )

        sample_size = len(sample_user_ids)
        right_playtime = float(sum(baseline_playtime_by_user[user_id] for user_id in sample_user_ids) / sample_size)
        right_stats = {
            stat: float(
                sum(baseline_stats_by_user.get((user_id, stat), 0.0) for user_id in sample_user_ids) / sample_size
            )
            for stat in requested_stats
        }

    metrics: list[schemas.UserHeroCompareMetric] = []
    for stat in requested_stats:
        left_value = float(left_stats.get(stat, 0.0))
        right_value = float(right_stats.get(stat, 0.0))
        delta = left_value - right_value
        higher_is_better = not enums.is_ascending_stat(stat)
        delta_percent = None
        if right_value != 0:
            delta_percent = (delta / abs(right_value)) * 100
        metrics.append(
            schemas.UserHeroCompareMetric(
                stat=stat,
                left_value=round(left_value, 2),
                right_value=round(right_value, 2),
                delta=round(delta, 2),
                delta_percent=round(delta_percent, 2) if delta_percent is not None else None,
                better_worse=_compute_better_worse(left_value, right_value, higher_is_better),
                higher_is_better=higher_is_better,
            )
        )

    left_hero = await hero_flows.get(session, params.left_hero_id) if params.left_hero_id else None
    right_hero = await hero_flows.get(session, params.right_hero_id) if params.right_hero_id else None
    map_value = await map_flows.get(session, params.map_id, []) if params.map_id else None

    return schemas.UserHeroCompareResponse(
        subject=schemas.UserCompareUser(id=subject.id, name=subject.name),
        target=target,
        baseline=schemas.UserCompareBaselineInfo(
            mode=mode,
            sample_size=sample_size,
            target_user=baseline_target,
            role=resolved_role if mode == "cohort" else None,
            div_min=resolved_div_min if mode == "cohort" else None,
            div_max=resolved_div_max if mode == "cohort" else None,
        ),
        subject_hero=left_hero,
        target_hero=right_hero,
        map=map_value,
        left_playtime_seconds=round(left_playtime, 2),
        right_playtime_seconds=round(right_playtime, 2),
        metrics=metrics,
    )


async def search_by_name(session: AsyncSession, name: str, fields: list[str]) -> list[schemas.UserSearch]:
    """
    Searches for a user by name and converts the result to a `UserRead` schema.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        name: The name of the user to search for.
        fields: A list of strings representing the names of related entities to include.

    Returns:
        A `UserSearch` schema instance.
    """
    users = await service.search_by_name(session, name, fields)
    return [schemas.UserSearch(id=user.user_id, name=user.battle_tag) for user in users]


async def get_read(session: AsyncSession, user_id: int, entities: list[str]) -> schemas.UserRead:
    """
    Retrieves a `User` model instance by its ID and converts it to a `UserRead` schema.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `UserRead` schema instance.
    """
    user = await get(session, user_id, entities)
    return await to_pydantic(session, user, entities)


async def get_roles(
    session: AsyncSession,
    user_id: int,
    workspace_id: int | None = None,
    *,
    grid: DivisionGrid,
    normalizer: DivisionGridNormalizer | None = None,
    division_grid_version: schemas.DivisionGridVersionRead | None = None,
) -> list[schemas.UserRole]:
    """
    Retrieves the roles and statistics for a user across tournaments.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve roles for.
        workspace_id: Optional workspace ID to filter by.
        grid: The division grid to compute divisions from rank.

    Returns:
        A list of `UserRole` schemas representing the user's roles and statistics.
    """
    roles = await service.get_roles(session, user_id, workspace_id=workspace_id, grid=grid)
    payload: list[schemas.UserRole] = []
    for role, maps_won, maps_lost, division in roles:
        latest_role = max(division, key=lambda item: item["tournament"])
        payload.append(
            schemas.UserRole(
                role=role,
                tournaments=len({item["tournament"] for item in division}),
                maps_won=maps_won,
                maps=maps_won + maps_lost,
                division=resolve_workspace_division(
                    latest_role["rank"],
                    source_version_id=latest_role["division_grid_version_id"],
                    fallback_grid=grid,
                    normalizer=normalizer,
                ),
                division_grid_version=division_grid_version,
            )
        )
    return payload


# Cache key intentionally omits `session`, `grid`, `normalizer` — they're
# either non-hashable runtime fixtures (session) or derivable from workspace_id
# (grid/normalizer are loaded fresh for the workspace). Workspace-level grid
# changes are rare; a TournamentChangedEvent invalidates all user_* keys.
@cache(
    ttl=config.settings.users_cache_ttl,
    key="user_profile:{id}:{workspace_id}",
    prefix="backend:",
)
async def get_profile(
    session: AsyncSession,
    id: int,
    workspace_id: int | None = None,
    *,
    grid: DivisionGrid,
    normalizer: DivisionGridNormalizer | None = None,
) -> schemas.UserProfile:
    """
    Retrieves a user's profile, including statistics, roles, and tournament history.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        id: The ID of the user to retrieve the profile for.

    Returns:
        A `UserProfile` schema instance.
    """
    user = await get(session, id, [])
    matches = await service.get_overall_statistics(session, user.id, workspace_id=workspace_id)
    matches_won, matches_lose, avg_closeness = 0, 0, 0
    if matches:
        matches_won, matches_lose, avg_closeness = matches
    if workspace_id is not None and normalizer is None:
        try:
            normalizer = await build_workspace_division_grid_normalizer(
                session,
                workspace_id,
                require_complete=False,
            )
        except DivisionGridNormalizationError:
            normalizer = None

    current_grid_version_model = await get_division_grid_version(session, workspace_id)
    current_grid_version = (
        schemas.DivisionGridVersionRead.model_validate(current_grid_version_model, from_attributes=True)
        if current_grid_version_model is not None
        else None
    )

    roles = await get_roles(
        session,
        user.id,
        workspace_id=workspace_id,
        grid=grid,
        normalizer=normalizer,
        division_grid_version=current_grid_version,
    )
    hero_statistics = await hero_flows.get_playtime(
        session,
        schemas.HeroPlaytimePaginationParams(user_id=user.id, sort="playtime", order="desc"),
        workspace_id=workspace_id,
    )

    teams, _ = await service.get_teams(
        session,
        user.id,
        params=pagination.PaginationSortParams(page=1, per_page=-1, entities=["tournament", "placement"]),
        workspace_id=workspace_id,
    )

    placements: list[int] = []
    placements_playoff: list[int] = []
    placements_group: list[int] = []
    tournaments_count: int = 0
    tournaments_won: int = 0

    # Narrow tournament summary — only fields the frontend renders on the user
    # overview. Pure CPU conversion (no SQL), no need to fan out.
    tournaments: list[schemas.UserTournamentSummary] = [
        _mappers.to_user_tournament_summary(team.tournament) for team in teams
    ]

    for team in teams:
        if team.tournament.is_league:
            continue

        placement = _mappers.resolve_team_placement(team)
        if placement is None:
            continue
        placements.append(placement)
        tournaments_count += 1
        if placement == 1:
            tournaments_won += 1
        for standing in team.standings:
            if standing.buchholz is None:
                placements_playoff.append(standing.position)
            else:
                placements_group.append(standing.position)

    return schemas.UserProfile(
        tournaments_count=tournaments_count,
        tournaments_won=tournaments_won,
        maps_total=matches_lose + matches_won,
        maps_won=matches_won,
        avg_placement=round(mean(placements), 2) if placements else None,
        avg_playoff_placement=(round(mean(placements_playoff), 2) if placements_playoff else None),
        avg_group_placement=(round(mean(placements_group), 2) if placements_group else None),
        avg_closeness=round(avg_closeness, 2) if avg_closeness else 0,
        most_played_hero=(hero_statistics.results[0].hero if hero_statistics.results else None),
        heroes_count=hero_statistics.total,
        roles=roles,
        hero_statistics=hero_statistics.results,
        tournaments=sorted(tournaments, key=lambda x: x.id, reverse=True),
    )


@cache(
    ttl=config.settings.users_cache_ttl,
    key="user_tournaments:{id}:{workspace_id}",
    prefix="backend:",
)
async def get_tournaments(
    session: AsyncSession, id: int, workspace_id: int | None = None, *, grid: DivisionGrid
) -> list[schemas.UserTournament]:
    """
    Retrieves a user's tournament history, including statistics and encounters.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        id: The ID of the user to retrieve tournament history for.

    Returns:
        A list of `UserTournament` schemas representing the user's tournament history.
    """
    user = await get(session, id, [])
    output: list[schemas.UserTournament] = []
    tournaments = await service.get_tournaments_with_stats(session, user.id, workspace_id=workspace_id)
    tournaments_ids = [tournament[0].tournament_id for tournament in tournaments]
    encounters: dict[int, list[schemas.EncounterReadWithUserStats]] = {}
    encounters_cache: dict[int, dict[int, models.Encounter]] = {}
    matches_cache: dict[int, dict[int, list[schemas.MatchReadWithUserStats]]] = {}
    matches = await _repositories.get_user_encounter_matches_unpaginated(session, user.id)
    placements = await _repositories.count_teams_by_tournament_bulk(session, tournaments_ids)

    for team, encounter, match, performance, heroes in matches:
        encounters.setdefault(team.id, [])
        encounters_cache.setdefault(team.id, {})
        matches_cache.setdefault(team.id, {})
        encounters_cache[team.id].setdefault(encounter.id, encounter)
        matches_cache[team.id].setdefault(encounter.id, [])

        if match:
            matches_cache[team.id][encounter.id].append(
                _mappers.to_match_with_user_stats(
                    match, performance=performance, heroes=heroes
                )
            )

    for team_id, encounter_dict in encounters_cache.items():
        for encounter_id, encounter in encounter_dict.items():
            encounters[team_id].append(
                _mappers.to_encounter_with_user_stats(
                    encounter,
                    matches=matches_cache.get(team_id, {}).get(encounter_id, []),
                    viewer_user_id=user.id,
                )
            )

    for team, wins, losses, avg_closeness in tournaments:
        user_role: enums.HeroClass | None = None
        user_division: int | None = None
        won: int = 0
        lost: int = 0
        draw: int = 0
        placement = _mappers.resolve_team_placement(team)

        # Use tournament-specific grid if available, otherwise fall back to workspace grid
        tournament_grid = (
            load_runtime_grid(team.tournament.division_grid_version)
            if team.tournament.division_grid_version is not None
            else grid
        )

        for player in team.players:
            if player.user_id == user.id:
                user_role = player.role
                user_division = resolve_tournament_division(
                    player.rank,
                    tournament_grid=tournament_grid,
                    fallback_grid=grid,
                )
                break

        for standing in team.standings:
            won += standing.win
            lost += standing.lose
            draw += standing.draw

        division_grid_version = (
            schemas.DivisionGridVersionRead.model_validate(team.tournament.division_grid_version, from_attributes=True)
            if team.tournament.division_grid_version is not None
            else None
        )

        players_read = [
            _mappers.to_user_tournament_player(player, grid=tournament_grid)
            for player in team.players
        ]

        tournament = schemas.UserTournament(
            id=team.tournament.id,
            number=team.tournament.number,
            name=team.tournament.name,
            is_league=team.tournament.is_league,
            team_id=team.id,
            team=team.name,
            players=players_read,
            closeness=round(avg_closeness, 2) if avg_closeness else 0,
            maps_won=wins,
            maps_lost=losses,
            placement=placement,
            role=user_role,
            division=user_division,
            division_grid_version=division_grid_version,
            count_teams=placements[team.tournament_id],
            won=won,
            lost=lost,
            draw=draw,
            encounters=encounters.get(team.id, []),
        )
        output.append(tournament)

    output = sorted(output, key=lambda x: x.id, reverse=True)
    return output


async def get_tournament_with_stats(
    session: AsyncSession, id: int, tournament_id: int, *, grid: DivisionGrid
) -> schemas.UserTournamentWithStats | None:
    """
    Retrieves detailed statistics for a user in a specific tournament.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        id: The ID of the user to retrieve statistics for.
        tournament_id: The ID of the tournament to retrieve statistics for.

    Returns:
        A `UserTournamentWithStats` schema instance if found, otherwise `None`.
    """
    user = await get(session, id, [])
    player = await _repositories.get_player_by_user_and_tournament(
        session, user.id, tournament_id
    )
    if player is None:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Player with user [id={user.id}] not found in tournament [id={tournament_id}].",
                )
            ],
        )
    team = player.team
    statistics = await service.get_tournament_stats_overall(session, team.tournament, user.id)
    last_playoff_placement: float | None = None
    last_group_placement: float | None = None
    stats: dict[enums.LogStatsName | typing.Literal["winrate"], schemas.UserTournamentStat] = {}
    winrate = await statistics_service.get_tournament_winrate(session, team.tournament, user.id)

    if winrate:
        stats["winrate"] = schemas.UserTournamentStat(value=winrate[1], rank=winrate[2], total=winrate[3])
    else:
        stats["winrate"] = schemas.UserTournamentStat(value=0, rank=0, total=0)

    for values in await statistics_service.get_tournament_avg_match_stat_for_user_bulk(
        session,
        team.tournament,
        user.id,
        tournament_stats,
    ):
        if not values:
            continue
        stat, _user_id, value, rank_desc, rank_asc, total = values

        rank = rank_asc if enums.is_ascending_stat(stat) else rank_desc

        stats[stat] = schemas.UserTournamentStat(value=value, rank=rank, total=total)

    for placement in team.standings:
        if placement.buchholz is None:
            last_playoff_placement = placement.position
        else:
            last_group_placement = placement.position

    return schemas.UserTournamentWithStats(
        id=team.tournament.id,
        number=team.tournament.number,
        name=team.tournament.name,
        division=resolve_tournament_division(
            player.rank,
            tournament_grid=grid,
        ),
        closeness=round(statistics[2], 2) if statistics[2] else 0,
        role=player.role,
        maps=statistics[0] + statistics[1] if statistics[0] else 0,
        maps_won=statistics[0] if statistics[0] else 0,
        playtime=round(statistics[3], 2) if statistics[3] else 0,
        group_placement=last_group_placement,
        playoff_placement=last_playoff_placement,
        stats=stats,
    )


async def get_heroes(
    session: AsyncSession,
    id: int,
    params: pagination.PaginationParams,
    stats: list[enums.LogStatsName] | None = None,
    tournament_id: int | None = None,
    workspace_id: int | None = None,
) -> pagination.Paginated[schemas.HeroWithUserStats]:
    """
    Retrieves a user's hero statistics, including performance and comparisons with other users.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        id: The ID of the user to retrieve hero statistics for.
        params:  An instance of `PaginationParams` containing pagination parameters (e.g., page, per_page).

    Returns:
        A list of `HeroWithUserStats` schemas representing the user's hero statistics.
    """
    user = await get(session, id, [])
    requested_stats = set(stats or [])
    stats_filter = list(requested_stats) if requested_stats else None

    user_stats = await service.get_statistics_by_heroes(session, user.id, stats_filter, tournament_id=tournament_id, workspace_id=workspace_id)
    if stats_filter:
        all_stats = await service.get_statistics_by_heroes_all_values_filtered(session, stats_filter)
    else:
        all_stats = await service.get_statistics_by_heroes_all_values(session)
    payload: list[schemas.HeroWithUserStats] = []

    stats_by_hero: dict[int, dict[enums.LogStatsName, schemas.HeroStat]] = {}
    cache_hero: dict[int, schemas.HeroRead] = {}

    for name, hero, value, value_best, value_avg_10, best_meta in user_stats:
        if requested_stats and name not in requested_stats and name != enums.LogStatsName.HeroTimePlayed:
            continue
        if hero.id not in cache_hero:
            cache_hero[hero.id] = await hero_flows.to_pydantic(session, hero, [])
        if hero.id not in stats_by_hero:
            stats_by_hero[hero.id] = {}
        stats_by_hero[hero.id][name] = schemas.HeroStat(
            name=name,
            overall=round(value, 2),
            best=schemas.HeroStatBest(
                encounter_id=best_meta["encounter_id"],
                map_name=best_meta["map_name"],
                value=round(value_best, 2),
                map_image_path=best_meta["map_image_path"],
                tournament_name=best_meta["tournament_name"],
                player_name=user.name,
            ),
            avg_10=round(value_avg_10, 2),
            best_all=None,
            avg_10_all=0,
        )

    for name, hero_id, value_best, value_avg_10, best_meta in all_stats:
        if requested_stats and name not in requested_stats:
            continue
        if hero_id in stats_by_hero:
            stats_by_hero[hero_id][name].best_all = schemas.HeroStatBest(
                encounter_id=best_meta["encounter_id"],
                map_name=best_meta["map_name"],
                value=round(value_best, 2),
                map_image_path=best_meta["map_image_path"],
                tournament_name=best_meta["tournament_name"],
                player_name=best_meta["username"],
            )
            stats_by_hero[hero_id][name].avg_10_all = round(value_avg_10, 2)

    for hero_id, stats in stats_by_hero.items():
        # Filter out heroes without meaningful playtime. Previously we used
        # eliminations == 0 which could hide valid support picks.
        playtime_stat = stats.get(enums.LogStatsName.HeroTimePlayed)
        if not playtime_stat or playtime_stat.overall <= 0:
            continue

        hero_stats = list(stats.values())
        if requested_stats:
            hero_stats = [hero_stat for hero_stat in hero_stats if hero_stat.name in requested_stats]
            if not hero_stats:
                continue

        payload.append(
            schemas.HeroWithUserStats(
                hero=cache_hero[hero_id],
                stats=hero_stats,
            )
        )

    return pagination.Paginated(
        page=params.page,
        per_page=params.per_page,
        total=len(payload),
        results=params.paginate_data(payload),
    )


async def get_best_teammates(
    session: AsyncSession, id: int, params: pagination.PaginationSortParams, workspace_id: int | None = None,
) -> pagination.Paginated[schemas.UserBestTeammate]:
    """
    Retrieves a paginated list of a user's best teammates, including win rate, tournaments played together,
    and performance statistics.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        id: The ID of the user to retrieve best teammates for.
        params: An instance of `PaginationParams` containing pagination parameters (e.g., page, per_page).

    Returns:
        A `Paginated` instance containing `UserBestTeammate` schemas, representing the user's best teammates.
    """
    user = await get(session, id, [])
    teammates, total = await service.get_best_teammates(session, user.id, params, workspace_id=workspace_id)
    return pagination.Paginated(
        page=params.page,
        per_page=params.per_page,
        total=total,
        results=[
            schemas.UserBestTeammate(
                user=await to_pydantic(session, teammate, []),
                winrate=round(winrate, 2),
                tournaments=tournaments,
                maps=maps or 0,
                stats={
                    enums.LogStatsName.Performance: (round(performance, 2) if performance else 0),
                    enums.LogStatsName.KDA: round(kda, 2) if kda else 0,
                },
            )
            for teammate, winrate, tournaments, maps, performance, kda in teammates
        ],
    )


async def get_encounters_by_user(
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
) -> pagination.Paginated[schemas.EncounterReadWithUserStats]:
    """Paginated encounters involving a specific user, with per-user stats.

    Returns narrow `EncounterReadWithUserStats` objects — the tournament and
    team summaries are always populated (loaded via joinedload in the repo).
    The `params.entities` query parameter is accepted for backward
    compatibility but ignored: the shape is fixed by the narrow DTO.
    """
    user = await get(session, user_id, [])
    encounters, total = await _repositories.get_user_encounters_paginated(
        session,
        user.id,
        params,
        workspace_id=workspace_id,
        result=result,
        stage=stage,
        mvp1=mvp1,
        has_logs=has_logs,
        opponent=opponent,
    )
    encounters_read: list[schemas.EncounterReadWithUserStats] = []
    encounters_cache: dict[int, models.Encounter] = {}
    matches_cache: dict[int, list[schemas.MatchReadWithUserStats]] = {}

    for encounter, match, performance, heroes in encounters:
        encounters_cache.setdefault(encounter.id, encounter)
        matches_cache.setdefault(encounter.id, [])

        if match:
            matches_cache[encounter.id].append(
                _mappers.to_match_with_user_stats(
                    match, performance=performance, heroes=heroes
                )
            )

    for encounter_id, encounter in encounters_cache.items():
        encounters_read.append(
            _mappers.to_encounter_with_user_stats(
                encounter,
                matches=matches_cache.get(encounter_id, []),
                viewer_user_id=user.id,
            )
        )

    return pagination.Paginated(
        total=total,
        per_page=params.per_page,
        page=params.page,
        results=encounters_read,
    )
