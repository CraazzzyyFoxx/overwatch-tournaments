import datetime
import typing
from collections import Counter
from statistics import mean

from cashews import cache
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums, errors, pagination
from shared.core.errors import BaseAPIException
from shared.disciplines import DISCIPLINES
from shared.division_grid import DivisionGrid
from shared.repository import TournamentRepository
from shared.schemas.role import RoleRef
from shared.services.cache_generations import versioned
from shared.services.division_grid.access import (
    build_workspace_division_grid_normalizer,
    get_effective_division_grid_version_ids,
    load_division_grid_version_read_payloads,
    load_division_grids,
)
from shared.services.division_grid.normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
)
from shared.services.division_grid.resolution import (
    resolve_tournament_division,
    resolve_workspace_division,
)
from shared.services.realtime import Resource, resource_generation
from shared.services.user_cache import COMPARE_GENERATIONS, user_generations
from src import schemas
from src.core import config
from src.core.workspace import get_division_grid, get_division_grid_version
from src.services.discipline_queries import DisciplineQueries
from src.services.hero.service import heroes as hero_service
from src.services.statistics.queries import StatisticsQueries

from . import _mappers
from .queries.compare import COMPARE_METRIC_DEFINITIONS, UserCompareQueries
from .queries.encounters import UserEncounterQueries
from .queries.overview import UserOverviewQueries
from .queries.profile import UserProfileQueries

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

#: The stats ``get_tournament_player_stats`` ships: what the tournament page shows, a subset of ``tournament_stats``.
tournament_player_stats = [
    enums.LogStatsName.Performance,
    enums.LogStatsName.KDA,
    enums.LogStatsName.Eliminations,
    enums.LogStatsName.Deaths,
    enums.LogStatsName.Assists,
    enums.LogStatsName.HeroDamageDealt,
    enums.LogStatsName.DamageDelta,
]
# A parsed log emits encounters + standings on its tournament's scope; a structure change may drop its matches.
_TOURNAMENT_STATS_GENERATIONS = tuple(
    resource_generation(resource, "{tournament_id}")
    for resource in (
        Resource.TOURNAMENT_ENCOUNTERS,
        Resource.TOURNAMENT_STANDINGS,
        Resource.TOURNAMENT_STRUCTURE,
    )
)

# The stat a character's career-best game (``CharacterWithUserStats.record``) is judged by, per ``attrs["class"]``
# (a ``HeroClass`` member name).
_CHARACTER_RECORD_STAT: dict[str, enums.LogStatsName] = {
    enums.HeroClass.tank.name: enums.LogStatsName.DamageBlocked,
    enums.HeroClass.damage.name: enums.LogStatsName.HeroDamageDealt,
    enums.HeroClass.support.name: enums.LogStatsName.HealingDealt,
}


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


async def _division_grid_version_reads(
    session: AsyncSession,
    version_ids: typing.Iterable[int | None],
) -> dict[int, schemas.DivisionGridVersionRead]:
    """Read models for grid versions a response refers to (cached, one query for misses)."""
    payloads = await load_division_grid_version_read_payloads(
        session,
        {version_id for version_id in version_ids if version_id is not None},
    )
    return {
        version_id: schemas.DivisionGridVersionRead.model_validate(payload) for version_id, payload in payloads.items()
    }


async def _tournament_grid_versions(
    session: AsyncSession,
    tournament_ids: typing.Sequence[int],
) -> tuple[dict[int, int | None], dict[int, schemas.DivisionGridVersionRead]]:
    """Each tournament's effective grid version id, plus those versions' read models."""
    version_by_tournament = await get_effective_division_grid_version_ids(session, tournament_ids)
    return version_by_tournament, await _division_grid_version_reads(session, version_by_tournament.values())


async def _overview_role_divisions(
    session: AsyncSession,
    raw_roles_map: dict[int, list[tuple[RoleRef, int | None, int | None]]],
    *,
    grid: DivisionGrid | None,
    normalizer: DivisionGridNormalizer | None,
    workspace_id: int | None,
) -> tuple[dict[int, list[schemas.UserOverviewRoleDivision]], list[schemas.DivisionGridVersionRead]]:
    """Per-user role divisions, plus the grids those division numbers live on.

    A workspace-scoped read normalizes every rank onto the one workspace grid,
    so all roles share its version. The all-workspaces read arrives with each
    role's canonical number on the game's native ladder already resolved in SQL
    (``None`` without a ladder): an in-code ladder, so no version id and no grid
    to ship.
    """
    if not raw_roles_map:
        # No roles (the cross-game read lists none): no division to resolve, no grid to read.
        return {}, []
    if workspace_id is None:
        return {
            user_id: [schemas.UserOverviewRoleDivision(role=role, division=division) for role, _rank, division in rows]
            for user_id, rows in raw_roles_map.items()
        }, []
    scoped_version_id = normalizer.target_version_id if normalizer is not None else grid.version_id

    roles_by_user: dict[int, list[schemas.UserOverviewRoleDivision]] = {}
    used_version_ids: set[int] = set()
    for user_id, rows in raw_roles_map.items():
        roles: list[schemas.UserOverviewRoleDivision] = []
        for role, rank, version_id in rows:
            if scoped_version_id is not None:
                used_version_ids.add(scoped_version_id)
            roles.append(
                schemas.UserOverviewRoleDivision(
                    role=role,
                    division=resolve_workspace_division(
                        rank,
                        source_version_id=version_id,
                        fallback_grid=grid,
                        normalizer=normalizer,
                    ),
                    division_grid_version_id=scoped_version_id,
                )
            )
        roles_by_user[user_id] = roles

    reads = await _division_grid_version_reads(session, used_version_ids)
    return roles_by_user, [reads[version_id] for version_id in sorted(reads)]


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


