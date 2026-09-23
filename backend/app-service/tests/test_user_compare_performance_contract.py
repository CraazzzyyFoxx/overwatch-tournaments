"""Query-shape contracts for the optimized user comparison reads."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.dialects import postgresql

from shared.division_grid import DEFAULT_GRID
from src import models, schemas
from src.core import enums, errors, pagination
from src.services.dashboard.service import dashboard as dashboard_service
from src.services.statistics.queries import encounter_query
from src.services.statistics.queries import queries as statistics_queries
from src.services.user import service as user_service
from src.services.user.queries.compare import COMPARE_METRIC_DEFINITIONS
from src.services.user.queries.compare import compare as compare_queries
from src.services.user.queries.overview import overview as overview_queries
from src.services.user.queries.profile import profile as profile_queries


def _postgres_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_overall_compare_v2_is_a_grouped_candidate_query() -> None:
    statement = compare_queries._compare_metrics_query_v2(  # noqa: SLF001 - query contract
        user_ids=None,
        role=None,
        div_min=None,
        div_max=None,
        tournament_id=None,
        grid=DEFAULT_GRID,
    )

    sql = _postgres_sql(statement)

    assert "WITH compare_candidates AS" in sql
    assert "compare_match_stats AS" in sql
    assert "LEFT OUTER JOIN" in sql
    assert "UNION ALL" in sql
    assert "matches.statistics.user_id = players.user.id" not in sql
    assert "home_team_id = tournament.team.id OR" not in sql


def test_compare_population_executes_the_grouped_v2_query() -> None:
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = result

    payload = asyncio.run(
        compare_queries.get_compare_population(
            session,
            user_ids=[7],
            grid=DEFAULT_GRID,
        )
    )

    statement = session.execute.await_args.args[0]
    assert payload == []
    assert "compare_scoped_players AS" in _postgres_sql(statement)


def _compare_row(user_id: int, name: str, value: float) -> dict[str, float | int | str]:
    row: dict[str, float | int | str] = {"id": user_id, "name": name}
    for key, _label, _higher_is_better in COMPARE_METRIC_DEFINITIONS:
        row[key] = value
    return row


def test_target_compare_fetches_both_users_in_one_population_query() -> None:
    rows = [_compare_row(7, "Subject", 10.0), _compare_row(9, "Target", 5.0)]
    get_population = AsyncMock(return_value=rows)
    get_user = AsyncMock(side_effect=[SimpleNamespace(id=7, name="Subject"), SimpleNamespace(id=9, name="Target")])

    with (
        patch.object(compare_queries, "get_compare_population", get_population),
        patch.object(user_service.users, "get", get_user),
    ):
        response = asyncio.run(
            user_service.users.get_compare(
                AsyncMock(),
                7,
                schemas.UserCompareParams(baseline="target_user", target_user_id=9),
                grid=DEFAULT_GRID,
            )
        )

    assert response.subject.id == 7
    assert response.baseline.target_user is not None
    assert response.baseline.target_user.id == 9
    get_population.assert_awaited_once()
    assert get_population.await_args.kwargs["user_ids"] == [7, 9]
    get_user.assert_not_awaited()


def test_hero_compare_v2_combines_playtime_and_stats_in_one_statement() -> None:
    statement = compare_queries._users_hero_compare_query_v2(  # noqa: SLF001 - query contract
        user_ids=[7, 9],
        hero_id=None,
        map_id=None,
        stats=[enums.LogStatsName.Eliminations, enums.LogStatsName.FinalBlows],
        role=None,
        div_min=None,
        div_max=None,
        tournament_id=None,
        grid=DEFAULT_GRID,
    )

    sql = _postgres_sql(statement)

    assert "compare_hero_candidates AS" in sql
    assert "compare_hero_playtime AS" in sql
    assert "compare_hero_stats AS" in sql
    assert "LEFT OUTER JOIN compare_hero_stats" in sql


def test_hero_role_scope_preserves_legacy_team_filter_semantics() -> None:
    statement = compare_queries._users_hero_compare_query_v2(  # noqa: SLF001 - parity contract
        user_ids=[7, 9],
        hero_id=None,
        map_id=None,
        stats=[enums.LogStatsName.Eliminations],
        role=enums.HeroClass.support,
        div_min=None,
        div_max=None,
        tournament_id=None,
        grid=DEFAULT_GRID,
    )

    sql = _postgres_sql(statement)
    assert "compare_hero_scoped_players AS" in sql
    assert "is_finished" not in sql


def test_users_hero_compare_stats_executes_one_statement() -> None:
    async def execute(statement):
        sql = _postgres_sql(statement)
        result = MagicMock()
        if "compare_hero_candidates AS" in sql:
            result.all.return_value = [
                (7, 1200.0, enums.LogStatsName.Eliminations, 18.5),
                (9, 0.0, None, None),
            ]
        elif "playtime_seconds" in sql:
            result.all.return_value = [(7, 1200.0), (9, 0.0)]
        else:
            result.all.return_value = [(7, enums.LogStatsName.Eliminations, 18.5)]
        return result

    session = AsyncMock()
    session.execute.side_effect = execute

    playtime, stats = asyncio.run(
        compare_queries.get_users_hero_compare_stats(
            session,
            user_ids=[7, 9],
            hero_id=None,
            map_id=None,
            stats=[enums.LogStatsName.Eliminations],
            grid=DEFAULT_GRID,
        )
    )

    assert playtime == {7: 1200.0, 9: 0.0}
    assert stats == {(7, enums.LogStatsName.Eliminations): 18.5}
    assert session.execute.await_count == 1


def test_compare_catalog_entities_execute_one_statement() -> None:
    result = MagicMock()
    result.one.return_value = (SimpleNamespace(id=1), SimpleNamespace(id=2), SimpleNamespace(id=3))
    session = AsyncMock()
    session.execute.return_value = result

    entities = asyncio.run(
        compare_queries.get_compare_catalog_entities(
            session,
            left_hero_id=1,
            right_hero_id=2,
            map_id=3,
        )
    )

    assert [entity.id for entity in entities] == [1, 2, 3]
    session.execute.assert_awaited_once()


def test_statistics_by_heroes_defers_metadata_join_off_the_window() -> None:
    """Guard the deferred-metadata-join rewrite (see migration ``herostatmv01``).

    The window function (``hero_stats_ranked``) must rank the slim eligible set
    alone; map/encounter/tournament are joined only for the winning rows in
    ``best_result_cte``. Joining those tables *into* the window CTE ranks the
    full eligible set already fanned out across four tables and blows past
    ``statement_timeout`` for heavy users (Sentry OWT-TOURNAMENTS-2G).
    """
    statement = profile_queries._statistics_by_heroes_query(  # noqa: SLF001 - query contract
        user_id=552,
        stats=None,
        tournament_id=None,
        workspace_id=1,
    )

    sql = _postgres_sql(statement)

    assert "hero_stats_agg AS" in sql
    assert "hero_stats_ranked AS" in sql
    assert "best_result_cte AS" in sql

    # The ranking CTE ranks the slim eligible set with no metadata joins.
    ranked_body = sql.split("hero_stats_ranked AS")[1].split("best_result_cte AS")[0]
    assert "row_number() OVER" in ranked_body
    assert "overwatch.map" not in ranked_body
    assert "tournament.tournament" not in ranked_body
    assert "matches.match " not in ranked_body

    # Metadata is hydrated only for the winning row per (hero, stat).
    assert "FROM hero_stats_ranked JOIN matches.match" in sql
    assert "JOIN overwatch.map" in sql
    assert "WHERE hero_stats_ranked.row_num = 1" in sql


class _Rows:
    def first(self):
        return None

    def all(self):
        return []

    def unique(self):
        return self

    def scalar_one(self):
        return 0

    def one_or_none(self):
        return None


class _CaptureSession:
    def __init__(self) -> None:
        self.statements: list = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Rows()

    async def scalars(self, statement):
        self.statements.append(statement)
        return _Rows()


def _assert_indexable_encounter_join(sql: str) -> None:
    assert "UNION ALL" in sql
    assert "home_team_id = tournament.team.id OR" not in sql


def test_global_compare_runs_population_once_when_subject_is_in_sample() -> None:
    rows = [_compare_row(7, "Subject", 10.0), _compare_row(8, "Other", 5.0)]
    get_population = AsyncMock(return_value=rows)

    with patch.object(compare_queries, "get_compare_population", get_population):
        response = asyncio.run(
            user_service.users.get_compare(
                AsyncMock(),
                7,
                schemas.UserCompareParams(baseline="global"),
                grid=DEFAULT_GRID,
            )
        )

    assert response.subject.id == 7
    get_population.assert_awaited_once()
    assert get_population.await_args.kwargs.get("user_ids") is None


def test_cohort_compare_falls_back_when_subject_missing_from_population() -> None:
    population = [_compare_row(8, "Other", 5.0)]
    subject = [_compare_row(7, "Subject", 10.0)]
    get_population = AsyncMock(side_effect=[population, subject])

    with patch.object(compare_queries, "get_compare_population", get_population):
        response = asyncio.run(
            user_service.users.get_compare(
                AsyncMock(),
                7,
                schemas.UserCompareParams(baseline="cohort", role=enums.HeroClass.tank),
                grid=DEFAULT_GRID,
            )
        )

    assert response.subject.id == 7
    assert get_population.await_count == 2
    assert get_population.await_args_list[0].kwargs.get("user_ids") is None
    assert get_population.await_args_list[1].kwargs["user_ids"] == [7]


def test_hero_compare_skips_exists_probe_when_sample_is_nonempty() -> None:
    get_user = AsyncMock(return_value=SimpleNamespace(id=7, name="Subject"))
    get_left = AsyncMock(return_value=(1200.0, {enums.LogStatsName.Eliminations: 10.0}))
    get_pop = AsyncMock(
        return_value=(
            {8: 900.0, 9: 800.0},
            {
                (8, enums.LogStatsName.Eliminations): 12.0,
                (9, enums.LogStatsName.Eliminations): 8.0,
            },
        )
    )
    exists = AsyncMock(return_value=True)
    catalog = AsyncMock(return_value=(None, None, None))

    with (
        patch.object(user_service.users, "get", get_user),
        patch.object(compare_queries, "get_user_hero_compare_stats", get_left),
        patch.object(compare_queries, "get_users_hero_compare_stats", get_pop),
        patch.object(compare_queries, "compare_population_exists", exists),
        patch.object(compare_queries, "get_compare_catalog_entities", catalog),
    ):
        response = asyncio.run(
            user_service.users.get_hero_compare(
                AsyncMock(),
                7,
                schemas.UserHeroCompareParams(baseline="global"),
                grid=DEFAULT_GRID,
            )
        )

    exists.assert_not_awaited()
    get_pop.assert_awaited_once()
    assert response.baseline.sample_size == 2


def test_hero_compare_empty_sample_without_population_is_baseline_404() -> None:
    get_user = AsyncMock(return_value=SimpleNamespace(id=7, name="Subject"))
    get_left = AsyncMock(return_value=(0.0, {}))
    get_pop = AsyncMock(return_value=({}, {}))
    exists = AsyncMock(return_value=False)

    with (
        patch.object(user_service.users, "get", get_user),
        patch.object(compare_queries, "get_user_hero_compare_stats", get_left),
        patch.object(compare_queries, "get_users_hero_compare_stats", get_pop),
        patch.object(compare_queries, "compare_population_exists", exists),
        pytest.raises(errors.ApiHTTPException) as exc,
    ):
        asyncio.run(
            user_service.users.get_hero_compare(
                AsyncMock(),
                7,
                schemas.UserHeroCompareParams(baseline="global"),
                grid=DEFAULT_GRID,
            )
        )

    exists.assert_awaited_once()
    assert exc.value.status_code == 404
    assert "baseline" in str(exc.value.detail).lower()


def test_hero_compare_empty_sample_with_population_is_hero_map_404() -> None:
    get_user = AsyncMock(return_value=SimpleNamespace(id=7, name="Subject"))
    get_left = AsyncMock(return_value=(0.0, {}))
    get_pop = AsyncMock(return_value=({8: 0.0}, {}))
    exists = AsyncMock(return_value=True)

    with (
        patch.object(user_service.users, "get", get_user),
        patch.object(compare_queries, "get_user_hero_compare_stats", get_left),
        patch.object(compare_queries, "get_users_hero_compare_stats", get_pop),
        patch.object(compare_queries, "compare_population_exists", exists),
        pytest.raises(errors.ApiHTTPException) as exc,
    ):
        asyncio.run(
            user_service.users.get_hero_compare(
                AsyncMock(),
                7,
                schemas.UserHeroCompareParams(baseline="global"),
                grid=DEFAULT_GRID,
            )
        )

    exists.assert_awaited_once()
    assert exc.value.status_code == 404
    assert "hero/map" in str(exc.value.detail).lower()


def test_profile_overall_statistics_uses_union_all_sides() -> None:
    session = _CaptureSession()
    asyncio.run(profile_queries.get_overall_statistics(session, user_id=7))
    _assert_indexable_encounter_join(_postgres_sql(session.statements[0]))


def test_profile_roles_uses_union_all_sides() -> None:
    session = _CaptureSession()
    asyncio.run(profile_queries.get_roles(session, user_id=7))
    _assert_indexable_encounter_join(_postgres_sql(session.statements[0]))


def test_profile_tournaments_with_stats_uses_union_all_sides() -> None:
    session = _CaptureSession()
    asyncio.run(profile_queries.get_tournaments_with_stats(session, user_id=7))
    _assert_indexable_encounter_join(_postgres_sql(session.statements[0]))


def test_profile_tournament_stats_overall_uses_union_all_sides() -> None:
    session = _CaptureSession()
    asyncio.run(profile_queries.get_tournament_stats_overall(session, SimpleNamespace(id=1), user_id=7))
    sql = _postgres_sql(session.statements[0])
    _assert_indexable_encounter_join(sql)
    assert sql.count("UNION ALL") >= 2


def test_profile_best_teammates_uses_union_all_sides() -> None:
    session = _CaptureSession()
    asyncio.run(
        profile_queries.get_best_teammates(
            session,
            user_id=7,
            params=pagination.PaginationSortParams(),
        )
    )
    _assert_indexable_encounter_join(_postgres_sql(session.statements[0]))


def test_get_teams_unlimited_skips_count_and_uses_indexable_exists() -> None:
    session = _CaptureSession()
    asyncio.run(
        profile_queries.get_teams(
            session,
            user_id=7,
            params=pagination.PaginationSortParams(per_page=-1, entities=["tournament", "placement"]),
        )
    )
    assert len(session.statements) == 1
    sql = _postgres_sql(session.statements[0])
    assert "exists" in sql.lower()
    assert "home_team_id = tournament.team.id OR" not in sql


def test_overview_closeness_uses_union_all_sides() -> None:
    session = _CaptureSession()
    asyncio.run(overview_queries.get_overview_averages(session, user_ids=[7]))
    _assert_indexable_encounter_join(_postgres_sql(session.statements[-1]))


def test_statistics_encounter_query_uses_union_all_sides() -> None:
    _assert_indexable_encounter_join(_postgres_sql(encounter_query))


def test_tournament_winrate_uses_union_all_sides() -> None:
    session = _CaptureSession()
    asyncio.run(statistics_queries.get_tournament_winrate(session, SimpleNamespace(id=1), user_id=7))
    sql = _postgres_sql(session.statements[0])
    _assert_indexable_encounter_join(sql)
    assert "nullif" in sql.lower()


def test_active_tournament_stats_is_one_statement() -> None:
    session = _CaptureSession()
    asyncio.run(dashboard_service.get_active_tournament_stats(session, workspace_id=1))
    assert len(session.statements) == 1
    sql = _postgres_sql(session.statements[0])
    assert "active_tournament AS" in sql


def test_overview_encounter_exprs_use_union_all_sides() -> None:
    for expr in (
        overview_queries._overview_avg_closeness_expr(models.User.id, grid=DEFAULT_GRID),
        overview_queries._overview_maps_won_expr(models.User.id, grid=DEFAULT_GRID),
        overview_queries._overview_maps_lost_expr(models.User.id, grid=DEFAULT_GRID),
    ):
        _assert_indexable_encounter_join(_postgres_sql(expr))


def _overview_query_stub():
    overview = MagicMock()
    overview.get_overview_users = AsyncMock(return_value=([SimpleNamespace(id=7, name="Subject")], 1))
    overview.get_catalog_users = AsyncMock(return_value=([("S", [SimpleNamespace(id=7, name="Subject")])], 1, ["S"]))
    overview.get_overview_role_divisions = AsyncMock(return_value={})
    overview.get_overview_tournaments_count = AsyncMock(return_value={})
    overview.get_overview_achievements_count = AsyncMock(return_value={})
    overview.get_overview_averages = AsyncMock(return_value={})
    overview.get_overview_top_heroes = AsyncMock(return_value={})
    overview.get_overview_top_hero_metrics = AsyncMock(return_value={})
    return overview


class _SessionCM:
    def __init__(self, opened: list) -> None:
        self._opened = opened

    async def __aenter__(self):
        session = AsyncMock()
        self._opened.append(session)
        return session

    async def __aexit__(self, *args):
        return False


def test_overview_enrichment_opens_isolated_sessions() -> None:
    overview = _overview_query_stub()
    opened: list = []
    svc = user_service.UserService(overview=overview)
    with patch.object(user_service, "async_session_maker", side_effect=lambda: _SessionCM(opened)):
        result = asyncio.run(svc.get_overview(AsyncMock(), schemas.UserOverviewParams(), grid=DEFAULT_GRID))

    assert len(opened) == 5
    overview.get_overview_top_hero_metrics.assert_awaited_once()
    assert overview.get_overview_top_heroes.await_args.kwargs["limit"] == 5
    assert result.total == 1
    assert result.results[0].id == 7


def test_catalog_enrichment_opens_isolated_sessions_with_hero_limit() -> None:
    overview = _overview_query_stub()
    opened: list = []
    svc = user_service.UserService(overview=overview)
    with patch.object(user_service, "async_session_maker", side_effect=lambda: _SessionCM(opened)):
        result = asyncio.run(svc.get_catalog(AsyncMock(), schemas.UserCatalogParams(), grid=DEFAULT_GRID))

    assert len(opened) == 5
    assert overview.get_overview_top_heroes.await_args.kwargs["limit"] == 3
    overview.get_overview_top_hero_metrics.assert_awaited_once()
    assert result.total == 1
    assert result.letters[0].letter == "S"


def test_overview_skips_enrichment_when_page_is_empty() -> None:
    overview = _overview_query_stub()
    overview.get_overview_users = AsyncMock(return_value=([], 0))
    opened: list = []
    svc = user_service.UserService(overview=overview)
    with patch.object(user_service, "async_session_maker", side_effect=lambda: _SessionCM(opened)):
        result = asyncio.run(svc.get_overview(AsyncMock(), schemas.UserOverviewParams(), grid=DEFAULT_GRID))

    assert opened == []
    overview.get_overview_role_divisions.assert_not_awaited()
    overview.get_overview_top_hero_metrics.assert_not_awaited()
    assert result.results == []
