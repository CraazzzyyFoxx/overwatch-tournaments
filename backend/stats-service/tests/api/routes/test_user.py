"""RPC-handler tests for the /users/* statistics reads.

Each former ``GET /users/...`` HTTP route is now a bespoke typed-RPC handler in
``src/rpc/users.py``; this suite dispatches them via the ``rpc`` harness instead
of an HTTP client. Route -> subject mapping (the identity reads ``GET /users`` and
``GET /users/{name}`` stay in app-service):

- ``GET /users/overview``                 -> ``rpc.stats.users.overview``
- ``GET /users/{id}/compare``             -> ``rpc.stats.users.compare``
- ``GET /users/{id}/compare/characters`` -> ``rpc.stats.users.compare_characters``
- ``GET /users/{id}/profile``             -> ``rpc.stats.users.get_profile``
- ``GET /users/{id}/tournaments``         -> ``rpc.stats.users.tournaments``
- ``GET /users/{id}/tournaments/{tid}``   -> ``rpc.stats.users.tournament``
- ``GET /users/{id}/maps``                -> ``rpc.stats.users.maps``
- ``GET /users/{id}/maps/summary``        -> ``rpc.stats.users.maps_summary``
- ``GET /users/{id}/encounters``          -> ``rpc.stats.users.encounters``
- ``GET /users/{id}/characters``         -> ``rpc.stats.users.characters``
- ``GET /users/{id}/teammates``           -> ``rpc.stats.users.teammates``

Every statistics read names its game (``discipline=overwatch``) and reads across
workspaces with the explicit ``workspace_id=all`` (see :func:`_q`); the owner-scoped
``tournament`` read takes its tournament's game. Assertions mirror the old HTTP
tests against the envelope ``data``. HTTP error statuses map to the envelope
``error.code`` (gateway mapping): 400->bad_request, 404->not_found.
"""

import json

import pytest
from sqlalchemy.orm import Session

from shared import models
from shared.core import enums
from shared.models.catalog.role import CatalogRole, RoleDimension
from shared.models.tournament.player_role import assignment_of
from shared.schemas.role import RoleRef
from tests.conftest import RpcHarness, build_query, seeded_db
from tests.encounter_seed import add_duel, add_observed_game

#: Fixed ids of the compare-division fixture (its rows persist across runs, see ``_ensure_compare_division_fixture``);
#: below 2**31, since ``tournament.standing`` keys its tournament and team as ``integer``.
_COMPARE_FIXTURE_IDS = {
    "subject_user": 1_910_100_001,
    "baseline_user": 1_910_100_002,
    "subject_cohort_tournament": 1_910_100_101,
    "subject_other_tournament": 1_910_100_102,
    "baseline_cohort_tournament": 1_910_100_103,
    "subject_cohort_team": 1_910_100_301,
    "subject_other_team": 1_910_100_302,
    "baseline_cohort_team": 1_910_100_303,
    "subject_cohort_enemy_team": 1_910_100_304,
    "subject_other_enemy_team": 1_910_100_305,
    "baseline_cohort_enemy_team": 1_910_100_306,
    "subject_cohort_player": 1_910_100_401,
    "subject_other_player": 1_910_100_402,
    "baseline_cohort_player": 1_910_100_403,
    "workspace": 1_910_100_901,
    "scoring_rule": 1_910_100_902,
    "subject_cohort_encounter": 1_910_100_601,
    "subject_other_encounter": 1_910_100_602,
    "baseline_cohort_encounter": 1_910_100_603,
    "subject_cohort_match": 1_910_100_701,
    "subject_other_match": 1_910_100_702,
    "baseline_cohort_match": 1_910_100_703,
    "subject_member": 1_910_100_811,
    "baseline_member": 1_910_100_812,
}


def _q(params: dict[str, object] | None = None) -> dict[str, list[str]]:
    """Query of an Overwatch statistics read across every workspace."""
    return build_query({"discipline": "overwatch", "workspace_id": "all", **(params or {})})


def _get_compare_metric(payload: dict[str, object], key: str) -> dict[str, object]:
    return next(metric for metric in payload["metrics"] if metric["key"] == key)


