import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src import models
from src.core import config, enums


_COMPARE_FIXTURE_IDS = {
    "subject_user": 9_100_000_001,
    "baseline_user": 9_100_000_002,
    "subject_cohort_tournament": 9_100_000_101,
    "subject_other_tournament": 9_100_000_102,
    "baseline_cohort_tournament": 9_100_000_103,
}


def _get_compare_metric(payload: dict[str, object], key: str) -> dict[str, object]:
    return next(metric for metric in payload["metrics"] if metric["key"] == key)


def _skip_if_compare_test_db_unavailable(db: Session) -> None:
    bind = db.get_bind()
    if bind.url.host in {None, "\\.135.214.75"}:
        pytest.skip("DB is not reachable in this environment for compare regression fixture setup")


def _pick_unused_role_division_pair(db: Session) -> tuple[enums.HeroClass, int]:
    existing_pairs = {
        (role, division)
        for role, division in db.query(models.Player.role, models.Player.div).distinct().all()
        if role is not None
    }

    for role in enums.HeroClass:
        for division in range(1, 21):
            if (role, division) not in existing_pairs:
                return role, division

    raise AssertionError("Could not find an unused role/division pair for compare regression tests")


def _ensure_compare_division_fixture(db: Session) -> dict[str, int | str]:
    subject_user_id = _COMPARE_FIXTURE_IDS["subject_user"]
    subject_user = db.get(models.User, subject_user_id)
    if subject_user is not None:
        existing_subject_performance = db.get(models.MatchStatistics, 9_100_000_807)
        existing_baseline_performance = db.get(models.MatchStatistics, 9_100_000_808)
        if existing_subject_performance is None:
            db.add(
                models.MatchStatistics(
                    id=9_100_000_807,
                    match_id=9_100_000_701,
                    round=0,
                    team_id=9_100_000_301,
                    user_id=subject_user_id,
                    hero_id=None,
                    name=enums.LogStatsName.Performance,
                    value=10,
                )
            )
        if existing_baseline_performance is None:
            db.add(
                models.MatchStatistics(
                    id=9_100_000_808,
                    match_id=9_100_000_703,
                    round=0,
                    team_id=9_100_000_303,
                    user_id=_COMPARE_FIXTURE_IDS["baseline_user"],
                    hero_id=None,
                    name=enums.LogStatsName.Performance,
                    value=20,
                )
            )
        if existing_subject_performance is None or existing_baseline_performance is None:
            db.commit()

        cohort_player = (
            db.query(models.Player)
            .filter(models.Player.user_id == subject_user_id)
            .filter(models.Player.tournament_id == _COMPARE_FIXTURE_IDS["subject_cohort_tournament"])
            .one()
        )
        hero_id = db.query(models.Hero.id).order_by(models.Hero.id).first()[0]
        return {
            "subject_user_id": subject_user_id,
            "role": cohort_player.role.value,
            "division": cohort_player.div,
            "hero_id": hero_id,
        }

    role, division = _pick_unused_role_division_pair(db)
    other_division = 1 if division != 1 else 2
    hero_row = db.query(models.Hero.id).order_by(models.Hero.id).first()
    map_row = db.query(models.Map.id).order_by(models.Map.id).first()
    assert hero_row is not None
    assert map_row is not None
    hero_id = hero_row[0]
    map_id = map_row[0]

    ids = {
        "subject_user": _COMPARE_FIXTURE_IDS["subject_user"],
        "baseline_user": _COMPARE_FIXTURE_IDS["baseline_user"],
        "subject_cohort_tournament": _COMPARE_FIXTURE_IDS["subject_cohort_tournament"],
        "subject_other_tournament": _COMPARE_FIXTURE_IDS["subject_other_tournament"],
        "baseline_cohort_tournament": _COMPARE_FIXTURE_IDS["baseline_cohort_tournament"],
        "subject_cohort_group": 9_100_000_201,
        "subject_other_group": 9_100_000_202,
        "baseline_cohort_group": 9_100_000_203,
        "subject_cohort_team": 9_100_000_301,
        "subject_other_team": 9_100_000_302,
        "baseline_cohort_team": 9_100_000_303,
        "subject_cohort_enemy_team": 9_100_000_304,
        "subject_other_enemy_team": 9_100_000_305,
        "baseline_cohort_enemy_team": 9_100_000_306,
        "subject_cohort_player": 9_100_000_401,
        "subject_other_player": 9_100_000_402,
        "baseline_cohort_player": 9_100_000_403,
        "subject_cohort_standing": 9_100_000_501,
        "subject_other_standing": 9_100_000_502,
        "baseline_cohort_standing": 9_100_000_503,
        "subject_cohort_encounter": 9_100_000_601,
        "subject_other_encounter": 9_100_000_602,
        "baseline_cohort_encounter": 9_100_000_603,
        "subject_cohort_match": 9_100_000_701,
        "subject_other_match": 9_100_000_702,
        "baseline_cohort_match": 9_100_000_703,
        "subject_cohort_playtime": 9_100_000_801,
        "subject_cohort_eliminations": 9_100_000_802,
        "subject_other_playtime": 9_100_000_803,
        "subject_other_eliminations": 9_100_000_804,
        "baseline_cohort_playtime": 9_100_000_805,
        "baseline_cohort_eliminations": 9_100_000_806,
        "subject_cohort_performance": 9_100_000_807,
        "baseline_cohort_performance": 9_100_000_808,
    }

    db.add_all(
        [
            models.User(id=ids["subject_user"], name="compare-division-subject"),
            models.User(id=ids["baseline_user"], name="compare-division-baseline"),
            models.Tournament(
                id=ids["subject_cohort_tournament"],
                name="Compare Division Subject Cohort",
                is_finished=True,
                is_league=False,
            ),
            models.Tournament(
                id=ids["subject_other_tournament"],
                name="Compare Division Subject Other",
                is_finished=True,
                is_league=False,
            ),
            models.Tournament(
                id=ids["baseline_cohort_tournament"],
                name="Compare Division Baseline Cohort",
                is_finished=True,
                is_league=False,
            ),
            models.TournamentGroup(
                id=ids["subject_cohort_group"],
                tournament_id=ids["subject_cohort_tournament"],
                name="Main",
                is_groups=False,
            ),
            models.TournamentGroup(
                id=ids["subject_other_group"],
                tournament_id=ids["subject_other_tournament"],
                name="Main",
                is_groups=False,
            ),
            models.TournamentGroup(
                id=ids["baseline_cohort_group"],
                tournament_id=ids["baseline_cohort_tournament"],
                name="Main",
                is_groups=False,
            ),
            models.Team(
                id=ids["subject_cohort_team"],
                balancer_name="compare-subject-cohort",
                name="Compare Subject Cohort",
                avg_sr=3000,
                total_sr=3000,
                captain_id=ids["subject_user"],
                tournament_id=ids["subject_cohort_tournament"],
            ),
            models.Team(
                id=ids["subject_other_team"],
                balancer_name="compare-subject-other",
                name="Compare Subject Other",
                avg_sr=3000,
                total_sr=3000,
                captain_id=ids["subject_user"],
                tournament_id=ids["subject_other_tournament"],
            ),
            models.Team(
                id=ids["baseline_cohort_team"],
                balancer_name="compare-baseline-cohort",
                name="Compare Baseline Cohort",
                avg_sr=3000,
                total_sr=3000,
                captain_id=ids["baseline_user"],
                tournament_id=ids["baseline_cohort_tournament"],
            ),
            models.Team(
                id=ids["subject_cohort_enemy_team"],
                balancer_name="compare-subject-cohort-enemy",
                name="Compare Subject Cohort Enemy",
                avg_sr=3000,
                total_sr=3000,
                captain_id=ids["baseline_user"],
                tournament_id=ids["subject_cohort_tournament"],
            ),
            models.Team(
                id=ids["subject_other_enemy_team"],
                balancer_name="compare-subject-other-enemy",
                name="Compare Subject Other Enemy",
                avg_sr=3000,
                total_sr=3000,
                captain_id=ids["baseline_user"],
                tournament_id=ids["subject_other_tournament"],
            ),
            models.Team(
                id=ids["baseline_cohort_enemy_team"],
                balancer_name="compare-baseline-cohort-enemy",
                name="Compare Baseline Cohort Enemy",
                avg_sr=3000,
                total_sr=3000,
                captain_id=ids["subject_user"],
                tournament_id=ids["baseline_cohort_tournament"],
            ),
            models.Player(
                id=ids["subject_cohort_player"],
                name="compare-division-subject",
                sub_role="hitscan",
                rank=3000,
                div=division,
                role=role,
                tournament_id=ids["subject_cohort_tournament"],
                user_id=ids["subject_user"],
                team_id=ids["subject_cohort_team"],
            ),
            models.Player(
                id=ids["subject_other_player"],
                name="compare-division-subject",
                sub_role="hitscan",
                rank=3000,
                div=other_division,
                role=role,
                tournament_id=ids["subject_other_tournament"],
                user_id=ids["subject_user"],
                team_id=ids["subject_other_team"],
            ),
            models.Player(
                id=ids["baseline_cohort_player"],
                name="compare-division-baseline",
                sub_role="hitscan",
                rank=3000,
                div=division,
                role=role,
                tournament_id=ids["baseline_cohort_tournament"],
                user_id=ids["baseline_user"],
                team_id=ids["baseline_cohort_team"],
            ),
            models.Standing(
                id=ids["subject_cohort_standing"],
                tournament_id=ids["subject_cohort_tournament"],
                group_id=ids["subject_cohort_group"],
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
                id=ids["subject_other_standing"],
                tournament_id=ids["subject_other_tournament"],
                group_id=ids["subject_other_group"],
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
                id=ids["baseline_cohort_standing"],
                tournament_id=ids["baseline_cohort_tournament"],
                group_id=ids["baseline_cohort_group"],
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
            models.Encounter(
                id=ids["subject_cohort_encounter"],
                name="Compare Subject Cohort Encounter",
                home_team_id=ids["subject_cohort_team"],
                away_team_id=ids["subject_cohort_enemy_team"],
                home_score=2,
                away_score=1,
                round=1,
                closeness=0.75,
                tournament_id=ids["subject_cohort_tournament"],
                tournament_group_id=ids["subject_cohort_group"],
            ),
            models.Encounter(
                id=ids["subject_other_encounter"],
                name="Compare Subject Other Encounter",
                home_team_id=ids["subject_other_team"],
                away_team_id=ids["subject_other_enemy_team"],
                home_score=2,
                away_score=1,
                round=1,
                closeness=0.5,
                tournament_id=ids["subject_other_tournament"],
                tournament_group_id=ids["subject_other_group"],
            ),
            models.Encounter(
                id=ids["baseline_cohort_encounter"],
                name="Compare Baseline Cohort Encounter",
                home_team_id=ids["baseline_cohort_team"],
                away_team_id=ids["baseline_cohort_enemy_team"],
                home_score=2,
                away_score=1,
                round=1,
                closeness=0.65,
                tournament_id=ids["baseline_cohort_tournament"],
                tournament_group_id=ids["baseline_cohort_group"],
            ),
            models.Match(
                id=ids["subject_cohort_match"],
                home_team_id=ids["subject_cohort_team"],
                away_team_id=ids["subject_cohort_enemy_team"],
                home_score=2,
                away_score=1,
                time=600,
                log_name="compare-subject-cohort-match",
                encounter_id=ids["subject_cohort_encounter"],
                map_id=map_id,
            ),
            models.Match(
                id=ids["subject_other_match"],
                home_team_id=ids["subject_other_team"],
                away_team_id=ids["subject_other_enemy_team"],
                home_score=2,
                away_score=1,
                time=600,
                log_name="compare-subject-other-match",
                encounter_id=ids["subject_other_encounter"],
                map_id=map_id,
            ),
            models.Match(
                id=ids["baseline_cohort_match"],
                home_team_id=ids["baseline_cohort_team"],
                away_team_id=ids["baseline_cohort_enemy_team"],
                home_score=2,
                away_score=1,
                time=600,
                log_name="compare-baseline-cohort-match",
                encounter_id=ids["baseline_cohort_encounter"],
                map_id=map_id,
            ),
            models.MatchStatistics(
                id=ids["subject_cohort_playtime"],
                match_id=ids["subject_cohort_match"],
                round=0,
                team_id=ids["subject_cohort_team"],
                user_id=ids["subject_user"],
                hero_id=hero_id,
                name=enums.LogStatsName.HeroTimePlayed,
                value=600,
            ),
            models.MatchStatistics(
                id=ids["subject_cohort_eliminations"],
                match_id=ids["subject_cohort_match"],
                round=0,
                team_id=ids["subject_cohort_team"],
                user_id=ids["subject_user"],
                hero_id=hero_id,
                name=enums.LogStatsName.Eliminations,
                value=20,
            ),
            models.MatchStatistics(
                id=ids["subject_other_playtime"],
                match_id=ids["subject_other_match"],
                round=0,
                team_id=ids["subject_other_team"],
                user_id=ids["subject_user"],
                hero_id=hero_id,
                name=enums.LogStatsName.HeroTimePlayed,
                value=600,
            ),
            models.MatchStatistics(
                id=ids["subject_other_eliminations"],
                match_id=ids["subject_other_match"],
                round=0,
                team_id=ids["subject_other_team"],
                user_id=ids["subject_user"],
                hero_id=hero_id,
                name=enums.LogStatsName.Eliminations,
                value=100,
            ),
            models.MatchStatistics(
                id=ids["baseline_cohort_playtime"],
                match_id=ids["baseline_cohort_match"],
                round=0,
                team_id=ids["baseline_cohort_team"],
                user_id=ids["baseline_user"],
                hero_id=hero_id,
                name=enums.LogStatsName.HeroTimePlayed,
                value=600,
            ),
            models.MatchStatistics(
                id=ids["baseline_cohort_eliminations"],
                match_id=ids["baseline_cohort_match"],
                round=0,
                team_id=ids["baseline_cohort_team"],
                user_id=ids["baseline_user"],
                hero_id=hero_id,
                name=enums.LogStatsName.Eliminations,
                value=40,
            ),
            models.MatchStatistics(
                id=ids["subject_cohort_performance"],
                match_id=ids["subject_cohort_match"],
                round=0,
                team_id=ids["subject_cohort_team"],
                user_id=ids["subject_user"],
                hero_id=None,
                name=enums.LogStatsName.Performance,
                value=10,
            ),
            models.MatchStatistics(
                id=ids["baseline_cohort_performance"],
                match_id=ids["baseline_cohort_match"],
                round=0,
                team_id=ids["baseline_cohort_team"],
                user_id=ids["baseline_user"],
                hero_id=None,
                name=enums.LogStatsName.Performance,
                value=20,
            ),
        ]
    )
    db.commit()

    return {
        "subject_user_id": subject_user_id,
        "role": role.value,
        "division": division,
        "hero_id": hero_id,
    }


@pytest.mark.parametrize(
    ("page", "per_page", "sort", "order", "entities", "query", "fields"),
    [
        (1, 10, "id", "desc", [], "", []),
        (1, 25, "id", "desc", [], "", []),
        (1, 10, "id", "desc", ["discord", "twitch", "battle_tag"], "", []),
        (
            1,
            10,
            "similarity:name",
            "asc",
            ["discord", "twitch", "battle_tag"],
            "craaz",
            ["name"],
        ),
    ],
)
def test_search_user(
    client: TestClient,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    entities: list[str],
    query: str,
    fields: list[str],
) -> None:
    response = client.get(
        f"{config.settings.api_v1_str}/users",
        params={
            "page": page,
            "per_page": per_page,
            "sort": sort,
            "order": order,
            "entities": entities,
            "query": query,
            "fields": fields,
        },
    )
    assert response.status_code == 200
    content = response.json()
    assert content["page"] == page
    assert content["per_page"] == per_page
    assert content["results"]

    if query:
        assert query in content["results"][0]["name"].lower()


@pytest.mark.parametrize(
    (
        "page",
        "per_page",
        "sort",
        "order",
        "query",
        "role",
        "div_min",
        "div_max",
    ),
    [
        (1, 10, "name", "asc", "", None, None, None),
        (1, 10, "tournaments_count", "desc", "", None, None, None),
        (1, 10, "achievements_count", "desc", "", None, None, None),
        (1, 10, "avg_placement", "asc", "cra", None, None, None),
        (1, 10, "name", "asc", "", "Damage", 8, 20),
    ],
)
def test_get_users_overview(
    client: TestClient,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    query: str,
    role: str | None,
    div_min: int | None,
    div_max: int | None,
) -> None:
    params: dict[str, object] = {
        "page": page,
        "per_page": per_page,
        "sort": sort,
        "order": order,
        "query": query,
    }
    if role is not None:
        params["role"] = role
    if div_min is not None:
        params["div_min"] = div_min
    if div_max is not None:
        params["div_max"] = div_max

    response = client.get(f"{config.settings.api_v1_str}/users/overview", params=params)
    assert response.status_code == 200

    content = response.json()
    assert content["page"] == page
    assert content["per_page"] == per_page
    assert "results" in content

    if content["results"]:
        first = content["results"][0]
        assert "id" in first
        assert "name" in first
        assert "roles" in first
        assert "top_heroes" in first
        assert "tournaments_count" in first
        assert "achievements_count" in first
        assert "averages" in first
        assert len(first["top_heroes"]) <= 5

        if query:
            assert query.lower() in first["name"].lower()

        if role is not None:
            assert any(role_row["role"] == role for role_row in first["roles"])

        if div_min is not None:
            max_division = div_max if div_max is not None else 999
            assert any(div_min <= role_row["division"] <= max_division for role_row in first["roles"])


def test_get_users_overview_invalid_division_range(client: TestClient) -> None:
    response = client.get(
        f"{config.settings.api_v1_str}/users/overview",
        params={"div_min": 15, "div_max": 5},
    )
    assert response.status_code == 400
    content = response.json()
    assert content["detail"][0]["code"] == "invalid_filter"


@pytest.mark.parametrize(("user_id",), [(599,), (79,)])
@pytest.mark.db
def test_get_user_compare_global(client: TestClient, user_id: int) -> None:
    response = client.get(f"{config.settings.api_v1_str}/users/{user_id}/compare")
    assert response.status_code == 200

    content = response.json()
    assert content["subject"]["id"] == user_id
    assert content["baseline"]["mode"] == "global"
    assert content["baseline"]["sample_size"] >= 1
    assert content["metrics"]
    assert "better_worse" in content["metrics"][0]


@pytest.mark.db
def test_get_user_compare_target_user(client: TestClient) -> None:
    response = client.get(
        f"{config.settings.api_v1_str}/users/599/compare",
        params={"baseline": "target_user", "target_user_id": 79},
    )
    assert response.status_code == 200

    content = response.json()
    assert content["subject"]["id"] == 599
    assert content["baseline"]["mode"] == "target_user"
    assert content["baseline"]["sample_size"] == 1
    assert content["baseline"]["target_user"] is not None
    assert content["baseline"]["target_user"]["id"] == 79
    assert "better_worse" in content["metrics"][0]


@pytest.mark.db
def test_get_user_compare_cohort(client: TestClient) -> None:
    response = client.get(
        f"{config.settings.api_v1_str}/users/599/compare",
        params={
            "baseline": "cohort",
            "role": "Damage",
            "div_min": 8,
            "div_max": 20,
        },
    )
    assert response.status_code == 200

    content = response.json()
    assert content["baseline"]["mode"] == "cohort"
    assert content["baseline"]["role"] == "Damage"
    assert content["baseline"]["div_min"] == 8
    assert content["baseline"]["div_max"] == 20
    assert content["baseline"]["sample_size"] >= 1
    assert "better_worse" in content["metrics"][0]


@pytest.mark.db
def test_get_user_compare_cohort_scopes_average_placement_to_matching_division(client: TestClient, db: Session) -> None:
    _skip_if_compare_test_db_unavailable(db)
    fixture = _ensure_compare_division_fixture(db)

    response = client.get(
        f"{config.settings.api_v1_str}/users/{fixture['subject_user_id']}/compare",
        params={
            "baseline": "cohort",
            "role": fixture["role"],
            "div_min": fixture["division"],
            "div_max": fixture["division"],
        },
    )
    assert response.status_code == 200

    content = response.json()
    metric = _get_compare_metric(content, "avg_placement")

    assert content["baseline"]["sample_size"] == 2
    assert metric["subject_value"] == pytest.approx(1.0)
    assert metric["baseline_value"] == pytest.approx(2.5)


@pytest.mark.db
def test_get_user_hero_compare(client: TestClient) -> None:
    left_heroes_response = client.get(f"{config.settings.api_v1_str}/users/599/heroes", params={"per_page": 1})
    right_heroes_response = client.get(f"{config.settings.api_v1_str}/users/79/heroes", params={"per_page": 1})
    assert left_heroes_response.status_code == 200
    assert right_heroes_response.status_code == 200

    left_heroes = left_heroes_response.json()["results"]
    right_heroes = right_heroes_response.json()["results"]
    assert left_heroes
    assert right_heroes

    response = client.get(
        f"{config.settings.api_v1_str}/users/599/compare/heroes",
        params={
            "baseline": "target_user",
            "target_user_id": 79,
            "left_hero_id": left_heroes[0]["hero"]["id"],
            "right_hero_id": right_heroes[0]["hero"]["id"],
            "stats": ["eliminations", "final_blows", "hero_damage_dealt", "healing_dealt"],
        },
    )
    assert response.status_code == 200

    content = response.json()
    assert content["subject"]["id"] == 599
    assert content["target"] is not None
    assert content["target"]["id"] == 79
    assert content["baseline"]["mode"] == "target_user"
    assert content["baseline"]["sample_size"] == 1
    assert content["subject_hero"] is not None
    assert content["target_hero"] is not None
    assert len(content["metrics"]) == 4
    assert "higher_is_better" in content["metrics"][0]
    assert "better_worse" in content["metrics"][0]


@pytest.mark.db
def test_get_user_hero_compare_cohort_scopes_stats_to_matching_division(client: TestClient, db: Session) -> None:
    _skip_if_compare_test_db_unavailable(db)
    fixture = _ensure_compare_division_fixture(db)

    response = client.get(
        f"{config.settings.api_v1_str}/users/{fixture['subject_user_id']}/compare/heroes",
        params={
            "baseline": "cohort",
            "role": fixture["role"],
            "div_min": fixture["division"],
            "div_max": fixture["division"],
            "left_hero_id": fixture["hero_id"],
            "right_hero_id": fixture["hero_id"],
            "stats": ["eliminations"],
        },
    )
    assert response.status_code == 200

    content = response.json()
    metric = content["metrics"][0]

    assert content["baseline"]["sample_size"] == 2
    assert metric["stat"] == "eliminations"
    assert metric["left_value"] == pytest.approx(20.0)
    assert metric["right_value"] == pytest.approx(30.0)


@pytest.mark.db
def test_get_user_hero_compare_includes_performance_without_hero_filter(client: TestClient, db: Session) -> None:
    _skip_if_compare_test_db_unavailable(db)
    fixture = _ensure_compare_division_fixture(db)

    response = client.get(
        f"{config.settings.api_v1_str}/users/{fixture['subject_user_id']}/compare/heroes",
        params={
            "baseline": "cohort",
            "role": fixture["role"],
            "div_min": fixture["division"],
            "div_max": fixture["division"],
            "stats": ["performance"],
        },
    )
    assert response.status_code == 200

    content = response.json()
    assert len(content["metrics"]) == 1
    metric = content["metrics"][0]

    assert metric["stat"] == "performance"
    assert metric["left_value"] == pytest.approx(10.0)
    assert metric["right_value"] == pytest.approx(15.0)


@pytest.mark.db
def test_get_user_hero_compare_global_baseline(client: TestClient) -> None:
    response = client.get(
        f"{config.settings.api_v1_str}/users/599/compare/heroes",
        params={
            "baseline": "global",
            "stats": ["eliminations", "final_blows"],
        },
    )
    assert response.status_code == 200

    content = response.json()
    assert content["subject"]["id"] == 599
    assert content["target"] is None
    assert content["baseline"]["mode"] == "global"
    assert content["baseline"]["sample_size"] >= 1
    assert len(content["metrics"]) == 2


@pytest.mark.db
def test_get_user_hero_compare_ascending_stat_better_worse(client: TestClient) -> None:
    response = client.get(
        f"{config.settings.api_v1_str}/users/599/compare/heroes",
        params={
            "baseline": "global",
            "stats": ["deaths"],
        },
    )
    assert response.status_code == 200

    content = response.json()
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


@pytest.mark.parametrize(
    ("name", "entities"),
    [
        ("CraazzzyyFox-2130", []),
        ("CraazzzyyFox-2130", ["battle_tag"]),
        ("CraazzzyyFox-2130", ["battle_tag", "discord", "twitch"]),
        ("Zuuuuuuuuuuz-2690", []),
        ("Zuuuuuuuuuuz-2690", ["battle_tag"]),
        ("Zuuuuuuuuuuz-2690", ["battle_tag", "discord", "twitch"]),
        ("Anak-2894", []),
        ("Anak-2894", ["battle_tag"]),
        ("Anak-2894", ["battle_tag", "discord", "twitch"]),
        ("marmeladka-21557", []),
        ("marmeladka-21557", ["battle_tag"]),
        ("marmeladka-21557", ["battle_tag", "discord", "twitch"]),
    ],
)
def test_get_user_by_name(client: TestClient, name: str, entities: list[str]) -> None:
    response = client.get(f"{config.settings.api_v1_str}/users/{name}", params={"entities": entities})
    assert response.status_code == 200
    content = response.json()
    assert content["name"] == name.replace("-", "#")
    if "battle_tag" in entities:
        assert content["battle_tag"] != []
    if "twitch" in entities:
        assert content["twitch"] != []


@pytest.mark.parametrize(
    ("user_id",),
    [
        (599,),
        (79,),
        (461,),
        (583,),
    ],
)
def test_get_user_profile(client: TestClient, user_id: int) -> None:
    response = client.get(f"{config.settings.api_v1_str}/users/{user_id}/profile")
    assert response.status_code == 200
    content = response.json()
    assert content["tournaments"].__len__() >= 0


@pytest.mark.parametrize(
    ("user_id",),
    [
        (599,),
        (79,),
        (461,),
        (583,),
    ],
)
def test_get_user_tournaments(client: TestClient, user_id: int) -> None:
    response = client.get(f"{config.settings.api_v1_str}/users/{user_id}/tournaments")
    assert response.status_code == 200
    content = response.json()
    assert content.__len__() >= 0


@pytest.mark.parametrize(
    ("user_id", "tournament_id"),
    [
        (599, 36),
        (79, 3),
        (461, 10),
        (583, 18),
    ],
)
def test_get_user_tournament(client: TestClient, user_id: int, tournament_id: int) -> None:
    response = client.get(f"{config.settings.api_v1_str}/users/{user_id}/tournaments/{tournament_id}")
    assert response.status_code == 200
    content = response.json()
    assert content.__len__() >= 0


@pytest.mark.parametrize(
    ("user_id", "tournament_id"),
    [
        (599, 3),
        (79, 36),
        (461, 14),
        (583, 14),
    ],
)
def test_get_user_tournament_not_found(client: TestClient, user_id: int, tournament_id: int) -> None:
    response = client.get(f"{config.settings.api_v1_str}/users/{user_id}/tournaments/{tournament_id}")
    assert response.status_code == 404
    content = response.json()
    assert content["detail"][0]["code"] == "not_found"


@pytest.mark.parametrize(
    ("user_id", "page", "per_page", "sort", "order", "entities"),
    [
        (599, 1, 10, "id", "desc", []),
        (599, 1, 25, "name", "desc", ["gamemode"]),
        (599, 1, 10, "winrate", "desc", ["hero_stats"]),
        (79, 1, 10, "id", "desc", []),
        (461, 1, 10, "name", "desc", []),
        (461, 1, 25, "gamemode_id", "desc", ["gamemode"]),
        (583, 1, 10, "name", "desc", []),
        (583, 1, 25, "slug", "desc", ["gamemode"]),
    ],
)
def test_get_user_maps(
    client: TestClient,
    user_id: int,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    entities: list[str],
) -> None:
    response = client.get(
        f"{config.settings.api_v1_str}/users/{user_id}/maps",
        params={
            "page": page,
            "per_page": per_page,
            "sort": sort,
            "order": order,
            "entities": entities,
        },
    )
    assert response.status_code == 200
    content = response.json()
    assert content["page"] == page
    assert content["per_page"] == per_page

    if "gamemode" in entities:
        assert content["results"][0]["map"]["gamemode"]
    else:
        if content["results"]:
            assert content["results"][0]["map"]["gamemode"] is None

    if "hero_stats" in entities and content["results"]:
        assert content["results"][0]["hero_stats"] is not None


@pytest.mark.parametrize(
    ("user_id", "entities", "min_count"),
    [
        (599, [], None),
        (599, ["gamemode"], 3),
        (79, [], 1),
    ],
)
def test_get_user_maps_summary(client: TestClient, user_id: int, entities: list[str], min_count: int | None) -> None:
    params: dict[str, object] = {
        "entities": entities,
    }
    if min_count is not None:
        params["min_count"] = min_count

    response = client.get(
        f"{config.settings.api_v1_str}/users/{user_id}/maps/summary",
        params=params,
    )
    assert response.status_code == 200
    content = response.json()

    assert "overall" in content
    assert "total_maps" in content["overall"]
    assert "total_games" in content["overall"]

    if "gamemode" in entities:
        if content.get("most_played") is not None:
            assert content["most_played"]["map"]["gamemode"]


@pytest.mark.parametrize(
    ("user_id", "page", "per_page", "sort", "order", "entities"),
    [
        (599, 1, 10, "id", "desc", []),
        (599, 1, 25, "id", "desc", ["tournament"]),
        # (599, 1, 25, "name", "desc", ["tournament", "teams", "teams.players"]),
        (599, 1, 25, "id", "desc", ["tournament", "teams"]),
        (79, 1, 10, "id", "desc", []),
        (79, 1, 25, "home_team_id", "desc", ["tournament"]),
        # (79, 1, 25, "away_team_id", "desc", ["tournament", "teams", "teams.players"]),
        (79, 1, 25, "away_team_id", "desc", ["tournament", "teams"]),
        (461, 1, 10, "name", "desc", []),
        (461, 1, 25, "round", "desc", ["tournament"]),
        # (461, 1, 25, "away_team_id", "desc", ["tournament", "teams", "teams.players"]),
        (461, 1, 25, "home_team_id", "desc", ["tournament", "teams"]),
        (583, 1, 10, "closeness", "desc", []),
        # (583, 1, 25, "tournament_id", "desc", ["tournament", "teams", "teams.players"]),
        (583, 1, 25, "round", "desc", ["tournament", "teams"]),
    ],
)
def test_get_user_encounters(
    client: TestClient,
    user_id: int,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    entities: list[str],
) -> None:
    response = client.get(
        f"{config.settings.api_v1_str}/users/{user_id}/encounters",
        params={
            "page": page,
            "per_page": per_page,
            "sort": sort,
            "order": order,
            "entities": entities,
        },
    )
    assert response.status_code == 200
    content = response.json()
    assert content["page"] == page
    assert content["per_page"] == per_page

    if "teams" in entities:
        assert content["results"][0]["home_team"]
        assert content["results"][0]["away_team"]

        if "teams.players" in entities:
            assert content["results"][0]["home_team"]["players"]
            assert content["results"][0]["away_team"]["players"]
        else:
            if content["results"]:
                assert content["results"][0]["home_team"]["players"] == []
                assert content["results"][0]["away_team"]["players"] == []

    else:
        if content["results"]:
            assert content["results"][0]["home_team"] is None
            assert content["results"][0]["away_team"] is None

    if "tournament" in entities:
        assert content["results"][0]["tournament"]
    else:
        if content["results"]:
            assert content["results"][0]["tournament"] is None


@pytest.mark.parametrize(("user_id",), [(599,), (79,), (461,), (583,)])
def test_get_user_heroes(client: TestClient, user_id: int) -> None:
    response = client.get(
        f"{config.settings.api_v1_str}/users/{user_id}/heroes",
    )
    assert response.status_code == 200


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
def test_get_user_teammates(client: TestClient, user_id: int, page: int, per_page: int, sort: str, order: str) -> None:
    response = client.get(
        f"{config.settings.api_v1_str}/users/{user_id}/teammates",
        params={
            "page": page,
            "per_page": per_page,
            "sort": sort,
            "order": order,
        },
    )
    assert response.status_code == 200
    content = response.json()
    assert content["page"] == page
    assert content["per_page"] == per_page

    if content["results"] and "winrate" == sort:
        if order == "desc":
            assert content["results"][0]["winrate"] >= content["results"][-1]["winrate"]
        else:
            assert content["results"][0]["winrate"] <= content["results"][-1]["winrate"]


def test_get_user_heroes_with_stats(client: TestClient) -> None:
    user_id = 599
    response = client.get(
        f"{config.settings.api_v1_str}/users/{user_id}/heroes", params={"stats": ["deaths", "eliminations"]}
    )
    assert response.status_code == 200