class UserService(DisciplineQueries):
    """Orchestrates one game's user statistics; unbound instances serve only identity reads."""

    def __init__(self, discipline: str | None = None) -> None:
        super().__init__(discipline)
        self.profile = UserProfileQueries.of(discipline)
        self.overview = UserOverviewQueries.of(discipline)
        self.compare = UserCompareQueries.of(discipline)
        self.encounters = UserEncounterQueries.of(discipline)
        self.statistics_queries = StatisticsQueries.of(discipline)

    @classmethod
    async def for_tournament(cls, session: AsyncSession, tournament_id: int) -> typing.Self:
        """The instance of the tournament's own game: its owner discipline overrides any browsing choice."""
        owner = await TournamentRepository().get_owner(session, tournament_id)
        if owner is None:
            raise errors.BaseAPIException(status_code=404, detail="Tournament not found")
        return cls.of(owner[1])

    @staticmethod
    def to_read(user: models.User, entities: list[str], *, visible_only: bool = False) -> schemas.UserRead:
        """Convert a `User` to ``UserRead``. Identities come from the unified
        ``user.social_accounts`` relationship and are only accessed (and serialized)
        when an identity entity was requested — and therefore eager-loaded — so this
        never triggers a lazy load outside the async greenlet. The ``battle_tag``/
        ``discord``/``twitch`` entity tokens count as identity requests too.

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

    async def _gather_overview_enrichment(
        self,
        session: AsyncSession,
        user_ids: list[int],
        *,
        workspace_id: int | None,
        top_heroes_limit: int = 5,
    ) -> tuple[
        dict[int, list[tuple[RoleRef | None, int, int | None]]],
        dict[int, int],
        dict[int, int],
        dict[int, tuple[float | None, float | None, float | None, float | None, int | None]],
        dict[int, list[tuple[models.CatalogEntity, float]]],
        dict[int, tuple[int, int, int]],
        dict[int, datetime.datetime | None],
        dict[int, list[str]],
    ]:
        """The independent per-page aggregates of the overview/catalog rows."""
        overview = self.overview
        return (
            await overview.get_overview_role_divisions(session, user_ids, workspace_id=workspace_id),
            await overview.get_overview_tournaments_count(session, user_ids, workspace_id=workspace_id),
            await overview.get_overview_achievements_count(session, user_ids, workspace_id=workspace_id),
            await overview.get_overview_averages(session, user_ids, workspace_id=workspace_id),
            await overview.get_overview_top_heroes(
                session, user_ids, limit=top_heroes_limit, workspace_id=workspace_id
            ),
            await overview.get_overview_map_records(session, user_ids, workspace_id=workspace_id),
            await overview.get_overview_last_active(session, user_ids, workspace_id=workspace_id),
            await overview.get_overview_disciplines(session, user_ids, workspace_id=workspace_id),
        )

    async def get_overview(
        self,
        session: AsyncSession,
        params: schemas.UserOverviewParams,
        workspace_id: int | None = None,
        *,
        grid: DivisionGrid | None,
        normalizer: DivisionGridNormalizer | None = None,
    ) -> schemas.UserOverviewResponse:
        users, total = await self.overview.get_overview_users(session, params, grid, workspace_id=workspace_id)
        if not users:
            return schemas.UserOverviewResponse(
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
            map_records_map,
            last_active_map,
            disciplines_map,
        ) = await self._gather_overview_enrichment(session, user_ids, workspace_id=workspace_id)

        roles_by_user, division_grids = await _overview_role_divisions(
            session,
            raw_roles_map,
            grid=grid,
            normalizer=normalizer,
            workspace_id=workspace_id,
        )

        rows: list[schemas.UserOverviewRow] = []
        for user in users:
            avg_placement, avg_playoff_placement, avg_group_placement, avg_closeness, best_placement = averages_map.get(
                user.id, (None, None, None, None, None)
            )
            maps_won, maps_lost, encounters_played = map_records_map.get(user.id, (0, 0, 0))
            last_active = last_active_map.get(user.id)

            rows.append(
                schemas.UserOverviewRow(
                    id=user.id,
                    name=user.name,
                    avatar_url=user.avatar_url,
                    disciplines=disciplines_map.get(user.id, []),
                    roles=roles_by_user.get(user.id, []),
                    top_characters=[
                        schemas.UserOverviewCharacter(
                            character=hero_service.to_read(hero),
                            playtime_seconds=round(playtime_seconds, 2),
                        )
                        for hero, playtime_seconds in top_heroes_map.get(user.id, [])
                    ],
                    tournaments_count=tournaments_count_map.get(user.id, 0),
                    achievements_count=achievements_count_map.get(user.id, 0),
                    maps_won=maps_won,
                    maps_lost=maps_lost,
                    encounters_played=encounters_played,
                    best_placement=best_placement,
                    last_active_at=last_active.date().isoformat() if last_active is not None else None,
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

        return schemas.UserOverviewResponse(
            page=params.page,
            per_page=params.per_page,
            total=total,
            results=rows,
            division_grids=division_grids,
        )

    async def get_overview_stats(
        self,
        session: AsyncSession,
        params: schemas.UserOverviewStatsQueryParams,
        *,
        grid: DivisionGrid | None,
        workspace_id: int | None = None,
    ) -> schemas.UserOverviewStats:
        payload = await self.overview.get_overview_stats(
            session,
            role=params.role,
            has_role_filter="role" in params.model_fields_set,
            divisions=params.divisions,
            has_logs=params.has_logs,
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
        grid: DivisionGrid | None,
        normalizer: DivisionGridNormalizer | None = None,
        workspace_id: int | None = None,
    ) -> schemas.UserCatalogResponse:
        letters_with_users, total_users, available_letters = await self.overview.get_catalog_users(
            session,
            role=params.role,
            has_role_filter=params.has_role_filter,
            divisions=params.divisions,
            has_logs=params.has_logs,
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
            map_records_map,
            last_active_map,
            disciplines_map,
        ) = await self._gather_overview_enrichment(
            session,
            user_ids,
            workspace_id=workspace_id,
            top_heroes_limit=3,
        )

        roles_by_user, division_grids = await _overview_role_divisions(
            session,
            raw_roles_map,
            grid=grid,
            normalizer=normalizer,
            workspace_id=workspace_id,
        )

        catalog_letters: list[schemas.UserCatalogLetter] = []
        for letter_label, users in letters_with_users:
            entries: list[schemas.UserCatalogEntry] = []
            for user in users:
                avg_placement, _, _, _, best_placement = averages_map.get(user.id, (None, None, None, None, None))
                maps_won, maps_lost, encounters_played = map_records_map.get(user.id, (0, 0, 0))
                last_active = last_active_map.get(user.id)

                entries.append(
                    schemas.UserCatalogEntry(
                        id=user.id,
                        name=user.name,
                        avatar_url=user.avatar_url,
                        disciplines=disciplines_map.get(user.id, []),
                        roles=roles_by_user.get(user.id, []),
                        top_characters=[
                            schemas.UserOverviewCharacter(
                                character=hero_service.to_read(hero),
                                playtime_seconds=round(playtime_seconds, 2),
                            )
                            for hero, playtime_seconds in top_heroes_map.get(user.id, [])
                        ],
                        tournaments_count=tournaments_count_map.get(user.id, 0),
                        achievements_count=achievements_count_map.get(user.id, 0),
                        maps_won=maps_won,
                        maps_lost=maps_lost,
                        encounters_played=encounters_played,
                        best_placement=best_placement,
                        last_active_at=last_active.date().isoformat() if last_active is not None else None,
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
            division_grids=division_grids,
        )

    async def get_compare(
        self,
        session: AsyncSession,
        id: int,
        params: schemas.UserCompareParams,
        *,
        grid: DivisionGrid | None,
        workspace_id: int | None = None,
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
                workspace_id=workspace_id,
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
                workspace_id=workspace_id,
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
                    workspace_id=workspace_id,
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

    @versioned(
        generations=COMPARE_GENERATIONS,
        ttl=config.settings.users_cache_ttl,
        key=(
            "backend:user_compare:v4:{id}:{self.discipline}:{baseline}:{target_user_id}:{role}:{div_min}:{div_max}:"
            "{tournament_id}:{workspace_id}:{grid_version}"
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
        workspace_id: int | None,
        grid_version: int | None,
        *,
        grid: DivisionGrid | None,
    ) -> schemas.UserCompareResponse:
        # ``session`` and the runtime grid object deliberately stay out of the key.
        # The immutable grid version is enough to prevent cross-version reuse, but
        # not cross-workspace reuse: two workspaces can share a grid version, so
        # ``workspace_id`` is keyed on its own.
        del grid_version
        return await self.get_compare(
            session,
            id,
            schemas.UserCompareParams(
                baseline=baseline,
                target_user_id=target_user_id,
                role=RoleRef.model_validate_json(role) if role is not None else None,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
            ),
            grid=grid,
            workspace_id=workspace_id,
        )

    async def get_compare_cached(
        self,
        session: AsyncSession,
        id: int,
        params: schemas.UserCompareParams,
        *,
        grid: DivisionGrid | None,
        workspace_id: int | None = None,
    ) -> schemas.UserCompareResponse:
        is_cohort = params.baseline == "cohort"
        return await self._get_compare_cached(
            session,
            id,
            params.baseline,
            params.target_user_id if params.baseline == "target_user" else None,
            params.role.model_dump_json(exclude={"parent"}) if is_cohort and params.role is not None else None,
            params.div_min if is_cohort else None,
            params.div_max if is_cohort else None,
            params.tournament_id,
            workspace_id,
            grid.version_id if grid is not None else None,
            grid=grid,
        )

    async def get_hero_compare(
        self,
        session: AsyncSession,
        id: int,
        params: schemas.UserCharacterCompareParams,
        *,
        grid: DivisionGrid | None,
        workspace_id: int | None = None,
    ) -> schemas.UserCharacterCompareResponse:
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
        left_hero_model, right_hero_model, map_model = await self.compare.get_compare_catalog_entities(
            session,
            left_hero_id=params.left_entity_id,
            right_hero_id=params.right_entity_id,
            map_id=params.map_id,
        )
        if params.left_entity_id is not None and left_hero_model is None:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Character {params.left_entity_id} not found")],
            )
        if params.right_entity_id is not None and right_hero_model is None:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Character {params.right_entity_id} not found")],
            )
        if params.map_id is not None and map_model is None:
            raise errors.ApiHTTPException(
                status_code=404,
                detail=[errors.ApiExc(code="not_found", msg=f"Map with ID {params.map_id} not found")],
            )
        target: schemas.UserCompareUser | None = None
        baseline_target: schemas.UserCompareUser | None = None
        sample_size = 0

        # No named stats → the game's own comparable vocabulary; a game that declares none compares nothing (empty
        # metrics), never another game's stats.
        requested_stats = [stat for stat in params.stats if stat != enums.LogStatsName.HeroTimePlayed] or list(
            self.compare.comparable_stats
        )

        left_playtime, left_stats = await self.compare.get_user_hero_compare_stats(
            session,
            user_id=subject.id,
            hero_id=params.left_entity_id,
            map_id=params.map_id,
            stats=requested_stats,
            role=compare_role,
            div_min=compare_div_min,
            div_max=compare_div_max,
            tournament_id=params.tournament_id,
            workspace_id=workspace_id,
            grid=grid,
        )
        if left_playtime < 600:
            left_stats = {}

        if mode == "target_user":
            target_model = await self.get(session, params.target_user_id, [])
            right_playtime, right_stats = await self.compare.get_user_hero_compare_stats(
                session,
                user_id=target_model.id,
                hero_id=params.right_entity_id,
                map_id=params.map_id,
                stats=requested_stats,
                tournament_id=params.tournament_id,
                workspace_id=workspace_id,
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
                hero_id=params.right_entity_id,
                map_id=params.map_id,
                stats=requested_stats,
                role=compare_role,
                div_min=compare_div_min,
                div_max=compare_div_max,
                tournament_id=params.tournament_id,
                workspace_id=workspace_id,
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
                    workspace_id=workspace_id,
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

        metrics: list[schemas.UserCharacterCompareMetric] = []
        for stat in requested_stats:
            left_value = float(left_stats.get(stat, 0.0))
            right_value = float(right_stats.get(stat, 0.0))
            delta = left_value - right_value
            higher_is_better = not enums.is_ascending_stat(stat)
            delta_percent = None
            if right_value != 0:
                delta_percent = (delta / abs(right_value)) * 100
            metrics.append(
                schemas.UserCharacterCompareMetric(
                    stat=stat,
                    left_value=round(left_value, 2),
                    right_value=round(right_value, 2),
                    delta=round(delta, 2),
                    delta_percent=round(delta_percent, 2) if delta_percent is not None else None,
                    better_worse=_compute_better_worse(left_value, right_value, higher_is_better),
                    higher_is_better=higher_is_better,
                )
            )

        # Local import: ``map.service`` imports this module's ``users`` singleton at
        # module level, so importing it at the top would be a cycle.
        from src.services.map.service import maps as map_service

        left_hero = hero_service.to_read(left_hero_model) if left_hero_model else None
        right_hero = hero_service.to_read(right_hero_model) if right_hero_model else None
        map_value = map_service.to_read(map_model, []) if map_model else None

        return schemas.UserCharacterCompareResponse(
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
            subject_character=left_hero,
            target_character=right_hero,
            map=map_value,
            left_playtime_seconds=round(left_playtime, 2),
            right_playtime_seconds=round(right_playtime, 2),
            metrics=metrics,
        )

    @versioned(
        generations=COMPARE_GENERATIONS,
        ttl=config.settings.users_cache_ttl,
        key=(
            "backend:user_character_compare:v4:{id}:{self.discipline}:{baseline}:{target_user_id}:{left_hero_id}:"
            "{right_hero_id}:{map_id}:{role}:{div_min}:{div_max}:{tournament_id}:{workspace_id}:"
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
        workspace_id: int | None,
        stats_key: str,
        grid_version: int | None,
        *,
        grid: DivisionGrid | None,
    ) -> schemas.UserCharacterCompareResponse:
        del grid_version
        return await self.get_hero_compare(
            session,
            id,
            schemas.UserCharacterCompareParams(
                baseline=baseline,
                target_user_id=target_user_id,
                left_entity_id=left_hero_id,
                right_entity_id=right_hero_id,
                map_id=map_id,
                role=RoleRef.model_validate_json(role) if role is not None else None,
                div_min=div_min,
                div_max=div_max,
                tournament_id=tournament_id,
                stats=[enums.LogStatsName(value) for value in stats_key.split(",") if value],
            ),
            grid=grid,
            workspace_id=workspace_id,
        )

    async def get_hero_compare_cached(
        self,
        session: AsyncSession,
        id: int,
        params: schemas.UserCharacterCompareParams,
        *,
        grid: DivisionGrid | None,
        workspace_id: int | None = None,
    ) -> schemas.UserCharacterCompareResponse:
        # A character comparison reads player facts: only the game's declared non-team stat codes are comparable.
        declared = {d.code for d in DISCIPLINES[self.discipline].stat_defs if d.group != "team"}
        unknown = sorted(set(params.stats) - declared)
        if unknown:
            raise errors.ApiHTTPException(
                status_code=422,
                detail=[
                    errors.ApiExc(
                        code="stat_not_declared",
                        msg=f"{self.discipline} declares no comparable character stat {', '.join(unknown)}",
                    )
                ],
            )
        requested_stats = {stat for stat in params.stats if stat != enums.LogStatsName.HeroTimePlayed} or set(
            self.compare.comparable_stats
        )
        stats_key = ",".join(sorted(requested_stats))
        is_cohort = params.baseline == "cohort"
        return await self._get_hero_compare_cached(
            session,
            id,
            params.baseline,
            params.target_user_id if params.baseline == "target_user" else None,
            params.left_entity_id,
            params.right_entity_id,
            params.map_id,
            params.role.model_dump_json(exclude={"parent"}) if is_cohort and params.role is not None else None,
            params.div_min if is_cohort else None,
            params.div_max if is_cohort else None,
            params.tournament_id,
            workspace_id,
            stats_key,
            grid.version_id if grid is not None else None,
            grid=grid,
        )

    async def get_roles(
        self,
        session: AsyncSession,
        user_id: int,
        workspace_id: int | None = None,
        *,
        grid: DivisionGrid | None,
        normalizer: DivisionGridNormalizer | None = None,
        division_grid_version: schemas.DivisionGridVersionRead | None = None,
    ) -> list[schemas.UserRole]:
        """A user's per-role record and current division across tournaments.

        ``grid`` resolves divisions from the raw player rank, and ``workspace_id`` scopes
        the roles to a single workspace when given. Without a workspace there is no
        single target grid to normalize to, so each role reports the division — and
        the grid version — of the tournament its latest rank comes from. ``grid`` is
        ``None`` only there, for a game without a system-wide grid: a role whose own
        grid is unknown has no division to report and is left out.

        A sub-role is its parent role's (``damage_hitscan`` is Damage): one row per role, its record pooled across its
        sub-roles and its division from the newest ranked tournament of any of them. Rows come newest-ranked first.
        """
        pooled: dict[RoleRef | None, tuple[int, int, list[dict]]] = {}
        for role, maps_won, maps_lost, entries in await self.profile.get_roles(
            session, user_id, workspace_id=workspace_id
        ):
            parent = None if role is None else RoleRef(dimension=role.dimension, role=role.parent or role.role)
            won, lost, role_entries = pooled.get(parent, (0, 0, []))
            pooled[parent] = (won + maps_won, lost + maps_lost, role_entries + entries)

        # ``recency`` orders every entry newest event first (by start date, not id: see ``get_roles``). The current
        # division is the newest ranked one; a role never ranked keeps its newest entry and resolves to no division.
        latest_by_role = []
        for role, (maps_won, maps_lost, entries) in pooled.items():
            entries.sort(key=lambda entry: entry["recency"])
            latest = next((entry for entry in entries if entry["rank"] is not None), entries[0])
            latest_by_role.append((role, maps_won, maps_lost, entries, latest))
        latest_by_role.sort(key=lambda row: (row[4]["rank"] is None, row[4]["recency"]))

        all_workspaces = workspace_id is None
        source_version_ids = {
            latest_role["division_grid_version_id"]
            for *_rest, latest_role in latest_by_role
            if latest_role["division_grid_version_id"] is not None
        }
        grids_by_version = await load_division_grids(session, source_version_ids) if all_workspaces else {}
        version_reads = await _division_grid_version_reads(session, source_version_ids) if all_workspaces else {}

        payload: list[schemas.UserRole] = []
        for role, maps_won, maps_lost, entries, latest_role in latest_by_role:
            source_version_id = latest_role["division_grid_version_id"]
            source_grid = grids_by_version.get(source_version_id)
            fallback_grid = grid or source_grid
            if fallback_grid is None:
                continue
            payload.append(
                schemas.UserRole(
                    role=role,
                    tournaments=len({item["tournament"] for item in entries}),
                    maps_won=maps_won,
                    maps=maps_won + maps_lost,
                    division=resolve_workspace_division(
                        latest_role["rank"],
                        source_version_id=source_version_id,
                        fallback_grid=fallback_grid,
                        normalizer=normalizer,
                        source_grid=source_grid,
                    ),
                    division_grid_version=(
                        version_reads.get(source_version_id) if all_workspaces else division_grid_version
                    ),
                )
            )
        return payload

    # Cache key intentionally omits `session`, `grid`, `normalizer` — they're
    # either non-hashable runtime fixtures (session) or derivable from workspace_id
    # (grid/normalizer are loaded fresh for the workspace). Workspace-level grid
    # changes are rare; any tournament write that moves a user aggregate misses
    # every ``user_*`` key (``user_cache.TOURNAMENT_DATA``).
    @versioned(
        generations=user_generations("{id}"),
        ttl=config.settings.user_profile_cache_ttl,
        key="backend:user_profile:v2:{id}:{self._discipline}:{workspace_id}:native",
    )
    async def get_profile(
        self,
        session: AsyncSession,
        id: int,
        workspace_id: int | None = None,
        *,
        grid: DivisionGrid | None,
        normalizer: DivisionGridNormalizer | None = None,
    ) -> schemas.UserProfile:
        """A user's profile: overall statistics, roles and tournament history.

        Bound to a game it is that game's profile. Unbound (spec §8.2) the header spans every game, the game-bound
        parts (roles, characters) stay empty and ``games`` carries one summary per game played.
        """
        user = await self.get(session, id, [])
        matches = await self.profile.get_overall_statistics(session, user.id, workspace_id=workspace_id)
        matches_won, matches_lose, avg_closeness = 0, 0, 0
        if matches:
            matches_won, matches_lose, avg_closeness = matches

        roles: list[schemas.UserRole] = []
        hero_statistics = None
        if self._discipline is not None:
            roles = await self._roles_on_game_grid(
                session, user.id, workspace_id=workspace_id, grid=grid, normalizer=normalizer
            )
            hero_statistics = await hero_service.get_playtime(
                session,
                schemas.CharacterPlaytimePaginationParams(user_id=user.id, sort="playtime", order="desc"),
                discipline=self.discipline,
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

        # Narrow tournament summary — only fields the frontend renders on the user overview. Newest event first: the
        # page's "last tournament" is the first card.
        tournaments = [
            _mappers.to_user_tournament_summary(tournament)
            for tournament in sorted(
                (team.tournament for team in teams), key=_mappers.tournament_recency_key, reverse=True
            )
        ]

        for team in teams:
            if team.tournament.is_league:
                continue

            # Participation, not scoring: a live tournament has no final placement
            # yet, but the player is already in it.
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

        games = (
            await self._game_summaries(session, user.id, teams, workspace_id=workspace_id)
            if self._discipline is None
            else []
        )
        return schemas.UserProfile(
            tournaments_count=tournaments_count,
            tournaments_won=tournaments_won,
            maps_total=matches_lose + matches_won,
            maps_won=matches_won,
            avg_placement=round(mean(placements), 2) if placements else None,
            avg_playoff_placement=(round(mean(placements_playoff), 2) if placements_playoff else None),
            avg_group_placement=(round(mean(placements_group), 2) if placements_group else None),
            avg_closeness=round(avg_closeness, 2) if avg_closeness else 0,
            most_played_character=(
                hero_statistics.results[0].entity if hero_statistics is not None and hero_statistics.results else None
            ),
            characters_count=hero_statistics.total if hero_statistics is not None else 0,
            roles=roles,
            character_statistics=hero_statistics.results if hero_statistics is not None else [],
            tournaments=tournaments,
            games=games,
        )

    async def _roles_on_game_grid(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        workspace_id: int | None,
        grid: DivisionGrid | None,
        normalizer: DivisionGridNormalizer | None,
    ) -> list[schemas.UserRole]:
        """This game's per-role record, divisions normalized onto the viewed workspace's grid of the game."""
        if workspace_id is not None and normalizer is None:
            try:
                normalizer = await build_workspace_division_grid_normalizer(
                    session,
                    workspace_id,
                    require_complete=False,
                    discipline=self.discipline,
                )
            except DivisionGridNormalizationError:
                normalizer = None
        current_grid_version_model = await get_division_grid_version(session, workspace_id, discipline=self.discipline)
        current_grid_version = (
            schemas.DivisionGridVersionRead.model_validate(current_grid_version_model, from_attributes=True)
            if current_grid_version_model is not None
            else None
        )
        return await self.get_roles(
            session,
            user_id,
            workspace_id=workspace_id,
            grid=grid,
            normalizer=normalizer,
            division_grid_version=current_grid_version,
        )

    async def _game_summaries(
        self,
        session: AsyncSession,
        user_id: int,
        teams: typing.Sequence[models.Team],
        *,
        workspace_id: int | None,
    ) -> list[schemas.UserGameSummary]:
        """One summary per game played (spec §6.6): most tournaments first, ties in installed order.

        Each game's roles sit on that game's grid; across communities each role keeps its own tournament's grid.
        A game the viewed workspace has no grid for (``division_grid_required``) still gets its card, without roles;
        across communities such a game only drops the roles whose own grid is unknown.
        """
        tallies: dict[str, list[int]] = {}
        for team in teams:
            tally = tallies.setdefault(team.tournament.discipline, [0, 0])
            if team.tournament.is_league:
                continue
            tally[0] += 1
            if _mappers.resolve_team_placement(team) == 1:
                tally[1] += 1
        installed = {code: index for index, code in enumerate(DISCIPLINES)}
        ordered = sorted(tallies, key=lambda code: (-tallies[code][0], installed.get(code, len(installed))))

        summaries: list[schemas.UserGameSummary] = []
        for code in ordered:
            try:
                game_grid = await get_division_grid(session, workspace_id, discipline=code)
            except BaseAPIException as exc:
                if "division_grid_required" not in str(exc.detail):
                    raise
                game_grid = None
            roles = (
                await UserService.of(code)._roles_on_game_grid(
                    session, user_id, workspace_id=workspace_id, grid=game_grid, normalizer=None
                )
                if game_grid is not None or workspace_id is None
                else []
            )
            summaries.append(
                schemas.UserGameSummary(
                    discipline=code,
                    roles=roles,
                    tournaments_count=tallies[code][0],
                    tournaments_won=tallies[code][1],
                )
            )
        return summaries

    @versioned(
        generations=user_generations("{id}"),
        ttl=config.settings.users_cache_ttl,
        key="backend:user_draft_card:{id}:{self.discipline}:{workspace_id}:native",
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

        # Open slots have no role. Keep every assigned discipline-qualified leaf.
        role_rows = [
            (role, role_won, role_lost, entries)
            for role, role_won, role_lost, entries in await self.profile.get_roles(
                session, user.id, workspace_id=workspace_id
            )
            if role is not None
        ]
        roles = [
            schemas.UserDraftCardRole(role=code, maps=role_won + role_lost, maps_won=role_won)
            for code, role_won, role_lost, _entries in role_rows
        ]
        roles.sort(key=lambda entry: entry.maps, reverse=True)

        # Which role (and at which rank) the player held per tournament: the role
        # rows already carry one entry per played encounter side, so the most
        # frequent role in a tournament is the one they actually played there.
        weights: Counter[tuple[int, RoleRef]] = Counter()
        ranks: dict[tuple[int, RoleRef], int | None] = {}
        for code, _won, _lost, entries in role_rows:
            for entry in entries:
                key = (entry["tournament"], code)
                weights[key] += 1
                ranks.setdefault(key, entry["rank"])
        played_as: dict[int, tuple[RoleRef, int | None]] = {}
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
        for team in sorted(teams, key=lambda item: _mappers.tournament_recency_key(item.tournament), reverse=True):
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
            characters=[
                schemas.UserDraftCardCharacter(
                    character=hero_service.to_read(hero),
                    maps=hero_maps,
                    maps_won=hero_maps_won,
                )
                for hero, hero_maps, hero_maps_won, _lost, _drawn in hero_rows
            ],
            recent_tournaments=list(recent.values()),
        )

    @versioned(
        generations=user_generations("{id}"),
        ttl=config.settings.users_cache_ttl,
        key="backend:user_tournaments:v2:{id}:{self._discipline}:{workspace_id}:native",
    )
    async def get_tournaments(
        self, session: AsyncSession, id: int, workspace_id: int | None = None, *, grid: DivisionGrid | None
    ) -> schemas.UserTournamentList:
        """
        Retrieves a user's tournament history with per-event stats (record,
        placement, roster, avg MVP, signature heroes), and each grid version its
        rows' divisions are on, once.

        Ships no encounters: the Tournaments tab renders one selected tournament's
        encounters at a time (master-detail dossier), and every tournament's full
        encounter/match history runs a veteran player's response past 1 MB. Callers
        that need the per-match run for one tournament call
        `get_tournament_encounters` lazily instead.
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
        # Roster MVP and characters are facts of each tournament's own game: read per game (one game when bound).
        tournaments_by_game: dict[str, list[int]] = {}
        for team, *_ in tournaments:
            tournaments_by_game.setdefault(team.tournament.discipline, []).append(team.tournament_id)
        avg_mvp_map: dict[tuple[int, int], float] = {}
        top_characters_map: dict[tuple[int, int], list[models.CatalogEntity]] = {}
        for game, game_tournament_ids in tournaments_by_game.items():
            game_encounters = UserEncounterQueries.of(game)
            avg_mvp_map |= await game_encounters.get_roster_avg_mvp_bulk(session, game_tournament_ids, roster_user_ids)
            top_characters_map |= await game_encounters.get_roster_top_characters_bulk(
                session, game_tournament_ids, roster_user_ids
            )
        version_by_tournament, tournament_version_reads = await _tournament_grid_versions(session, tournaments_ids)
        grids_by_version = await load_division_grids(
            session,
            {version_id for version_id in version_by_tournament.values() if version_id is not None},
        )

        for team, wins, losses, avg_closeness in tournaments:
            user_role: RoleRef | None = None
            user_division: int | None = None
            won: int = 0
            lost: int = 0
            draw: int = 0
            placement = _mappers.resolve_team_placement(team)

            # Each tournament's divisions live on its own effective grid (own pin,
            # else its workspace default, else the system default) — in the
            # all-workspaces read the request grid is not that grid.
            effective_version_id = version_by_tournament.get(team.tournament_id)
            tournament_grid = grids_by_version.get(effective_version_id) or grid

            for player in team.players:
                if player.workspace_member is not None and player.workspace_member.player_id == user.id:
                    user_role = player.role_ref
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

            division_grid_version_id = (
                effective_version_id if effective_version_id in tournament_version_reads else None
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
                    characters=(
                        top_characters_map.get((team.tournament_id, player.workspace_member.player_id), [])
                        if player.workspace_member is not None
                        else []
                    ),
                )
                for player in team.players
            ]

            tournament = schemas.UserTournament(
                id=team.tournament.id,
                name=team.tournament.name,
                workspace_id=team.tournament.workspace_id,
                discipline=team.tournament.discipline,
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
                division_grid_version_id=division_grid_version_id,
                count_teams=placements[team.tournament_id],
                won=won,
                lost=lost,
                draw=draw,
            )
            output.append(tournament)

        return schemas.UserTournamentList(
            results=output,
            division_grid_versions=[
                tournament_version_reads[version_id] for version_id in sorted(tournament_version_reads)
            ],
        )

    @versioned(
        generations=user_generations("{id}"),
        ttl=config.settings.users_cache_ttl,
        key="backend:user_tournament_encounters:v8:{id}:{self.discipline}:{tournament_id}",
    )
    async def get_tournament_encounters(
        self, session: AsyncSession, id: int, tournament_id: int
    ) -> list[schemas.EncounterReadWithUserStats]:
        """
        Retrieves one user's encounters (with their per-match stats) within a
        single tournament — the lazy detail behind the Tournaments-tab dossier, so
        `get_tournaments` doesn't have to ship every tournament's encounters up front.

        Covers every team the user played on in that tournament, if there was more
        than one — e.g. a mid-tournament substitution.
        """
        user = await self.get(session, id, [])
        rows = await self.encounters.get_user_encounter_matches_unpaginated(
            session, user.id, tournament_id=tournament_id
        )

        encounters_by_id: dict[int, models.Encounter] = {}
        match_rows: list[tuple[typing.Any, ...]] = []
        for _team, encounter, match, *stats in rows:
            encounters_by_id.setdefault(encounter.id, encounter)
            if match:
                match_rows.append((encounter.id, match, *stats))
        return await self._map_user_encounters(
            session,
            sorted(encounters_by_id.values(), key=_mappers.encounter_play_key),
            match_rows,
            viewer_user_id=user.id,
        )

    async def _map_user_encounters(
        self,
        session: AsyncSession,
        encounters: list[models.Encounter],
        match_rows: list[tuple[typing.Any, ...]],
        *,
        viewer_user_id: int,
        entities: frozenset[str] = _mappers.ENCOUNTER_ENTITIES,
    ) -> list[schemas.EncounterReadWithUserStats]:
        """Encounters in the given order, each with what ``entities`` expands of its live seats and bracket position,
        and its matches (``match_rows``: ``(encounter_id, match, stats)``) in play order.

        Each match carries its historical game's slots independently of live encounter seats.
        """
        encounter_ids = [encounter.id for encounter in encounters]
        contexts = await self.encounters.get_encounter_contexts(session, encounter_ids, entities)
        matches: dict[int, list[schemas.MatchReadWithUserStats]] = {encounter_id: [] for encounter_id in encounter_ids}
        seen_matches: set[int] = set()
        for encounter_id, match, stats in match_rows:
            # Historical seats can qualify the same observation more than once.
            match_id = match.match.id
            if match_id in seen_matches:
                continue
            seen_matches.add(match_id)
            matches[encounter_id].append(_mappers.to_match_with_user_stats(match, stats))

        return [
            _mappers.to_encounter_with_user_stats(
                encounter,
                contexts[encounter.id],
                matches=_mappers.sort_user_matches(matches[encounter.id]),
                viewer_user_id=viewer_user_id,
                entities=entities,
            )
            for encounter in encounters
        ]

    # ``grid`` is a pure function of ``tournament_id`` (a tournament pins its own
    # division_grid_version), so it stays out of the key; a tournament write that
    # moves a user aggregate misses every ``user_tournament_stats:v2`` key
    # (``user_cache.TOURNAMENT_DATA``).
    @versioned(
        generations=user_generations("{id}"),
        ttl=config.settings.users_cache_ttl,
        key="backend:user_tournament_stats:v2:{id}:{self.discipline}:{tournament_id}:native",
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

        stat_rows, mvp_row = await self.statistics_queries.get_tournament_user_ranks(
            session,
            team.tournament,
            user.id,
            [name for name in tournament_stats if name != enums.LogStatsName.Performance],
        )
        for stat, _user_id, value, rank_desc, rank_asc, total in stat_rows:
            rank = rank_asc if enums.is_ascending_stat(stat) else rank_desc
            stats[stat] = schemas.UserTournamentStat(value=value, rank=rank, total=total)

        # MVP placement spans two LogStatsName columns (COALESCE(ImpactRank, Performance)), so it can't ride the
        # generic single-name ranking above. Slots into the same "performance" key the frontend already reads.
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
            workspace_id=team.tournament.workspace_id,
            discipline=team.tournament.discipline,
            division=resolve_tournament_division(
                player.rank,
                tournament_grid=grid,
            ),
            division_grid_version=_mappers._division_grid_version(team.tournament),
            closeness=round(statistics[2], 2) if statistics[2] else 0,
            role=player.role_ref,
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

    @versioned(
        generations=_TOURNAMENT_STATS_GENERATIONS,
        ttl=config.settings.users_cache_ttl,
        key="backend:tournament_player_stats:{self.discipline}:{tournament_id}",
    )
    async def get_tournament_player_stats(
        self, session: AsyncSession, tournament_id: int
    ) -> schemas.TournamentPlayerStats:
        """Every player's ``get_tournament_leaderboard`` value and rank for ``tournament_player_stats``, pivoted by
        player: the same leaderboards, so a player's numbers here are their leaderboard rows."""
        players: dict[int, dict[str, schemas.TournamentPlayerStat]] = {}
        total = 0
        for stat in tournament_player_stats:
            board = await self.get_tournament_leaderboard(session, tournament_id, stat)
            total = max(total, board.total_players)
            for entry in board.entries:
                players.setdefault(entry.player_id, {})[stat.value] = schemas.TournamentPlayerStat(
                    value=entry.value, rank=entry.rank
                )
        return schemas.TournamentPlayerStats(
            total_players=total,
            players=[schemas.TournamentPlayerStatsRow(player_id=pid, stats=stats) for pid, stats in players.items()],
        )

    async def get_heroes(
        self,
        session: AsyncSession,
        id: int,
        params: pagination.PaginationParams,
        stats: list[enums.LogStatsName] | None = None,
        tournament_id: int | None = None,
        workspace_id: int | None = None,
    ) -> pagination.Paginated[schemas.CharacterWithUserStats]:
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

    @versioned(
        generations=user_generations("{id}"),
        ttl=config.settings.users_cache_ttl,
        key="backend:user_characters:v2:{id}:{self.discipline}:{workspace_id}:{tournament_id}:{stats_key}:{params.page}:{params.per_page}",
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
    ) -> pagination.Paginated[schemas.CharacterWithUserStats]:
        """Paginated hero statistics for a user, each stat paired with the global
        per-hero comparison values, plus the user's game record, every player's
        win rate and the user's career-best game per hero.
        """
        del stats_key  # participates in the cache key only
        user = await self.get(session, id, [])
        requested_stats = set(stats or [])
        stats_filter = list(requested_stats) if requested_stats else None

        user_stats = await self.profile.get_statistics_by_heroes(
            session, user.id, stats_filter, tournament_id=tournament_id, workspace_id=workspace_id
        )
        all_stats = await self.profile.get_statistics_by_heroes_all_values(session, stats_filter)
        payload: list[schemas.CharacterWithUserStats] = []

        stats_by_hero: dict[int, dict[enums.LogStatsName, schemas.CharacterStat]] = {}
        cache_hero: dict[int, schemas.CatalogEntityRead] = {}

        for name, hero, value, value_best, value_avg_10, best_meta in user_stats:
            if requested_stats and name not in requested_stats and name != enums.LogStatsName.HeroTimePlayed:
                continue
            if hero.id not in cache_hero:
                cache_hero[hero.id] = hero_service.to_read(hero)
            if hero.id not in stats_by_hero:
                stats_by_hero[hero.id] = {}
            stats_by_hero[hero.id][name] = schemas.CharacterStat(
                name=name,
                overall=round(value, 2),
                best=schemas.CharacterStatBest(
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
                stats_by_hero[hero_id][name].best_all = schemas.CharacterStatBest(
                    encounter_id=best_meta["encounter_id"],
                    map_name=best_meta["map_name"],
                    value=round(value_best, 2),
                    map_image_path=best_meta["map_image_path"],
                    tournament_name=best_meta["tournament_name"],
                    player_name=best_meta["username"],
                )
                stats_by_hero[hero_id][name].avg_10_all = round(value_avg_10, 2)

        records = {
            hero.id: (games, won, lost, drawn)
            for hero, games, won, lost, drawn in await self.encounters.get_user_hero_records(
                session, user.id, workspace_id=workspace_id, tournament_id=tournament_id
            )
        }
        win_rates_all = await self._get_hero_win_rates_all(session)

        for hero_id, stats in stats_by_hero.items():
            # Gate on playtime, not eliminations: zero eliminations is a valid support pick.
            playtime_stat = stats.get(enums.LogStatsName.HeroTimePlayed)
            if not playtime_stat or playtime_stat.overall <= 0:
                continue

            hero_stats = list(stats.values())
            if requested_stats:
                hero_stats = [hero_stat for hero_stat in hero_stats if hero_stat.name in requested_stats]
                if not hero_stats:
                    continue

            games, win, loss, draw = records.get(hero_id, (0, 0, 0, 0))
            record_stat = _CHARACTER_RECORD_STAT.get(cache_hero[hero_id].attrs.get("class"))
            best = stats[record_stat].best if record_stat is not None and record_stat in stats else None
            payload.append(
                schemas.CharacterWithUserStats(
                    character=cache_hero[hero_id],
                    stats=hero_stats,
                    games=games,
                    win=win,
                    loss=loss,
                    draw=draw,
                    win_rate_all=win_rates_all.get(hero_id),
                    record=None
                    if record_stat is None or best is None or best.value <= 0
                    else schemas.CharacterRecord(
                        stat=record_stat,
                        value=best.value,
                        encounter_id=best.encounter_id,
                        map_name=best.map_name,
                        tournament_name=best.tournament_name,
                    ),
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
        key="backend:hero_win_rates_all:{self.discipline}",
        lock=True,
    )
    async def _get_hero_win_rates_all(self, session: AsyncSession) -> dict[int, float]:
        """Every player's ``win / games`` per hero over the whole discipline (the
        population of ``avg_10_all``), shared by every user's characters read."""
        return {
            hero.id: round(won / games, 4)
            for hero, games, won, _lost, _drawn in await self.encounters.get_user_hero_records(session, None)
        }

    @versioned(
        generations=user_generations("{id}"),
        ttl=config.settings.users_cache_ttl,
        key="backend:user_teammates:{id}:{self.discipline}:{workspace_id}:{params.page}:{params.per_page}:{params.sort}:{params.order}",
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

    @versioned(
        generations=user_generations("{user_id}"),
        ttl=config.settings.users_cache_ttl,
        key=(
            "backend:user_encounters:v8:{user_id}:{self._discipline}:{workspace_id}:{params.page}:{params.per_page}:"
            "{params.sort}:{params.order}:{params.entities}:{result_filter}:{stage}:{mvp1}:{has_logs}:{opponent}"
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

        Returns narrow `EncounterReadWithUserStats` objects expanding only what ``params.entities`` names
        (``_mappers.encounter_entities``): an entity left out is null/empty and never queried.
        """
        user = await self.get(session, user_id, [])
        entities = _mappers.encounter_entities(params.entities)
        encounters, total = await self.encounters.get_user_encounters_paginated(
            session,
            user.id,
            params,
            workspace_id=workspace_id,
            entities=entities,
            result=result_filter,
            stage=stage,
            mvp1=mvp1,
            has_logs=has_logs,
            opponent=opponent,
        )
        encounters_by_id: dict[int, models.Encounter] = {}
        match_rows: list[tuple[typing.Any, ...]] = []
        for encounter, match, *stats in encounters:
            encounters_by_id.setdefault(encounter.id, encounter)
            if match:
                match_rows.append((encounter.id, match, *stats))
        encounters_read = await self._map_user_encounters(
            session, list(encounters_by_id.values()), match_rows, viewer_user_id=user.id, entities=entities
        )

        return pagination.Paginated(
            total=total,
            per_page=params.per_page,
            page=params.page,
            results=encounters_read,
        )

    @versioned(
        generations=user_generations("{user_id}"),
        ttl=config.settings.users_cache_ttl,
        key="backend:user_matches_summary:{user_id}:{self.discipline}:{workspace_id}:{opponents_limit}",
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
        sidebars, aggregated over ALL of the user's encounters, not the current page."""
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