def _ensure_compare_division_fixture(db: Session) -> dict[str, int | str]:
    """A workspace with its own two-tier Overwatch grid (division 1: rank < 2000, division 2: rank >= 2000).

    The subject and the baseline user each play one division-2 (rank 3000) cohort tournament; the subject also plays
    a division-1 (rank 1000) tournament the cohort must leave out. Reads scoped to this workspace see no other data.
    Idempotent (fixed ids, checked before insert); the rows persist across runs.
    """
    ids = _COMPARE_FIXTURE_IDS
    hero_row, map_row = (
        db.query(models.CatalogEntity.id)
        .filter_by(discipline="overwatch", kind=kind)
        .order_by(models.CatalogEntity.id)
        .first()
        for kind in ("character", "map")
    )
    assert hero_row is not None
    assert map_row is not None
    hero_id = hero_row[0]
    map_id = map_row[0]
    role = "damage"
    fixture: dict[str, int | str] = {
        "subject_user_id": ids["subject_user"],
        "workspace_id": ids["workspace"],
        "role": RoleRef(dimension="player_role", role=role).model_dump_json(exclude={"parent"}),
        "division": 2,
        "hero_id": hero_id,
    }
    if db.get(models.User, ids["subject_user"]) is not None:
        return fixture

    leaf = (
        db.query(CatalogRole)
        .join(RoleDimension, CatalogRole.dimension_id == RoleDimension.id)
        .filter(RoleDimension.discipline == "overwatch", RoleDimension.code == "player_role", CatalogRole.code == role)
        .one()
    )

    db.add(models.Workspace(id=ids["workspace"], slug="compare-division-grid-ws", name="Compare Division Workspace"))
    db.flush()
    grid_version = models.DivisionGridVersion(
        grid=models.DivisionGrid(
            workspace_id=ids["workspace"], discipline="overwatch", slug="compare-division", name="Compare Division"
        ),
        version=1,
        label="v1",
        status="published",
        tiers=[
            models.DivisionGridTier(
                slug="low", number=1, name="Low", sort_order=0, rank_min=0, rank_max=1999, icon_url=""
            ),
            models.DivisionGridTier(
                slug="high", number=2, name="High", sort_order=1, rank_min=2000, rank_max=None, icon_url=""
            ),
        ],
    )
    db.add(grid_version)
    db.flush()
    db.add_all(
        [
            models.WorkspaceDivisionGridDefault(
                workspace_id=ids["workspace"], discipline="overwatch", version_id=grid_version.id
            ),
            models.ScoringRule(
                id=ids["scoring_rule"],
                workspace_id=ids["workspace"],
                preset="wins",
                game_formula="win",
                end_formula="games >= best_of",
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            models.User(id=ids["subject_user"], name="compare-division-subject"),
            models.User(id=ids["baseline_user"], name="compare-division-baseline"),
        ]
    )
    db.flush()
    db.add_all(
        [
            models.WorkspaceMember(
                id=ids["subject_member"], workspace_id=ids["workspace"], player_id=ids["subject_user"]
            ),
            models.WorkspaceMember(
                id=ids["baseline_member"], workspace_id=ids["workspace"], player_id=ids["baseline_user"]
            ),
        ]
    )
    db.flush()
    db.add_all(
        [
            models.Tournament(
                id=ids["subject_cohort_tournament"],
                name="Compare Division Subject Cohort",
                slug="compare-division-subject-cohort",
                workspace_id=ids["workspace"],
                is_finished=True,
                is_league=False,
            ),
            models.Tournament(
                id=ids["subject_other_tournament"],
                name="Compare Division Subject Other",
                slug="compare-division-subject-other",
                workspace_id=ids["workspace"],
                is_finished=True,
                is_league=False,
            ),
            models.Tournament(
                id=ids["baseline_cohort_tournament"],
                name="Compare Division Baseline Cohort",
                slug="compare-division-baseline-cohort",
                workspace_id=ids["workspace"],
                is_finished=True,
                is_league=False,
            ),
            models.Team(
                id=ids["subject_cohort_team"],
                balancer_name="compare-subject-cohort",
                name="Compare Subject Cohort",
                captain_id=ids["subject_user"],
                tournament_id=ids["subject_cohort_tournament"],
            ),
            models.Team(
                id=ids["subject_other_team"],
                balancer_name="compare-subject-other",
                name="Compare Subject Other",
                captain_id=ids["subject_user"],
                tournament_id=ids["subject_other_tournament"],
            ),
            models.Team(
                id=ids["baseline_cohort_team"],
                balancer_name="compare-baseline-cohort",
                name="Compare Baseline Cohort",
                captain_id=ids["baseline_user"],
                tournament_id=ids["baseline_cohort_tournament"],
            ),
            models.Team(
                id=ids["subject_cohort_enemy_team"],
                balancer_name="compare-subject-cohort-enemy",
                name="Compare Subject Cohort Enemy",
                captain_id=ids["baseline_user"],
                tournament_id=ids["subject_cohort_tournament"],
            ),
            models.Team(
                id=ids["subject_other_enemy_team"],
                balancer_name="compare-subject-other-enemy",
                name="Compare Subject Other Enemy",
                captain_id=ids["baseline_user"],
                tournament_id=ids["subject_other_tournament"],
            ),
            models.Team(
                id=ids["baseline_cohort_enemy_team"],
                balancer_name="compare-baseline-cohort-enemy",
                name="Compare Baseline Cohort Enemy",
                captain_id=ids["subject_user"],
                tournament_id=ids["baseline_cohort_tournament"],
            ),
            models.Player(
                id=ids["subject_cohort_player"],
                name="compare-division-subject",
                rank=3000,
                assignments=[assignment_of(leaf)],
                tournament_id=ids["subject_cohort_tournament"],
                workspace_member_id=ids["subject_member"],
                team_id=ids["subject_cohort_team"],
            ),
            models.Player(
                id=ids["subject_other_player"],
                name="compare-division-subject",
                rank=1000,
                assignments=[assignment_of(leaf)],
                tournament_id=ids["subject_other_tournament"],
                workspace_member_id=ids["subject_member"],
                team_id=ids["subject_other_team"],
            ),
            models.Player(
                id=ids["baseline_cohort_player"],
                name="compare-division-baseline",
                rank=3000,
                assignments=[assignment_of(leaf)],
                tournament_id=ids["baseline_cohort_tournament"],
                workspace_member_id=ids["baseline_member"],
                team_id=ids["baseline_cohort_team"],
            ),
            models.Standing(
                tournament_id=ids["subject_cohort_tournament"],
                team_id=ids["subject_cohort_team"],
                position=1,
                overall_position=1,
                matches=1,
                win=1,
                draw=0,
                lose=0,
                points=3,
                buchholz=None,
                tb=None,
            ),
            models.Standing(
                tournament_id=ids["subject_other_tournament"],
                team_id=ids["subject_other_team"],
                position=10,
                overall_position=10,
                matches=1,
                win=0,
                draw=0,
                lose=1,
                points=0,
                buchholz=None,
                tb=None,
            ),
            models.Standing(
                tournament_id=ids["baseline_cohort_tournament"],
                team_id=ids["baseline_cohort_team"],
                position=4,
                overall_position=4,
                matches=1,
                win=1,
                draw=0,
                lose=0,
                points=3,
                buchholz=None,
                tb=None,
            ),
        ]
    )
    db.flush()
    add_duel(
        db,
        encounter_id=ids["subject_cohort_encounter"],
        tournament_id=ids["subject_cohort_tournament"],
        workspace_id=ids["workspace"],
        scoring_rule_id=ids["scoring_rule"],
        name="Compare Subject Cohort Encounter",
        seats=[(ids["subject_cohort_team"], 2), (ids["subject_cohort_enemy_team"], 1)],
        closeness=0.75,
    )
    add_duel(
        db,
        encounter_id=ids["subject_other_encounter"],
        tournament_id=ids["subject_other_tournament"],
        workspace_id=ids["workspace"],
        scoring_rule_id=ids["scoring_rule"],
        name="Compare Subject Other Encounter",
        seats=[(ids["subject_other_team"], 2), (ids["subject_other_enemy_team"], 1)],
        closeness=0.5,
    )
    add_duel(
        db,
        encounter_id=ids["baseline_cohort_encounter"],
        tournament_id=ids["baseline_cohort_tournament"],
        workspace_id=ids["workspace"],
        scoring_rule_id=ids["scoring_rule"],
        name="Compare Baseline Cohort Encounter",
        seats=[(ids["baseline_cohort_team"], 2), (ids["baseline_cohort_enemy_team"], 1)],
        closeness=0.65,
    )
    for prefix, member, eliminations, performance in (
        ("subject_cohort", ids["subject_member"], 20, 10),
        ("subject_other", ids["subject_member"], 100, None),
        ("baseline_cohort", ids["baseline_member"], 40, 20),
    ):
        observations = [
            (member, 1, hero_id, enums.LogStatsName.HeroTimePlayed, 600),
            (member, 1, hero_id, enums.LogStatsName.Eliminations, eliminations),
        ]
        if performance is not None:
            observations.append((member, 1, None, enums.LogStatsName.Performance, performance))
        add_observed_game(
            db,
            match_id=ids[f"{prefix}_match"],
            encounter_id=ids[f"{prefix}_encounter"],
            map_entity_id=map_id,
            position=1,
            duration_s=600,
            scores=(2, 1),
            observations=observations,
        )
    db.commit()
    return fixture


@pytest.mark.parametrize(
    (
        "page",
        "per_page",
        "sort",
        "order",
        "query",
        "role",
        "divisions",
        "has_logs",
    ),
    [
        (1, 10, "name", "asc", "", None, None, False),
        (1, 10, "tournaments_count", "desc", "", None, None, False),
        (1, 10, "achievements_count", "desc", "", None, None, False),
        (1, 10, "avg_placement", "asc", "cra", None, None, False),
        (1, 10, "winrate", "desc", "", None, None, True),
        (1, 10, "best_placement", "asc", "", None, None, False),
        (1, 10, "name", "asc", "", {"dimension": "player_role", "role": "damage"}, [8, 9, 10], False),
    ],
)
def test_get_users_overview(
    rpc: RpcHarness,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    query: str,
    role: dict[str, str] | None,
    divisions: list[int] | None,
    has_logs: bool,
) -> None:
    params: dict[str, object] = {
        "page": page,
        "per_page": per_page,
        "sort": sort,
        "order": order,
        "query": query,
        "has_logs": has_logs,
    }
    if role is not None:
        params["role"] = json.dumps(role)
    if divisions is not None:
        params["divisions"] = divisions

    env = rpc.call_sync("rpc.stats.users.overview", {"query": _q(params)})
    assert env["ok"] is True

    content = env["data"]
    assert content["page"] == page
    assert content["per_page"] == per_page
    assert "results" in content

    if content["results"]:
        first = content["results"][0]
        assert "id" in first
        assert "name" in first
        assert "avatar_url" in first
        assert "roles" in first
        assert "top_characters" in first
        assert "tournaments_count" in first
        assert "achievements_count" in first
        assert "maps_won" in first
        assert "maps_lost" in first
        assert "encounters_played" in first
        assert "best_placement" in first
        assert "last_active_at" in first
        assert "averages" in first
        assert len(first["top_characters"]) <= 5
        # top_characters carries playtime only — the per-10 metrics are gone.
        assert all(set(row) == {"character", "playtime_seconds"} for row in first["top_characters"])

        if query:
            assert query.lower() in first["name"].lower()

        if role is not None:
            assert any(
                role_row["role"] is not None
                and role_row["role"]["dimension"] == role["dimension"]
                and (role_row["role"].get("parent") or role_row["role"]["role"]) == role["role"]
                for role_row in first["roles"]
            )

        if divisions is not None:
            assert any(role_row["division"] in divisions for role_row in first["roles"])


def test_get_users_overview_takes_any_ladder_division_but_not_zero(rpc: RpcHarness) -> None:
    # A native ladder numbers its tiers past 20 (Overwatch 40); a division the grid lacks just matches nobody.
    assert rpc.call_sync("rpc.stats.users.overview", {"query": _q({"divisions": [3, 25]})})["ok"] is True
    env = rpc.call_sync("rpc.stats.users.overview", {"query": _q({"divisions": [3, 0]})})
    assert env["ok"] is False
    assert env["error"]["code"] == "unprocessable"


def test_users_overview_without_a_game_lists_the_games_each_row_played(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.overview",
        {"query": build_query({"workspace_id": "all", "per_page": 5, "sort": "tournaments_count", "order": "desc"})},
    )
    assert env["ok"] is True, env

    for row in env["data"]["results"]:
        # Game-bound fields keep their shape and stay empty across games.
        assert row["roles"] == []
        assert row["top_characters"] == []
        if row["tournaments_count"] > 0:
            assert row["disciplines"], row
        assert set(row["disciplines"]) <= {"overwatch", "lol"}
    assert env["data"]["division_grids"] == []


@seeded_db
@pytest.mark.parametrize(("user_id",), [(599,), (79,)])
def test_get_user_compare_global(rpc: RpcHarness, user_id: int) -> None:
    env = rpc.call_sync("rpc.stats.users.compare", {"id": user_id, "query": _q()})
    assert env["ok"] is True

    content = env["data"]
    assert content["subject"]["id"] == user_id
    assert content["baseline"]["mode"] == "global"
    assert content["baseline"]["sample_size"] >= 1
    assert content["metrics"]
    assert "better_worse" in content["metrics"][0]


@seeded_db
def test_get_user_compare_target_user(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.compare",
        {"id": 599, "query": _q({"baseline": "target_user", "target_user_id": 79})},
    )
    assert env["ok"] is True

    content = env["data"]
    assert content["subject"]["id"] == 599
    assert content["baseline"]["mode"] == "target_user"
    assert content["baseline"]["sample_size"] == 1
    assert content["baseline"]["target_user"] is not None
    assert content["baseline"]["target_user"]["id"] == 79
    assert "better_worse" in content["metrics"][0]


@seeded_db
def test_get_user_compare_cohort(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.compare",
        {
            "id": 599,
            "query": _q(
                {
                    "baseline": "cohort",
                    "role": json.dumps({"dimension": "player_role", "role": "damage"}),
                    "div_min": 8,
                    "div_max": 20,
                }
            ),
        },
    )
    assert env["ok"] is True

    content = env["data"]
    assert content["baseline"]["mode"] == "cohort"
    assert content["baseline"]["role"] == {"dimension": "player_role", "role": "damage", "parent": None}
    assert content["baseline"]["div_min"] == 8
    assert content["baseline"]["div_max"] == 20
    assert content["baseline"]["sample_size"] >= 1
    assert "better_worse" in content["metrics"][0]


def test_get_user_compare_cohort_scopes_average_placement_to_matching_division(rpc: RpcHarness, db: Session) -> None:
    fixture = _ensure_compare_division_fixture(db)

    env = rpc.call_sync(
        "rpc.stats.users.compare",
        {
            "id": fixture["subject_user_id"],
            "query": _q(
                {
                    "workspace_id": fixture["workspace_id"],
                    "baseline": "cohort",
                    "role": fixture["role"],
                    "div_min": fixture["division"],
                    "div_max": fixture["division"],
                }
            ),
        },
    )
    assert env["ok"] is True

    content = env["data"]
    metric = _get_compare_metric(content, "avg_placement")

    assert content["baseline"]["sample_size"] == 2
    assert metric["subject_value"] == pytest.approx(1.0)
    assert metric["baseline_value"] == pytest.approx(2.5)


@seeded_db
def test_get_user_character_compare(rpc: RpcHarness) -> None:
    left_env = rpc.call_sync("rpc.stats.users.characters", {"id": 599, "query": _q({"per_page": 1})})
    right_env = rpc.call_sync("rpc.stats.users.characters", {"id": 79, "query": _q({"per_page": 1})})
    assert left_env["ok"] is True
    assert right_env["ok"] is True

    left_characters = left_env["data"]["results"]
    right_characters = right_env["data"]["results"]
    assert left_characters
    assert right_characters

    env = rpc.call_sync(
        "rpc.stats.users.compare_characters",
        {
            "id": 599,
            "query": _q(
                {
                    "baseline": "target_user",
                    "target_user_id": 79,
                    "left_entity_id": left_characters[0]["character"]["id"],
                    "right_entity_id": right_characters[0]["character"]["id"],
                    "stats": ["eliminations", "final_blows", "hero_damage_dealt", "healing_dealt"],
                }
            ),
        },
    )
    assert env["ok"] is True

    content = env["data"]
    assert content["subject"]["id"] == 599
    assert content["target"] is not None
    assert content["target"]["id"] == 79
    assert content["baseline"]["mode"] == "target_user"
    assert content["baseline"]["sample_size"] == 1
    assert content["subject_character"] is not None
    assert content["target_character"] is not None
    assert len(content["metrics"]) == 4
    assert "higher_is_better" in content["metrics"][0]
    assert "better_worse" in content["metrics"][0]


def test_get_user_character_compare_cohort_scopes_stats_to_matching_division(rpc: RpcHarness, db: Session) -> None:
    fixture = _ensure_compare_division_fixture(db)

    env = rpc.call_sync(
        "rpc.stats.users.compare_characters",
        {
            "id": fixture["subject_user_id"],
            "query": _q(
                {
                    "workspace_id": fixture["workspace_id"],
                    "baseline": "cohort",
                    "role": fixture["role"],
                    "div_min": fixture["division"],
                    "div_max": fixture["division"],
                    "left_entity_id": fixture["hero_id"],
                    "right_entity_id": fixture["hero_id"],
                    "stats": ["eliminations"],
                }
            ),
        },
    )
    assert env["ok"] is True

    content = env["data"]
    metric = content["metrics"][0]

    assert content["baseline"]["sample_size"] == 2
    assert metric["stat"] == "eliminations"
    assert metric["left_value"] == pytest.approx(20.0)
    assert metric["right_value"] == pytest.approx(30.0)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known gap: a character compare reads only facts of a character played > 60 s, so the player-total "
        "performance rank -- the only one native ingest writes -- never reaches a compare without a character. "
        "test_stats_reader_parity's frozen P3 golden pins that operand pool; a fix re-baselines it."
    ),
)
def test_get_user_character_compare_includes_performance_without_character_filter(rpc: RpcHarness, db: Session) -> None:
    fixture = _ensure_compare_division_fixture(db)

    env = rpc.call_sync(
        "rpc.stats.users.compare_characters",
        {
            "id": fixture["subject_user_id"],
            "query": _q(
                {
                    "workspace_id": fixture["workspace_id"],
                    "baseline": "cohort",
                    "role": fixture["role"],
                    "div_min": fixture["division"],
                    "div_max": fixture["division"],
                    "stats": ["performance"],
                }
            ),
        },
    )
    assert env["ok"] is True

    content = env["data"]
    assert len(content["metrics"]) == 1
    metric = content["metrics"][0]

    assert metric["stat"] == "performance"
    assert metric["left_value"] == pytest.approx(10.0)
    assert metric["right_value"] == pytest.approx(15.0)


