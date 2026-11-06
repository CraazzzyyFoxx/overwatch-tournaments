"""RPC-handler tests for the MVP impact fields on user match reads (task 8).

Mirrors the fixture style of ``test_user.py`` (same ``rpc: RpcHarness`` /
``db: Session`` fixtures, fixed-id idempotent setup via native observed games)
but exercises the viewer's whole-match facts (the stored overperformance badge among them) and every observed member's
totals on ``GET /users/{id}/encounters`` -> ``rpc.stats.users.encounters``.

These are DB-integration tests: the ``rpc`` fixture skips cleanly when no local
``anak_dev`` Postgres is reachable (see ``conftest.py``), which is the expected
outcome in CI and in this environment. They are written to be correct against a
populated dev DB, not merely to pass — see task-8 report for details.
"""

import pytest
from sqlalchemy.orm import Session

from shared import models
from shared.core import enums
from tests.conftest import RpcHarness, build_query
from tests.encounter_seed import add_duel, add_observed_game

_IMPACT_FIXTURE_IDS = {
    "user_a": 9_400_000_001,
    "user_b": 9_400_000_002,
    "workspace": 9_400_000_010,
    "workspace_member_a": 9_400_000_011,
    "workspace_member_b": 9_400_000_012,
    "tournament": 9_400_000_020,
    "team_home": 9_400_000_030,
    "team_away": 9_400_000_031,
    "player_a": 9_400_000_040,
    "player_b": 9_400_000_041,
    "encounter": 9_400_000_050,
    "scoring_rule": 9_400_000_051,
    "match_with_impact": 9_400_000_060,
    "match_without_impact": 9_400_000_061,
    "match_below_threshold": 9_400_000_062,
}

# The badge itself is the stored fact: these scores only need to stay consistent with it.
_OVERPERF_A_TOP = 2.0  # top-1 in match_with_impact, badge 1
_OVERPERF_B_SECOND = 1.0  # 2nd in match_with_impact, badge 0
_OVERPERF_A_BELOW_THRESHOLD = 0.5  # sole entrant but below the stored threshold, badge 0


def _ensure_impact_badge_fixture(db: Session) -> dict[str, int]:
    """One encounter, two players, three matches carrying the stored ``overperformance_badge`` fact:

      - ``match_with_impact``: user A is top-1 on OverperformanceScore -> badge 1. User B is 2nd -> badge 0.
      - ``match_without_impact``: neither player has impact rows at all -> no viewer.
      - ``match_below_threshold``: only user A has an OverperformanceScore row, below the stored threshold ->
        badge 0 despite the trivial first place.

    Idempotent (fixed ids, checked before insert) — mirrors
    ``test_user.py::_ensure_compare_division_fixture``. Rows persist in the dev
    DB across runs; a second run is a no-op.
    """
    ids = _IMPACT_FIXTURE_IDS
    if db.get(models.User, ids["user_a"]) is not None:
        return ids

    map_row = (
        db.query(models.CatalogEntity.id)
        .filter_by(discipline="overwatch", kind="map")
        .order_by(models.CatalogEntity.id)
        .first()
    )
    assert map_row is not None, "no map seeded in dev DB"
    map_id = map_row[0]

    db.add(models.Workspace(id=ids["workspace"], slug="impact-badge-ws", name="Impact Badge Workspace"))
    db.flush()
    db.add(
        models.ScoringRule(
            id=ids["scoring_rule"],
            workspace_id=ids["workspace"],
            preset="wins",
            game_formula="win",
            end_formula="games >= best_of",
        )
    )
    db.flush()
    db.add_all(
        [
            models.User(id=ids["user_a"], name="impact-badge-user-a"),
            models.User(id=ids["user_b"], name="impact-badge-user-b"),
            models.WorkspaceMember(
                id=ids["workspace_member_a"], workspace_id=ids["workspace"], player_id=ids["user_a"]
            ),
            models.WorkspaceMember(
                id=ids["workspace_member_b"], workspace_id=ids["workspace"], player_id=ids["user_b"]
            ),
            models.Tournament(
                id=ids["tournament"],
                workspace_id=ids["workspace"],
                name="Impact Badge Tournament",
                slug="impact-badge-tournament",
                is_finished=True,
            ),
            models.Team(
                id=ids["team_home"],
                balancer_name="impact-badge-home",
                name="Impact Badge Home",
                tournament_id=ids["tournament"],
            ),
            models.Team(
                id=ids["team_away"],
                balancer_name="impact-badge-away",
                name="Impact Badge Away",
                tournament_id=ids["tournament"],
            ),
            models.Player(
                id=ids["player_a"],
                name="impact-badge-user-a",
                rank=3000,
                tournament_id=ids["tournament"],
                workspace_member_id=ids["workspace_member_a"],
                team_id=ids["team_home"],
                is_substitution=False,
            ),
            models.Player(
                id=ids["player_b"],
                name="impact-badge-user-b",
                rank=3000,
                tournament_id=ids["tournament"],
                workspace_member_id=ids["workspace_member_b"],
                team_id=ids["team_away"],
                is_substitution=False,
            ),
        ]
    )
    db.flush()
    add_duel(
        db,
        encounter_id=ids["encounter"],
        tournament_id=ids["tournament"],
        workspace_id=ids["workspace"],
        scoring_rule_id=ids["scoring_rule"],
        name="Impact Badge Encounter",
        seats=[(ids["team_home"], 2), (ids["team_away"], 1)],
    )
    a, b = ids["workspace_member_a"], ids["workspace_member_b"]
    add_observed_game(
        db,
        match_id=ids["match_with_impact"],
        encounter_id=ids["encounter"],
        map_entity_id=map_id,
        position=1,
        duration_s=600,
        scores=(1, 0),
        observations=[
            (a, 1, None, enums.LogStatsName.ImpactRank, 1),
            (a, 1, None, enums.LogStatsName.ImpactPoints, 3.4),
            (a, 1, None, enums.LogStatsName.OverperformanceScore, _OVERPERF_A_TOP),
            (a, 1, None, enums.LogStatsName.OverperformanceBadge, 1),
            (b, 2, None, enums.LogStatsName.ImpactRank, 2),
            (b, 2, None, enums.LogStatsName.ImpactPoints, 1.1),
            (b, 2, None, enums.LogStatsName.OverperformanceScore, _OVERPERF_B_SECOND),
            (b, 2, None, enums.LogStatsName.OverperformanceBadge, 0),
        ],
    )
    add_observed_game(
        db,
        match_id=ids["match_without_impact"],
        encounter_id=ids["encounter"],
        map_entity_id=map_id,
        position=2,
        duration_s=600,
        scores=(1, 0),
        observations=[],
    )
    # A is first by the window rank, but below the badge threshold: scored, no badge.
    add_observed_game(
        db,
        match_id=ids["match_below_threshold"],
        encounter_id=ids["encounter"],
        map_entity_id=map_id,
        position=3,
        duration_s=600,
        scores=(0, 1),
        observations=[
            (a, 1, None, enums.LogStatsName.ImpactRank, 1),
            (a, 1, None, enums.LogStatsName.ImpactPoints, 0.9),
            (a, 1, None, enums.LogStatsName.OverperformanceScore, _OVERPERF_A_BELOW_THRESHOLD),
            (a, 1, None, enums.LogStatsName.OverperformanceBadge, 0),
        ],
    )
    db.commit()

    return ids


