import asyncio
import typing
from collections import Counter
from statistics import mean

from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.domain.roster_shape import RegistrationRoleCode
from shared.services.division_grid.access import build_workspace_division_grid_normalizer
from shared.services.division_grid.normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
)
from shared.services.division_grid.resolution import (
    resolve_tournament_division,
    resolve_workspace_division,
)
from src import models, schemas
from src.core import config, enums, errors, pagination
from src.core.db import async_session_maker
from src.core.workspace import get_division_grid_version
from src.services.hero.service import heroes as hero_service
from src.services.statistics.queries import StatisticsQueries
from src.services.statistics.queries import queries as statistics_queries

from . import _mappers
from .queries.compare import COMPARE_METRIC_DEFINITIONS, DEFAULT_HERO_COMPARE_STATS, UserCompareQueries
from .queries.compare import compare as compare_queries
from .queries.encounters import UserEncounterQueries
from .queries.encounters import encounters as encounter_queries
from .queries.overview import UserOverviewQueries
from .queries.overview import overview as overview_queries
from .queries.profile import UserProfileQueries
from .queries.profile import profile as profile_queries

__all__ = ["UserService", "users"]

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


# The draft card speaks slot codes (``tank``/``damage``/``support``); a roster
# row typed ``flex`` is not one of them and never reaches the card.
_DRAFT_CARD_ROLE_CODES: frozenset[str] = frozenset(typing.get_args(RegistrationRoleCode))


# Computed once at import — COMPARE_METRIC_DEFINITIONS is module-level
# constant; rebuilding these dicts per request was pure waste.
_METRIC_DIRECTION_MAP: dict[str, bool] = {
    key: higher_is_better for key, _label, higher_is_better in COMPARE_METRIC_DEFINITIONS
}


_METRIC_LABEL_MAP: dict[str, str] = {key: label for key, label, _higher_is_better in COMPARE_METRIC_DEFINITIONS}


def _build_baseline_average_row(rows: list[dict[str, typing.Any]]) -> dict[str, float | None]:
    baseline: dict[str, float | None] = {}
    for key, _label, _higher_is_better in COMPARE_METRIC_DEFINITIONS:
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