@seeded_db
def test_get_user_character_compare_global_baseline(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.compare_characters",
        {
            "id": 599,
            "query": _q(
                {
                    "baseline": "global",
                    "stats": ["eliminations", "final_blows"],
                }
            ),
        },
    )
    assert env["ok"] is True

    content = env["data"]
    assert content["subject"]["id"] == 599
    assert content["target"] is None
    assert content["baseline"]["mode"] == "global"
    assert content["baseline"]["sample_size"] >= 1
    assert len(content["metrics"]) == 2


@seeded_db
def test_get_user_character_compare_ascending_stat_better_worse(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.compare_characters",
        {
            "id": 599,
            "query": _q(
                {
                    "baseline": "global",
                    "stats": ["deaths"],
                }
            ),
        },
    )
    assert env["ok"] is True

    content = env["data"]
    assert len(content["metrics"]) == 1

    metric = content["metrics"][0]
    assert metric["stat"] == "deaths"
    assert metric["higher_is_better"] is False

    left_value = metric["left_value"]
    right_value = metric["right_value"]
    better_worse = metric["better_worse"]

    if left_value == right_value:
        assert better_worse == "equal"
    elif left_value < right_value:
        assert better_worse == "better"
    else:
        assert better_worse == "worse"


@seeded_db
@pytest.mark.parametrize(
    ("user_id",),
    [
        (599,),
        (79,),
        (461,),
        (583,),
    ],
)
def test_get_user_profile(rpc: RpcHarness, user_id: int) -> None:
    env = rpc.call_sync("rpc.stats.users.get_profile", {"id": user_id, "query": _q()})
    assert env["ok"] is True
    content = env["data"]
    assert content["tournaments"].__len__() >= 0