def _find_match(matches: list[dict], match_id: int) -> dict:
    return next(m for m in matches if m["id"] == match_id)


def _get_encounters(rpc: RpcHarness, user_id: int, workspace_id: int) -> dict:
    env = rpc.call_sync(
        "rpc.stats.users.encounters",
        {
            "id": user_id,
            "query": build_query(
                {
                    "page": 1,
                    "per_page": 10,
                    "sort": "id",
                    "order": "desc",
                    "workspace_id": workspace_id,
                    "discipline": "overwatch",
                    "entities": ["matches"],
                }
            ),
        },
    )
    assert env["ok"] is True
    return env["data"]


def test_get_user_encounters_carry_viewer_facts_and_no_member_totals(rpc: RpcHarness, db: Session) -> None:
    """MVP impact inputs on user match reads: the wire ships the viewer's whole-match facts (the stored
    ``overperformance_badge`` among them: no read-time badge computation) and, as Overwatch declares no
    ``member_total_stats``, no member totals.

    - badge fact 1.0 -> viewer holds the badge
    - badge fact 0.0 -> viewer was scored for overperformance without holding it
    - no observed member at all for that match -> no viewer
    """
    ids = _ensure_impact_badge_fixture(db)

    content_a = _get_encounters(rpc, ids["user_a"], ids["workspace"])
    results_a = content_a["results"]
    assert len(results_a) == 1
    matches_a = results_a[0]["matches"]
    assert len(matches_a) == 3
    assert {"impact_rank", "impact_points", "overperformance_score", "overperformance_badge"}.isdisjoint(matches_a[0])

    with_impact_a = _find_match(matches_a, ids["match_with_impact"])
    facts_a = with_impact_a["viewer"]["facts"]
    assert facts_a["impact_rank"] == 1
    assert facts_a["impact_points"] == pytest.approx(3.4)
    assert facts_a["overperformance_score"] == pytest.approx(_OVERPERF_A_TOP)
    assert facts_a["overperformance_badge"] == 1.0
    # Overwatch ranks no member totals: the badge is the stored fact above.
    assert with_impact_a["member_totals"] == []

    without_impact_a = _find_match(matches_a, ids["match_without_impact"])
    assert without_impact_a["viewer"] is None

    below_threshold_a = _find_match(matches_a, ids["match_below_threshold"])
    assert below_threshold_a["viewer"]["facts"]["impact_rank"] == 1
    assert below_threshold_a["viewer"]["facts"]["overperformance_score"] == pytest.approx(_OVERPERF_A_BELOW_THRESHOLD)
    assert below_threshold_a["viewer"]["facts"]["overperformance_badge"] == 0.0  # top-1 but below the threshold

    content_b = _get_encounters(rpc, ids["user_b"], ids["workspace"])
    results_b = content_b["results"]
    assert len(results_b) == 1
    matches_b = results_b[0]["matches"]

    with_impact_b = _find_match(matches_b, ids["match_with_impact"])
    assert with_impact_b["viewer"]["facts"]["impact_rank"] == 2
    assert with_impact_b["viewer"]["facts"]["overperformance_score"] == pytest.approx(_OVERPERF_B_SECOND)
    assert with_impact_b["viewer"]["facts"]["overperformance_badge"] == 0.0  # not top-1 in the match