class UserService:
    """Orchestrates the user read surface: query objects in, pydantic DTOs out."""

    def __init__(
        self,
        *,
        profile: UserProfileQueries = profile_queries,
        overview: UserOverviewQueries = overview_queries,
        compare: UserCompareQueries = compare_queries,
        encounters: UserEncounterQueries = encounter_queries,
        statistics: StatisticsQueries = statistics_queries,
    ) -> None:
        self.profile = profile
        self.overview = overview
        self.compare = compare
        self.encounters = encounters
        self.statistics_queries = statistics

    @staticmethod
    def to_read(user: models.User, entities: list[str], *, visible_only: bool = False) -> schemas.UserRead:
        """Convert a `User` to ``UserRead``. Identities come from the unified
        ``user.social_accounts`` relationship and are only accessed (and serialized)
        when an identity entity was requested — and therefore eager-loaded — so this
        never triggers a lazy load outside the async greenlet. The legacy entity
        tokens (``battle_tag``/``discord``/``twitch``) are still honored as triggers
        for backward compatibility with existing callers.

        ``visible_only`` is set by public-facing reads (profile, list): accounts the
        owner has hidden from the public profile (no global visibility row) are
        dropped. Admin/self reads leave it False so they see every account.
        """
        social_accounts: list[schemas.SocialAccountRead] = []
        if any(name in entities for name in _mappers._IDENTITY_ENTITIES):
            accounts = sorted(user.social_accounts, key=lambda a: (a.provider, not a.is_primary, a.id))
            if visible_only:
                accounts = [account for account in accounts if _mappers._is_globally_visible(account)]
            social_accounts = [_mappers._social_account_read(account) for account in accounts]
        return schemas.UserRead(
            id=user.id,
            name=user.name,
            avatar_url=user.avatar_url,
            # ``is not False`` rather than a truthiness check: the column default lands
            # at INSERT, so a transient (unflushed) ``User`` reads None here, and
            # reporting that as "hidden" would show the owner a switch that lies about
            # their own state. Same fail-open direction as ``_is_globally_visible``.
            stream_visible=user.stream_visible is not False,
            social_accounts=social_accounts,
        )

    async def get(self, session: AsyncSession, user_id: int, entities: list[str]) -> models.User:
        """A user by ID with ``entities`` eager-loaded; 400 when no such user exists."""
        user = await self.profile.get(session, user_id, entities)
        if not user:
            raise errors.ApiHTTPException(
                status_code=400,
                detail=[errors.ApiExc(code="not_found", msg=f"User with id {user_id} not found.")],
            )
        return user

    async def get_by_battle_tag(self, session: AsyncSession, battle_tag: str, entities: list[str]) -> schemas.UserRead:
        """A user by battle tag as ``UserRead``; 400 when no such user exists."""
        user = await self.profile.find_by_battle_tag(session, battle_tag, entities)
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
        return self.to_read(user, entities, visible_only=True)

    async def get_by_discord(self, session: AsyncSession, discord: str, entities: list[str]) -> schemas.UserRead:
        """A user by Discord handle as ``UserRead``; 400 when no such user exists."""
        user = await self.profile.get_by_discord(session, discord, entities)
        if not user:
            raise errors.ApiHTTPException(
                status_code=400,
                detail=[errors.ApiExc(code="not_found", msg=f"User with discord {discord} not found.")],
            )
        return self.to_read(user, entities, visible_only=True)

    async def get_all(
        self, session: AsyncSession, params: pagination.PaginationSortSearchParams
    ) -> pagination.Paginated[schemas.UserRead]:
        """Paginated users as ``UserRead`` schemas."""
        users, total = await self.profile.get_all(session, params)
        return pagination.Paginated(
            page=params.page,
            per_page=params.per_page,
            total=total,
            results=[self.to_read(user, params.entities, visible_only=True) for user in users],
        )

    async def _gather_overview_enrichment(
        self,
        session: AsyncSession,
        user_ids: list[int],
        *,
        workspace_id: int | None,
        top_heroes_limit: int = 5,
    ) -> tuple[
        dict[int, list[tuple[enums.HeroClass, int, int | None]]],
        dict[int, int],
        dict[int, int],
        dict[int, tuple[float | None, float | None, float | None, float | None]],
        dict[int, list[tuple[models.Hero, float]]],
        dict[tuple[int, int], dict[enums.LogStatsName, float]],
    ]:
        """Fan out the independent per-page aggregates.

        AsyncSession is not concurrency-safe, so each parallel query gets
        its own session (same pattern as DashboardService._gather). Hero
        metrics need the top-heroes map, so they run after the gather on the
        request session.
        """

        async def _isolated(fn):
            async with async_session_maker() as isolated:
                return await fn(isolated)

        (
            raw_roles_map,
            tournaments_count_map,
            achievements_count_map,
            averages_map,
            top_heroes_map,
        ) = await asyncio.gather(
            _isolated(lambda s: self.overview.get_overview_role_divisions(s, user_ids, workspace_id=workspace_id)),
            _isolated(lambda s: self.overview.get_overview_tournaments_count(s, user_ids, workspace_id=workspace_id)),
            _isolated(lambda s: self.overview.get_overview_achievements_count(s, user_ids, workspace_id=workspace_id)),
            _isolated(lambda s: self.overview.get_overview_averages(s, user_ids, workspace_id=workspace_id)),
            _isolated(
                lambda s: self.overview.get_overview_top_heroes(
                    s, user_ids, limit=top_heroes_limit, workspace_id=workspace_id
                )
            ),
        )
        hero_metrics_map = await self.overview.get_overview_top_hero_metrics(
            session, top_heroes_map, workspace_id=workspace_id
        )
        return (
            raw_roles_map,
            tournaments_count_map,
            achievements_count_map,
            averages_map,
            top_heroes_map,
            hero_metrics_map,
        )

    async def get_overview(
        self,
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

        users, total = await self.overview.get_overview_users(session, params, grid, workspace_id=workspace_id)
        if not users:
            return pagination.Paginated(
                page=params.page,
                per_page=params.per_page,
                total=total,
                results=[],
            )

        user_ids = [user.id for user in users]
        (
            raw_roles_map,
            tournaments_count_map,
            achievements_count_map,
            averages_map,
            top_heroes_map,
            hero_metrics_map,
        ) = await self._gather_overview_enrichment(session, user_ids, workspace_id=workspace_id)

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
                        hero=hero_service.to_read(hero),
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
        self,
        session: AsyncSession,
        params: schemas.UserOverviewStatsQueryParams,
        *,
        grid: DivisionGrid,
        workspace_id: int | None = None,
    ) -> schemas.UserOverviewStats:
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

        payload = await self.overview.get_overview_stats(
            session,
            role=params.role,
            div_min=params.div_min,
            div_max=params.div_max,
            query=params.query,
            grid=grid,
            workspace_id=workspace_id,
        )
        return schemas.UserOverviewStats(**payload)

    async def get_catalog(
        self,
        session: AsyncSession,
        params: schemas.UserCatalogParams,
        *,
        grid: DivisionGrid,
        normalizer: DivisionGridNormalizer | None = None,
        workspace_id: int | None = None,
    ) -> schemas.UserCatalogResponse:
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

        letters_with_users, total_users, available_letters = await self.overview.get_catalog_users(
            session,
            role=params.role,
            div_min=params.div_min,
            div_max=params.div_max,
            query=params.query,
            letter=params.letter,
            per_letter=params.per_letter,
            max_letters=params.max_letters,
            grid=grid,
            workspace_id=workspace_id,
        )

        flat_users = [user for _letter, bucket in letters_with_users for user in bucket]
        if not flat_users:
            return schemas.UserCatalogResponse(
                letters=[],
                total=total_users,
                available_letters=available_letters,
            )

        user_ids = [user.id for user in flat_users]
        (
            raw_roles_map,
            tournaments_count_map,
            achievements_count_map,
            averages_map,
            top_heroes_map,
            hero_metrics_map,
        ) = await self._gather_overview_enrichment(
            session,
            user_ids,
            workspace_id=workspace_id,
            top_heroes_limit=3,
        )

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
                            hero=hero_service.to_read(hero),
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
        self,
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
                detail=[
                    errors.ApiExc(code="invalid_filter", msg="target_user_id is required for baseline=target_user.")
                ],
            )

        baseline_target: schemas.UserCompareUser | None = None
        sample_size = 0
        population_rows: list[dict[str, typing.Any]] = []

        if mode == "target_user":
            requested_ids = [id, typing.cast(int, params.target_user_id)]
            pair_rows = await self.compare.get_compare_population(
                session,
                user_ids=requested_ids,
                tournament_id=params.tournament_id,
                grid=grid,
            )
            pair_by_id = {int(row["id"]): row for row in pair_rows}
            subject_row = pair_by_id.get(id)
            if subject_row is None:
                raise errors.ApiHTTPException(
                    status_code=400,
                    detail=[errors.ApiExc(code="not_found", msg=f"User with id {id} not found.")],
                )
            target_id = typing.cast(int, params.target_user_id)
            baseline_row = pair_by_id.get(target_id)
            if baseline_row is None:
                raise errors.ApiHTTPException(
                    status_code=400,
                    detail=[errors.ApiExc(code="not_found", msg=f"User with id {target_id} not found.")],
                )
            sample_size = 1
            baseline_target = schemas.UserCompareUser(id=target_id, name=str(baseline_row["name"]))
        else:
            # Population already contains the subject on the common path (global, or
            # a cohort the subject belongs to). The 1-user query is only the fallback
            # when the subject sits outside the cohort filter.
            population_rows = await self.compare.get_compare_population(
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
            subject_row = next((row for row in population_rows if int(row["id"]) == id), None)
            if subject_row is None:
                subject_rows = await self.compare.get_compare_population(
                    session,
                    user_ids=[id],
                    role=compare_role,
                    div_min=compare_div_min,
                    div_max=compare_div_max,
                    tournament_id=params.tournament_id,
                    grid=grid,
                )
                if not subject_rows:
                    raise errors.ApiHTTPException(
                        status_code=400,
                        detail=[errors.ApiExc(code="not_found", msg=f"User with id {id} not found.")],
                    )
                subject_row = subject_rows[0]
            baseline_row = _build_baseline_average_row(population_rows)
            sample_size = len(population_rows)

        labels = _METRIC_LABEL_MAP
        directions = _METRIC_DIRECTION_MAP

        metrics: list[schemas.UserCompareMetric] = []
        for key, _label, _higher_is_better in COMPARE_METRIC_DEFINITIONS:
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
            subject=schemas.UserCompareUser(id=id, name=str(subject_row["name"])),
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

    @cache(
        ttl=config.settings.users_cache_ttl,
        key=(
            "backend:user_compare:v2:{id}:{baseline}:{target_user_id}:{role}:{div_min}:{div_max}:"
            "{tournament_id}:{grid_version}"
        ),
        lock=True,
    )
    async def _get_compare_cached(
        self,
        session: AsyncSession,
        id: int,
        baseline: schemas.UserCompareBaselineMode,
        target_user_id: int | None,
        role: str | None,
        div_min: int | None,
        div_max: int | None,
        tournament_id: int | None,
        grid_version: int | None,
        *,
        grid: DivisionGrid,
    ) -> schemas.UserCompareResponse:
        # ``session`` and the runtime grid object deliberately stay out of the key.
        # The immutable grid version is enough to prevent cross-version reuse.
        del grid_version
        return await self.get_compare(
            session,
            id,
            schemas.UserCompareParams(
                baseline=baseline,
                target_user_id=target_user_id,
                role=enums.HeroClass(role) if role is not None else None,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
            ),
            grid=grid,
        )

    async def get_compare_cached(
        self,
        session: AsyncSession,
        id: int,
        params: schemas.UserCompareParams,
        *,
        grid: DivisionGrid,
    ) -> schemas.UserCompareResponse:
        is_cohort = params.baseline == "cohort"
        return await self._get_compare_cached(
            session,
            id,
            params.baseline,
            params.target_user_id if params.baseline == "target_user" else None,
            params.role.value if is_cohort and params.role is not None else None,
            params.div_min if is_cohort else None,
            params.div_max if is_cohort else None,
            params.tournament_id,
            grid.version_id,
            grid=grid,
        )

    async def get_hero_compare(
        self,
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
                detail=[
                    errors.ApiExc(code="invalid_filter", msg="target_user_id is required for baseline=target_user.")
                ],
            )

        subject = await self.get(session, id, [])
        target: schemas.UserCompareUser | None = None
        baseline_target: schemas.UserCompareUser | None = None
        sample_size = 0

        requested_stats = [stat for stat in params.stats if stat != enums.LogStatsName.HeroTimePlayed]
        if not requested_stats:
            requested_stats = list(DEFAULT_HERO_COMPARE_STATS)

        left_playtime, left_stats = await self.compare.get_user_hero_compare_stats(
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
            target_model = await self.get(session, params.target_user_id, [])
            right_playtime, right_stats = await self.compare.get_user_hero_compare_stats(
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
            # Population is resolved inside the stats query. The exists probe only
            # tells the two 404s apart, so run it after an empty sample — not on
            # every cache miss.
            baseline_playtime_by_user, baseline_stats_by_user = await self.compare.get_users_hero_compare_stats(
                session,
                user_ids=None,
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
                if not await self.compare.compare_population_exists(
                    session,
                    role=compare_role,
                    div_min=compare_div_min,
                    div_max=compare_div_max,
                    tournament_id=params.tournament_id,
                    grid=grid,
                ):
                    raise errors.ApiHTTPException(
                        status_code=404,
                        detail=[errors.ApiExc(code="not_found", msg="No users found for selected baseline filters.")],
                    )
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

        left_hero_model, right_hero_model, map_model = await self.compare.get_compare_catalog_entities(
            session,
            left_hero_id=params.left_hero_id,
            right_hero_id=params.right_hero_id,
            map_id=params.map_id,
        )
        if params.left_hero_id is not None and left_hero_model is None:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Hero {params.left_hero_id} not found")],
            )
        if params.right_hero_id is not None and right_hero_model is None:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Hero {params.right_hero_id} not found")],
            )
        if params.map_id is not None and map_model is None:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Map with ID {params.map_id} not found")],
            )

        # Local import: ``map.service`` imports this module's ``users`` singleton at
        # module level, so importing it at the top would be a cycle.
        from src.services.map.service import maps as map_service

        left_hero = hero_service.to_read(left_hero_model) if left_hero_model else None
        right_hero = hero_service.to_read(right_hero_model) if right_hero_model else None
        map_value = map_service.to_read(map_model, []) if map_model else None

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

    @cache(
        ttl=config.settings.users_cache_ttl,
        key=(
            "backend:user_hero_compare:v2:{id}:{baseline}:{target_user_id}:{left_hero_id}:"
            "{right_hero_id}:{map_id}:{role}:{div_min}:{div_max}:{tournament_id}:"
            "{stats_key}:{grid_version}"
        ),
        lock=True,
    )
    async def _get_hero_compare_cached(
        self,
        session: AsyncSession,
        id: int,
        baseline: schemas.UserCompareBaselineMode,
        target_user_id: int | None,
        left_hero_id: int | None,
        right_hero_id: int | None,
        map_id: int | None,
        role: str | None,
        div_min: int | None,
        div_max: int | None,
        tournament_id: int | None,
        stats_key: str,
        grid_version: int | None,
        *,
        grid: DivisionGrid,
    ) -> schemas.UserHeroCompareResponse:
        del grid_version
        return await self.get_hero_compare(
            session,
            id,
            schemas.UserHeroCompareParams(
                baseline=baseline,
                target_user_id=target_user_id,
                left_hero_id=left_hero_id,
                right_hero_id=right_hero_id,
                map_id=map_id,
                role=enums.HeroClass(role) if role is not None else None,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                stats=[enums.LogStatsName(value) for value in stats_key.split(",") if value],
            ),
            grid=grid,
        )

    async def get_hero_compare_cached(
        self,
        session: AsyncSession,
        id: int,
        params: schemas.UserHeroCompareParams,
        *,
        grid: DivisionGrid,
    ) -> schemas.UserHeroCompareResponse:
        requested_stats = {stat for stat in params.stats if stat != enums.LogStatsName.HeroTimePlayed}
        if not requested_stats:
            requested_stats = set(DEFAULT_HERO_COMPARE_STATS)
        stats_key = ",".join(sorted(stat.value for stat in requested_stats))
        is_cohort = params.baseline == "cohort"
        return await self._get_hero_compare_cached(
            session,
            id,
            params.baseline,
            params.target_user_id if params.baseline == "target_user" else None,
            params.left_hero_id,
            params.right_hero_id,
            params.map_id,
            params.role.value if is_cohort and params.role is not None else None,
            params.div_min if is_cohort else None,
            params.div_max if is_cohort else None,
            params.tournament_id,
            stats_key,
            grid.version_id,
            grid=grid,
        )

    async def search_by_name(self, session: AsyncSession, name: str, fields: list[str]) -> list[schemas.UserSearch]:
        """Battle-tag autocomplete matches as ``UserSearch`` rows.

        ``fields`` is accepted for API compatibility only; the search always runs on the
        unified battlenet handle.
        """
        users = await self.profile.search_by_name(session, name, fields)
        return [schemas.UserSearch(id=user.user_id, name=user.username) for user in users]

    async def get_read(self, session: AsyncSession, user_id: int, entities: list[str]) -> schemas.UserRead:
        """A user by ID as ``UserRead``, with ``entities`` eager-loaded."""
        user = await self.get(session, user_id, entities)
        return self.to_read(user, entities)

    async def get_roles(
        self,
        session: AsyncSession,
        user_id: int,
        workspace_id: int | None = None,
        *,
        grid: DivisionGrid,
        normalizer: DivisionGridNormalizer | None = None,
        division_grid_version: schemas.DivisionGridVersionRead | None = None,
    ) -> list[schemas.UserRole]:
        """A user's per-role record and current division across tournaments.

        ``grid`` resolves divisions from the raw player rank, and ``workspace_id`` scopes
        the roles to a single workspace when given.
        """
        roles = await self.profile.get_roles(session, user_id, workspace_id=workspace_id)
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
        ttl=config.settings.user_profile_cache_ttl,
        key="backend:user_profile:{id}:{workspace_id}",
    )
    async def get_profile(
        self,
        session: AsyncSession,
        id: int,
        workspace_id: int | None = None,
        *,
        grid: DivisionGrid,
        normalizer: DivisionGridNormalizer | None = None,
    ) -> schemas.UserProfile:
        """A user's profile: overall statistics, roles and tournament history."""
        user = await self.get(session, id, [])
        matches = await self.profile.get_overall_statistics(session, user.id, workspace_id=workspace_id)
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

        roles = await self.get_roles(
            session,
            user.id,
            workspace_id=workspace_id,
            grid=grid,
            normalizer=normalizer,
            division_grid_version=current_grid_version,
        )
        hero_statistics = await hero_service.get_playtime(
            session,
            schemas.HeroPlaytimePaginationParams(user_id=user.id, sort="playtime", order="desc"),
            workspace_id=workspace_id,
        )

        teams, _ = await self.profile.get_teams(
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

            # Participation, not scoring: a live tournament has no final placement
            # yet, but the player is already in it — counting only scored events
            # reported 0 tournaments and collapsed the whole profile into the
            # empty-career panel.
            tournaments_count += 1

            placement = _mappers.resolve_team_placement(team)
            if placement is None:
                continue
            placements.append(placement)
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
        key="backend:user_draft_card:{id}:{workspace_id}",
    )
    async def get_draft_card(
        self, session: AsyncSession, id: int, workspace_id: int | None = None
    ) -> schemas.UserDraftCard:
        """The draft room's player card: career record, roles, signature heroes
        and the last five tournaments.

        Assembled from the reads that already back the profile and Tournaments
        tabs — six queries total, none of them per-tournament. Leagues are left
        out everywhere (they have no placement and no bracket), so every number
        on the card counts the same set of events. A player with no history is a
        card of zeros, never a 404.
        """
        user = await self.get(session, id, [])
        matches = await self.profile.get_overall_statistics(session, user.id, workspace_id=workspace_id)
        maps_won, maps_lost = (matches[0] or 0, matches[1] or 0) if matches else (0, 0)

        # ``Player.role`` is nullable and can be ``flex``; the card only speaks the
        # three draft slot codes, so anything else is dropped rather than guessed at.
        role_rows = [
            (role.slot_code, role_won, role_lost, entries)
            for role, role_won, role_lost, entries in await self.profile.get_roles(
                session, user.id, workspace_id=workspace_id
            )
            if role is not None and role.slot_code in _DRAFT_CARD_ROLE_CODES
        ]
        roles = [
            schemas.UserDraftCardRole(role=code, maps=role_won + role_lost, maps_won=role_won)
            for code, role_won, role_lost, _entries in role_rows
        ]
        roles.sort(key=lambda entry: entry.maps, reverse=True)

        # Which role (and at which rank) the player held per tournament: the role
        # rows already carry one entry per played encounter side, so the most
        # frequent role in a tournament is the one they actually played there.
        weights: Counter[tuple[int, str]] = Counter()
        ranks: dict[tuple[int, str], int | None] = {}
        for code, _won, _lost, entries in role_rows:
            for entry in entries:
                key = (entry["tournament"], code)
                weights[key] += 1
                ranks.setdefault(key, entry["rank"])
        played_as: dict[int, tuple[str, int | None]] = {}
        for (tournament_id, code), _count in weights.most_common():
            played_as.setdefault(tournament_id, (code, ranks[(tournament_id, code)]))

        teams, _ = await self.profile.get_teams(
            session,
            user.id,
            params=pagination.PaginationSortParams(page=1, per_page=-1, entities=["tournament", "placement"]),
            workspace_id=workspace_id,
        )

        placements: list[int] = []
        tournaments_count = 0
        tournaments_won = 0
        recent: dict[int, schemas.UserDraftCardTournament] = {}
        for team in sorted(teams, key=lambda item: item.tournament_id, reverse=True):
            tournament = team.tournament
            if tournament.is_league:
                continue
            tournaments_count += 1
            placement = _mappers.resolve_team_placement(team)
            if placement is not None:
                placements.append(placement)
                if placement == 1:
                    tournaments_won += 1
            if len(recent) >= 5 or tournament.id in recent:
                continue
            role_code, rank = played_as.get(tournament.id, (None, None))
            recent[tournament.id] = schemas.UserDraftCardTournament(
                id=tournament.id,
                name=tournament.name,
                date=tournament.start_date.date() if tournament.start_date else None,
                role=role_code,
                rank=rank,
                placement=placement,
                teams_count=0,
            )

        teams_counts = await self.encounters.count_teams_by_tournament_bulk(session, list(recent))
        for tournament_id, card in recent.items():
            card.teams_count = teams_counts.get(tournament_id, 0)

        hero_rows = await self.encounters.get_user_hero_records(session, user.id, workspace_id=workspace_id)
        mvp_maps = await self.encounters.count_user_mvp_maps(session, user.id, workspace_id=workspace_id)

        return schemas.UserDraftCard(
            tournaments=tournaments_count,
            tournaments_won=tournaments_won,
            maps=maps_won + maps_lost,
            maps_won=maps_won,
            maps_lost=maps_lost,
            mvp_maps=mvp_maps,
            best_placement=min(placements) if placements else None,
            avg_placement=round(mean(placements), 2) if placements else None,
            roles=roles,
            heroes=[
                schemas.UserDraftCardHero(
                    hero=hero_service.to_read(hero),
                    role=hero.type.slot_code,
                    maps=hero_maps,
                    maps_won=hero_maps_won,
                )
                for hero, hero_maps, hero_maps_won in hero_rows
            ],
            recent_tournaments=list(recent.values()),
        )

    @cache(
        ttl=config.settings.users_cache_ttl,
        key="backend:user_tournaments:{id}:{workspace_id}",
    )
    async def get_tournaments(
        self, session: AsyncSession, id: int, workspace_id: int | None = None, *, grid: DivisionGrid
    ) -> list[schemas.UserTournament]:
        """
        Retrieves a user's tournament history with per-event stats (record,
        placement, roster, avg MVP, signature heroes).

        Deliberately does NOT populate `UserTournament.encounters` — that used to
        make this endpoint ship every tournament's full encounter/match history
        (a veteran player's response ran past 1 MB) even though the Tournaments
        tab only ever renders one selected tournament's encounters at a time
        (master-detail dossier). Callers that need the per-match run for one
        tournament call `get_tournament_encounters` lazily instead.
        """
        user = await self.get(session, id, [])
        output: list[schemas.UserTournament] = []
        tournaments = await self.profile.get_tournaments_with_stats(session, user.id, workspace_id=workspace_id)
        tournaments_ids = [tournament[0].tournament_id for tournament in tournaments]
        placements = await self.encounters.count_teams_by_tournament_bulk(session, tournaments_ids)

        # Per-roster-player enrichment (avg MVP + signature heroes), scoped to the
        # tournaments this history covers. Gather every teammate's canonical user id
        # (workspace_member.player_id) up front and resolve both metrics in two bulk
        # queries keyed by (tournament_id, user_id) — no N+1 across roster players.
        roster_user_ids = list(
            {
                player.workspace_member.player_id
                for team, *_ in tournaments
                for player in team.players
                if player.workspace_member is not None
            }
        )
        avg_mvp_map = await self.encounters.get_roster_avg_mvp_bulk(session, tournaments_ids, roster_user_ids)
        top_heroes_map = await self.encounters.get_roster_top_heroes_bulk(session, tournaments_ids, roster_user_ids)

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
                if player.workspace_member is not None and player.workspace_member.player_id == user.id:
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
                schemas.DivisionGridVersionRead.model_validate(
                    team.tournament.division_grid_version, from_attributes=True
                )
                if team.tournament.division_grid_version is not None
                else None
            )

            players_read = [
                _mappers.to_user_tournament_player(
                    player,
                    grid=tournament_grid,
                    avg_mvp=(
                        avg_mvp_map.get((team.tournament_id, player.workspace_member.player_id))
                        if player.workspace_member is not None
                        else None
                    ),
                    heroes=(
                        top_heroes_map.get((team.tournament_id, player.workspace_member.player_id), [])
                        if player.workspace_member is not None
                        else []
                    ),
                )
                for player in team.players
            ]

            tournament = schemas.UserTournament(
                id=team.tournament.id,
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
            )
            output.append(tournament)

        output = sorted(output, key=lambda x: x.id, reverse=True)
        return output

    @cache(
        ttl=config.settings.users_cache_ttl,
        key="backend:user_tournament_encounters:v2:{id}:{tournament_id}",
    )
    async def get_tournament_encounters(
        self, session: AsyncSession, id: int, tournament_id: int
    ) -> list[schemas.EncounterReadWithUserStats]:
        """
        Retrieves one user's encounters (with their per-match stats) within a
        single tournament — the lazy detail behind the Tournaments-tab dossier,
        split out of `get_tournaments` so the list endpoint doesn't have to ship
        every tournament's encounters up front (see that function's docstring).

        Covers every team the user played on in that tournament, if there was more
        than one — e.g. a mid-tournament substitution.
        """
        user = await self.get(session, id, [])
        rows = await self.encounters.get_user_encounter_matches_unpaginated(
            session, user.id, tournament_id=tournament_id
        )

        encounters_cache: dict[int, models.Encounter] = {}
        matches_cache: dict[int, list[schemas.MatchReadWithUserStats]] = {}

        for (
            _team,
            encounter,
            match,
            performance,
            heroes,
            impact_rank,
            impact_points,
            overperformance_score,
            overperf_pos,
        ) in rows:
            encounters_cache.setdefault(encounter.id, encounter)
            matches_cache.setdefault(encounter.id, [])

            if match:
                matches_cache[encounter.id].append(
                    _mappers.to_match_with_user_stats(
                        match,
                        encounter=encounter,
                        performance=performance,
                        heroes=heroes,
                        impact_rank=impact_rank,
                        impact_points=impact_points,
                        overperformance_score=overperformance_score,
                        overperf_pos=overperf_pos,
                    )
                )

        pool_ids = await self.encounters.get_settled_map_ids(session, encounters_cache)
        return [
            _mappers.to_encounter_with_user_stats(
                encounter,
                matches=_mappers.sort_user_matches(
                    matches_cache.get(encounter.id, []),
                    pool_ids.get(encounter.id),
                ),
                viewer_user_id=user.id,
            )
            for encounter in sorted(encounters_cache.values(), key=_mappers.encounter_play_key)
        ]

    # ``grid`` is a pure function of ``tournament_id`` (a tournament pins its own
    # division_grid_version), so it stays out of the key; a grid change fires a
    # TournamentChangedEvent that broadly drops ``user_tournament_stats:*``.
    @cache(
        ttl=config.settings.users_cache_ttl,
        key="backend:user_tournament_stats:{id}:{tournament_id}",
        lock=True,
    )
    async def get_tournament_with_stats(
        self, session: AsyncSession, id: int, tournament_id: int, *, grid: DivisionGrid
    ) -> schemas.UserTournamentWithStats | None:
        """Detailed statistics for a user in one tournament; 404 when the user never
        played in it.
        """
        user = await self.get(session, id, [])
        player = await self.encounters.get_player_by_user_and_tournament(session, user.id, tournament_id)
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
        statistics = await self.profile.get_tournament_stats_overall(session, team.tournament, user.id)
        last_playoff_placement: float | None = None
        last_group_placement: float | None = None
        stats: dict[enums.LogStatsName | typing.Literal["winrate"], schemas.UserTournamentStat] = {}
        winrate = await self.statistics_queries.get_tournament_winrate(session, team.tournament, user.id)

        if winrate:
            stats["winrate"] = schemas.UserTournamentStat(value=winrate[1], rank=winrate[2], total=winrate[3])
        else:
            stats["winrate"] = schemas.UserTournamentStat(value=0, rank=0, total=0)

        for values in await self.statistics_queries.get_tournament_avg_match_stat_for_user_bulk(
            session,
            team.tournament,
            user.id,
            [name for name in tournament_stats if name != enums.LogStatsName.Performance],
        ):
            if not values:
                continue
            stat, _user_id, value, rank_desc, rank_asc, total = values

            rank = rank_asc if enums.is_ascending_stat(stat) else rank_desc

            stats[stat] = schemas.UserTournamentStat(value=value, rank=rank, total=total)

        # MVP placement spans two LogStatsName columns (COALESCE(ImpactRank, Performance) —
        # see get_tournament_mvp_stat_for_user), so it can't ride the generic single-name
        # loop above. Slots into the same "performance" key the frontend already reads.
        mvp_row = await self.statistics_queries.get_tournament_mvp_stat_for_user(session, team.tournament, user.id)
        if mvp_row:
            stats[enums.LogStatsName.Performance] = schemas.UserTournamentStat(
                value=mvp_row.value, rank=mvp_row.rank, total=mvp_row.total
            )

        for placement in team.standings:
            if placement.buchholz is None:
                last_playoff_placement = placement.position
            else:
                last_group_placement = placement.position

        return schemas.UserTournamentWithStats(
            id=team.tournament.id,
            name=team.tournament.name,
            division=resolve_tournament_division(
                player.rank,
                tournament_grid=grid,
            ),
            division_grid_version=_mappers._division_grid_version(team.tournament),
            closeness=round(statistics[2], 2) if statistics[2] else 0,
            role=player.role,
            maps=statistics[0] + statistics[1] if statistics[0] else 0,
            maps_won=statistics[0] if statistics[0] else 0,
            playtime=round(statistics[3], 2) if statistics[3] else 0,
            group_placement=last_group_placement,
            playoff_placement=last_playoff_placement,
            stats=stats,
        )

    async def get_tournament_leaderboard(
        self,
        session: AsyncSession,
        tournament_id: int,
        stat: enums.LogStatsName,
    ) -> schemas.LobbyLeaderboard:
        """Per-stat lobby leaderboard: every player in a tournament ranked by one stat.

        Exposes the full ranked population that backs a single user's
        ``UserTournamentWithStats.stats[stat].{rank,total}`` on the tournament-stats
        page. For every stat except ``Performance`` it reuses the exact ranking
        scheme (``statistics_service.get_tournament_stat_leaderboard``, a
        generalization of ``get_tournament_avg_match_stat_for_user_bulk``) — same
        AVG + dense_rank window and same inverse-stat direction handling — so an
        entry's rank/value here matches that user's row. ``Performance`` is the MVP
        placement stat and spans two ``LogStatsName`` columns (see
        ``get_tournament_mvp_stat_leaderboard`` / ``get_tournament_mvp_stat_for_user``),
        so it routes to its own query instead.

        ``stat`` must be one of the tournament-stats feature's ranked stats
        (``tournament_stats``); any other stat raises 400.
        """
        if stat not in tournament_stats:
            raise errors.ApiHTTPException(
                status_code=400,
                detail=[
                    errors.ApiExc(
                        code="invalid_stat",
                        msg=f"Stat [{stat.value}] is not a ranked tournament stat.",
                    )
                ],
            )

        if stat == enums.LogStatsName.Performance:
            rows = await self.statistics_queries.get_tournament_mvp_stat_leaderboard(session, tournament_id)
        else:
            rows = await self.statistics_queries.get_tournament_stat_leaderboard(session, tournament_id, stat)
        entries = [
            schemas.LobbyLeaderboardEntry(rank=row.rank, player_id=row.user_id, name=row.name, value=row.value)
            for row in rows
        ]
        return schemas.LobbyLeaderboard(stat=stat, total_players=len(entries), entries=entries)

    async def get_heroes(
        self,
        session: AsyncSession,
        id: int,
        params: pagination.PaginationParams,
        stats: list[enums.LogStatsName] | None = None,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
    ) -> pagination.Paginated[schemas.HeroWithUserStats]:
        """Cache wrapper for a user's hero statistics.

        Normalizes the requested-stats list (sort + dedup) into a stable cache key
        before delegating to the cached implementation, so ``[Deaths, Elims]`` and
        ``[Elims, Deaths, Elims]`` share one entry (mirrors the hero-compare cache).
        """
        stats_key = ",".join(sorted({stat.value for stat in (stats or [])}))
        return await self._get_heroes_cached(
            session,
            id,
            params,
            stats_key,
            stats=stats,
            tournament_id=tournament_id,
            workspace_id=workspace_id,
        )

    @cache(
        ttl=config.settings.users_cache_ttl,
        key="backend:user_heroes:{id}:{workspace_id}:{tournament_id}:{stats_key}:{params.page}:{params.per_page}",
        lock=True,
    )
    async def _get_heroes_cached(
        self,
        session: AsyncSession,
        id: int,
        params: pagination.PaginationParams,
        stats_key: str,
        stats: list[enums.LogStatsName] | None = None,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
    ) -> pagination.Paginated[schemas.HeroWithUserStats]:
        """Paginated hero statistics for a user, each stat paired with the global
        per-hero comparison values.
        """
        del stats_key  # participates in the cache key only
        user = await self.get(session, id, [])
        requested_stats = set(stats or [])
        stats_filter = list(requested_stats) if requested_stats else None

        user_stats = await self.profile.get_statistics_by_heroes(
            session, user.id, stats_filter, tournament_id=tournament_id, workspace_id=workspace_id
        )
        all_stats = await self.profile.get_statistics_by_heroes_all_values(session, stats_filter)
        payload: list[schemas.HeroWithUserStats] = []

        stats_by_hero: dict[int, dict[enums.LogStatsName, schemas.HeroStat]] = {}
        cache_hero: dict[int, schemas.HeroRead] = {}

        for name, hero, value, value_best, value_avg_10, best_meta in user_stats:
            if requested_stats and name not in requested_stats and name != enums.LogStatsName.HeroTimePlayed:
                continue
            if hero.id not in cache_hero:
                cache_hero[hero.id] = hero_service.to_read(hero)
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

    @cache(
        ttl=config.settings.users_cache_ttl,
        key="backend:user_teammates:{id}:{workspace_id}:{params.page}:{params.per_page}:{params.sort}:{params.order}",
    )
    async def get_best_teammates(
        self,
        session: AsyncSession,
        id: int,
        params: pagination.PaginationSortParams,
        workspace_id: int | None = None,
    ) -> pagination.Paginated[schemas.UserBestTeammate]:
        """Paginated best teammates for a user with their shared win rate, tournaments
        and performance statistics.
        """
        user = await self.get(session, id, [])
        teammates, total = await self.profile.get_best_teammates(session, user.id, params, workspace_id=workspace_id)
        return pagination.Paginated(
            page=params.page,
            per_page=params.per_page,
            total=total,
            results=[
                schemas.UserBestTeammate(
                    user=self.to_read(teammate, []),
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

    @cache(
        ttl=config.settings.users_cache_ttl,
        key=(
            "backend:user_encounters:v2:{user_id}:{workspace_id}:{params.page}:{params.per_page}:"
            "{params.sort}:{params.order}:{result_filter}:{stage}:{mvp1}:{has_logs}:{opponent}"
        ),
        lock=True,
    )
    async def get_encounters_by_user(
        self,
        session: AsyncSession,
        user_id: int,
        params: pagination.PaginationSortParams,
        workspace_id: int | None = None,
        *,
        result_filter: str | None = None,
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
        user = await self.get(session, user_id, [])
        encounters, total = await self.encounters.get_user_encounters_paginated(
            session,
            user.id,
            params,
            workspace_id=workspace_id,
            result=result_filter,
            stage=stage,
            mvp1=mvp1,
            has_logs=has_logs,
            opponent=opponent,
        )
        encounters_read: list[schemas.EncounterReadWithUserStats] = []
        encounters_cache: dict[int, models.Encounter] = {}
        matches_cache: dict[int, list[schemas.MatchReadWithUserStats]] = {}

        for (
            encounter,
            match,
            performance,
            heroes,
            impact_rank,
            impact_points,
            overperformance_score,
            overperf_pos,
        ) in encounters:
            encounters_cache.setdefault(encounter.id, encounter)
            matches_cache.setdefault(encounter.id, [])

            if match:
                matches_cache[encounter.id].append(
                    _mappers.to_match_with_user_stats(
                        match,
                        encounter=encounter,
                        performance=performance,
                        heroes=heroes,
                        impact_rank=impact_rank,
                        impact_points=impact_points,
                        overperformance_score=overperformance_score,
                        overperf_pos=overperf_pos,
                    )
                )

        pool_ids = await self.encounters.get_settled_map_ids(session, encounters_cache)
        for encounter_id, encounter in encounters_cache.items():
            encounters_read.append(
                _mappers.to_encounter_with_user_stats(
                    encounter,
                    matches=_mappers.sort_user_matches(
                        matches_cache.get(encounter_id, []),
                        pool_ids.get(encounter_id),
                    ),
                    viewer_user_id=user.id,
                )
            )

        return pagination.Paginated(
            total=total,
            per_page=params.per_page,
            page=params.page,
            results=encounters_read,
        )

    @cache(
        ttl=config.settings.users_cache_ttl,
        key="backend:user_matches_summary:{user_id}:{workspace_id}:{opponents_limit}",
    )
    async def get_matches_summary(
        self,
        session: AsyncSession,
        user_id: int,
        workspace_id: int | None = None,
        *,
        opponents_limit: int = 8,
    ) -> schemas.UserMatchesSummary:
        """Most-fought opponents + per-stage win/loss record for the Matches-tab
        sidebars, aggregated over ALL of the user's encounters (not the current
        page, which is what the old client-side computation was limited to)."""
        user = await self.get(session, user_id, [])
        opponent_rows = await self.encounters.get_user_opponents(session, user.id, workspace_id, limit=opponents_limit)
        stage_rows = await self.encounters.get_user_stage_breakdown(session, user.id, workspace_id)

        stages = {kind: schemas.UserStageRecord(w=0, l=0) for kind in ("group", "playoffs", "finals")}
        for row in stage_rows:
            if row.kind in stages:
                stages[row.kind] = schemas.UserStageRecord(w=row.w or 0, l=row.l or 0)

        return schemas.UserMatchesSummary(
            opponents=[
                schemas.UserOpponentStat(
                    name=row.name,
                    wins=row.wins or 0,
                    losses=row.losses or 0,
                    draws=row.draws or 0,
                )
                for row in opponent_rows
                if row.name
            ],
            stages=stages,
        )


users = UserService()