@seeded_db
@pytest.mark.parametrize(
    ("user_id",),
    [
        (599,),
        (79,),
        (461,),
        (583,),
    ],
)
def test_get_user_tournaments(rpc: RpcHarness, user_id: int) -> None:
    env = rpc.call_sync("rpc.stats.users.tournaments", {"id": user_id, "query": _q()})
    assert env["ok"] is True
    content = env["data"]
    versions = {version["id"] for version in content["division_grid_versions"]}
    assert {row["division_grid_version_id"] for row in content["results"]} - {None} == versions


@seeded_db
@pytest.mark.parametrize(
    ("user_id", "tournament_id"),
    [
        (599, 36),
        (79, 3),
        (461, 10),
        (583, 18),
    ],
)
def test_get_user_tournament(rpc: RpcHarness, user_id: int, tournament_id: int) -> None:
    env = rpc.call_sync("rpc.stats.users.tournament", {"id": user_id, "tournament_id": tournament_id})
    assert env["ok"] is True
    content = env["data"]
    assert content.__len__() >= 0


@seeded_db
@pytest.mark.parametrize(
    ("user_id", "tournament_id"),
    [
        (599, 3),
        (79, 36),
        (461, 14),
        (583, 14),
    ],
)
def test_get_user_tournament_not_found(rpc: RpcHarness, user_id: int, tournament_id: int) -> None:
    env = rpc.call_sync("rpc.stats.users.tournament", {"id": user_id, "tournament_id": tournament_id})
    assert env["ok"] is False
    assert env["error"]["code"] == "not_found"


