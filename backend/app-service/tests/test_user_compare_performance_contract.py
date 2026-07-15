"""Query-shape contracts for the optimized user comparison reads."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql

from shared.division_grid import DEFAULT_GRID
from src import schemas
from src.core import enums
from src.services.user import flows, service


def _postgres_sql(statement) -> str:
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def test_overall_compare_v2_is_a_grouped_candidate_query() -> None:
    statement = service._compare_metrics_query_v2(  # noqa: SLF001 - query contract
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
    assert "matches.statistics.user_id = players.user.id" not in sql


def test_compare_population_executes_the_grouped_v2_query() -> None:
    result = MagicMock()
    result.mappings.return_value.all.return_value = []
    session = AsyncMock()
    session.execute.return_value = result

    payload = asyncio.run(
        service.get_compare_population(
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
    for key, _label, _higher_is_better in service.COMPARE_METRIC_DEFINITIONS:
        row[key] = value
    return row


def test_target_compare_fetches_both_users_in_one_population_query() -> None:
    rows = [_compare_row(7, "Subject", 10.0), _compare_row(9, "Target", 5.0)]
    get_population = AsyncMock(return_value=rows)
    get_user = AsyncMock(side_effect=[SimpleNamespace(id=7, name="Subject"), SimpleNamespace(id=9, name="Target")])

    with (
        patch.object(service, "get_compare_population", get_population),
        patch.object(flows, "get", get_user),
    ):
        response = asyncio.run(
            flows.get_compare(
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
    statement = service._users_hero_compare_query_v2(  # noqa: SLF001 - query contract
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
    statement = service._users_hero_compare_query_v2(  # noqa: SLF001 - parity contract
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
        service.get_users_hero_compare_stats(
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
        service.get_compare_catalog_entities(
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
    statement = service._statistics_by_heroes_query(  # noqa: SLF001 - query contract
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