@seeded_db
@pytest.mark.parametrize(
    ("user_id", "page", "per_page", "sort", "order", "entities"),
    [
        (599, 1, 10, "id", "desc", []),
        (599, 1, 25, "name", "desc", ["parent"]),
        (599, 1, 10, "winrate", "desc", ["character_stats"]),
        (79, 1, 10, "id", "desc", []),
        (461, 1, 10, "name", "desc", []),
        (461, 1, 25, "mode_id", "desc", ["parent"]),
        (583, 1, 10, "name", "desc", []),
        (583, 1, 25, "slug", "desc", ["parent"]),
    ],
)
def test_get_user_maps(
    rpc: RpcHarness,
    user_id: int,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    entities: list[str],
) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.maps",
        {
            "id": user_id,
            "query": _q(
                {
                    "page": page,
                    "per_page": per_page,
                    "sort": sort,
                    "order": order,
                    "entities": entities,
                }
            ),
        },
    )
    assert env["ok"] is True
    content = env["data"]
    assert content["page"] == page
    assert content["per_page"] == per_page

    if "parent" in entities:
        assert content["results"][0]["map"]["parent"]
    else:
        if content["results"]:
            assert content["results"][0]["map"]["parent"] is None

    if "character_stats" in entities and content["results"]:
        assert content["results"][0]["character_stats"] is not None


@seeded_db
@pytest.mark.parametrize(
    ("user_id", "entities", "min_count"),
    [
        (599, [], None),
        (599, ["parent"], 3),
        (79, [], 1),
    ],
)
def test_get_user_maps_summary(rpc: RpcHarness, user_id: int, entities: list[str], min_count: int | None) -> None:
    params: dict[str, object] = {
        "entities": entities,
    }
    if min_count is not None:
        params["min_count"] = min_count

    env = rpc.call_sync("rpc.stats.users.maps_summary", {"id": user_id, "query": _q(params)})
    assert env["ok"] is True
    content = env["data"]

    assert "overall" in content
    assert "total_maps" in content["overall"]
    assert "total_games" in content["overall"]

    if "parent" in entities:
        if content.get("most_played") is not None:
            assert content["most_played"]["map"]["parent"]


@seeded_db
@pytest.mark.parametrize(
    ("user_id", "page", "per_page", "sort", "order", "entities"),
    [
        (599, 1, 10, "id", "desc", []),
        (599, 1, 25, "id", "desc", ["tournament"]),
        # (599, 1, 25, "name", "desc", ["tournament", "teams", "teams.players"]),
        (599, 1, 25, "id", "desc", ["tournament", "teams"]),
        (79, 1, 10, "id", "desc", []),
        (79, 1, 25, "closeness", "desc", ["tournament"]),
        # (79, 1, 25, "round", "desc", ["tournament", "teams", "teams.players"]),
        (79, 1, 25, "round", "desc", ["tournament", "teams"]),
        (461, 1, 10, "name", "desc", []),
        (461, 1, 25, "round", "desc", ["tournament"]),
        # (461, 1, 25, "round", "desc", ["tournament", "teams", "teams.players"]),
        (461, 1, 25, "closeness", "desc", ["tournament", "teams"]),
        (583, 1, 10, "closeness", "desc", []),
        # (583, 1, 25, "tournament_id", "desc", ["tournament", "teams", "teams.players"]),
        (583, 1, 25, "round", "desc", ["tournament", "teams"]),
    ],
)
def test_get_user_encounters(
    rpc: RpcHarness,
    user_id: int,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    entities: list[str],
) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.encounters",
        {
            "id": user_id,
            "query": _q(
                {
                    "page": page,
                    "per_page": per_page,
                    "sort": sort,
                    "order": order,
                    "entities": entities,
                }
            ),
        },
    )
    assert env["ok"] is True, env
    content = env["data"]
    assert content["page"] == page
    assert content["per_page"] == per_page

    # The live seats ride only when ``teams`` is asked for, in slot order; nothing else gates them.
    for encounter in content["results"]:
        assert "home_team" not in encounter and "away_team" not in encounter
        if "teams" not in entities:
            assert encounter["teams"] == []
            continue
        assert [team["slot"] for team in encounter["teams"]] == list(range(1, encounter["slot_count"] + 1))
        for team in encounter["teams"]:
            assert team["name"]
            assert isinstance(team["players"], list)

    if "tournament" in entities:
        assert content["results"][0]["tournament"]
    else:
        if content["results"]:
            assert content["results"][0]["tournament"] is None


@seeded_db
@pytest.mark.parametrize(("user_id",), [(599,), (79,), (461,), (583,)])
def test_get_user_characters(rpc: RpcHarness, user_id: int) -> None:
    env = rpc.call_sync("rpc.stats.users.characters", {"id": user_id, "query": _q()})
    assert env["ok"] is True


@seeded_db
@pytest.mark.parametrize(
    ("user_id", "page", "per_page", "sort", "order"),
    [
        (
            599,
            1,
            10,
            "id",
            "asc",
        ),
        (599, 1, 25, "winrate", "desc"),
        (599, 1, 25, "winrate", "asc"),
        (
            79,
            1,
            10,
            "id",
            "asc",
        ),
        (79, 1, 25, "winrate", "desc"),
        (79, 1, 25, "winrate", "asc"),
        (
            461,
            1,
            10,
            "id",
            "asc",
        ),
        (461, 1, 25, "winrate", "desc"),
        (461, 1, 25, "winrate", "asc"),
        (
            583,
            1,
            10,
            "id",
            "asc",
        ),
        (583, 1, 25, "winrate", "desc"),
        (583, 1, 25, "winrate", "asc"),
    ],
)
def test_get_user_teammates(rpc: RpcHarness, user_id: int, page: int, per_page: int, sort: str, order: str) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.teammates",
        {
            "id": user_id,
            "query": _q(
                {
                    "page": page,
                    "per_page": per_page,
                    "sort": sort,
                    "order": order,
                }
            ),
        },
    )
    assert env["ok"] is True
    content = env["data"]
    assert content["page"] == page
    assert content["per_page"] == per_page

    if content["results"] and "winrate" == sort:
        if order == "desc":
            assert content["results"][0]["winrate"] >= content["results"][-1]["winrate"]
        else:
            assert content["results"][0]["winrate"] <= content["results"][-1]["winrate"]


@seeded_db
def test_get_user_characters_with_stats(rpc: RpcHarness) -> None:
    user_id = 599
    env = rpc.call_sync(
        "rpc.stats.users.characters",
        {"id": user_id, "query": _q({"stats": ["deaths", "eliminations"]})},
    )
    assert env["ok"] is True
