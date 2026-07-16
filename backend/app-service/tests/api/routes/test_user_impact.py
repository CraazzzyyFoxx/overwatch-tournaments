"""RPC-handler tests for the MVP impact fields on user match reads (task 8).

Mirrors the fixture style of ``test_user.py`` (same ``rpc: RpcHarness`` /
``db: Session`` fixtures, fixed-id idempotent setup via ``models.MatchStatistics``)
but exercises the NEW ``impact_rank`` / ``impact_points`` / ``overperformance_score``
/ ``overperformance_badge`` fields on ``GET /users/{id}/encounters`` ->
``rpc.app.users.encounters``.

These are DB-integration tests: the ``rpc`` fixture skips cleanly when no local
``anak_dev`` Postgres is reachable (see ``conftest.py``), which is the expected
outcome in CI and in this environment. They are written to be correct against a
populated dev DB, not merely to pass — see task-8 report for details.
"""

import pytest
from sqlalchemy.orm import Session

from shared.core.impact import BADGE_THRESHOLD
from src import models
from src.core import enums
from tests.conftest import RpcHarness, build_query

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
    "match_with_impact": 9_400_000_060,
    "match_without_impact": 9_400_000_061,
    "match_below_threshold": 9_400_000_062,
    "stat_a_impact_rank_m1": 9_400_000_101,
    "stat_a_impact_points_m1": 9_400_000_102,
    "stat_a_overperf_m1": 9_400_000_103,
    "stat_b_impact_rank_m1": 9_400_000_104,
    "stat_b_impact_points_m1": 9_400_000_105,
    "stat_b_overperf_m1": 9_400_000_106,
    "stat_a_impact_rank_m3": 9_400_000_110,
    "stat_a_impact_points_m3": 9_400_000_111,
    "stat_a_overperf_m3": 9_400_000_112,
}

# Scores derived from BADGE_THRESHOLD so the fixture keeps testing the
# above/below-threshold boundary even if the constant is retuned later.
_OVERPERF_A_TOP = BADGE_THRESHOLD + 0.5  # top-1 in match_with_impact, >= threshold -> badge True
_OVERPERF_B_SECOND = BADGE_THRESHOLD / 2  # 2nd in match_with_impact -> badge False regardless of value
_OVERPERF_A_BELOW_THRESHOLD = BADGE_THRESHOLD * 0.75  # sole entrant (trivial pos=1) but < threshold -> badge False


def _ensure_impact_badge_fixture(db: Session) -> dict[str, int]:
    """One encounter, two players, three matches exercising every branch of the
    overperformance badge formula (``pos == 1 and score >= BADGE_THRESHOLD``):

      - ``match_with_impact``: user A ranks 1st (top-1 OverperformanceScore in
        the match, score >= BADGE_THRESHOLD) -> badge True. User B ranks 2nd
        -> badge False.
      - ``match_without_impact``: neither player has impact/overperformance
        rows at all -> ``impact_rank`` is None, badge False.
      - ``match_below_threshold``: only user A has an OverperformanceScore row,
        so the match-wide rank() window trivially ranks them 1st, but the
        score is below BADGE_THRESHOLD -> badge False despite ``pos == 1``.

    Idempotent (fixed ids, checked before insert) — mirrors
    ``test_user.py::_ensure_compare_division_fixture``. Rows persist in the dev
    DB across runs; a second run is a no-op.
    """
    ids = _IMPACT_FIXTURE_IDS
    if db.get(models.User, ids["user_a"]) is not None:
        return ids

    map_row = db.query(models.Map.id).order_by(models.Map.id).first()
    assert map_row is not None, "no map seeded in dev DB"
    map_id = map_row[0]

    db.add_all(
        [
            models.User(id=ids["user_a"], name="impact-badge-user-a"),
            models.User(id=ids["user_b"], name="impact-badge-user-b"),
            models.Workspace(id=ids["workspace"], slug="impact-badge-ws", name="Impact Badge Workspace"),
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
                is_finished=True,
                is_league=False,
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
            models.Encounter(
                id=ids["encounter"],
                name="Impact Badge Encounter",
                home_team_id=ids["team_home"],
                away_team_id=ids["team_away"],
                home_score=2,
                away_score=1,
                round=1,
                tournament_id=ids["tournament"],
            ),
            models.Match(
                id=ids["match_with_impact"],
                home_team_id=ids["team_home"],
                away_team_id=ids["team_away"],
                home_score=1,
                away_score=0,
                time=600,
                log_name="impact-badge-match-with-impact",
                encounter_id=ids["encounter"],
                map_id=map_id,
            ),
            models.Match(
                id=ids["match_without_impact"],
                home_team_id=ids["team_home"],
                away_team_id=ids["team_away"],
                home_score=1,
                away_score=0,
                time=600,
                log_name="impact-badge-match-without-impact",
                encounter_id=ids["encounter"],
                map_id=map_id,
            ),
            models.Match(
                id=ids["match_below_threshold"],
                home_team_id=ids["team_home"],
                away_team_id=ids["team_away"],
                home_score=0,
                away_score=1,
                time=600,
                log_name="impact-badge-match-below-threshold",
                encounter_id=ids["encounter"],
                map_id=map_id,
            ),
            # match_with_impact: A tops the match -> badge True.
            models.MatchStatistics(
                id=ids["stat_a_impact_rank_m1"],
                match_id=ids["match_with_impact"],
                round=0,
                team_id=ids["team_home"],
                user_id=ids["user_a"],
                hero_id=None,
                name=enums.LogStatsName.ImpactRank,
                value=1,
            ),
            models.MatchStatistics(
                id=ids["stat_a_impact_points_m1"],
                match_id=ids["match_with_impact"],
                round=0,
                team_id=ids["team_home"],
                user_id=ids["user_a"],
                hero_id=None,
                name=enums.LogStatsName.ImpactPoints,
                value=3.4,
            ),
            models.MatchStatistics(
                id=ids["stat_a_overperf_m1"],
                match_id=ids["match_with_impact"],
                round=0,
                team_id=ids["team_home"],
                user_id=ids["user_a"],
                hero_id=None,
                name=enums.LogStatsName.OverperformanceScore,
                value=_OVERPERF_A_TOP,
            ),
            # match_with_impact: B is 2nd -> not top-1 -> badge False.
            models.MatchStatistics(
                id=ids["stat_b_impact_rank_m1"],
                match_id=ids["match_with_impact"],
                round=0,
                team_id=ids["team_away"],
                user_id=ids["user_b"],
                hero_id=None,
                name=enums.LogStatsName.ImpactRank,
                value=2,
            ),
            models.MatchStatistics(
                id=ids["stat_b_impact_points_m1"],
                match_id=ids["match_with_impact"],
                round=0,
                team_id=ids["team_away"],
                user_id=ids["user_b"],
                hero_id=None,
                name=enums.LogStatsName.ImpactPoints,
                value=1.1,
            ),
            models.MatchStatistics(
                id=ids["stat_b_overperf_m1"],
                match_id=ids["match_with_impact"],
                round=0,
                team_id=ids["team_away"],
                user_id=ids["user_b"],
                hero_id=None,
                name=enums.LogStatsName.OverperformanceScore,
                value=_OVERPERF_B_SECOND,
            ),
            # match_below_threshold: only A has a score row; the match-wide
            # rank() window trivially ranks a solo row 1st, but the value is
            # below BADGE_THRESHOLD -> badge False despite pos == 1.
            models.MatchStatistics(
                id=ids["stat_a_impact_rank_m3"],
                match_id=ids["match_below_threshold"],
                round=0,
                team_id=ids["team_home"],
                user_id=ids["user_a"],
                hero_id=None,
                name=enums.LogStatsName.ImpactRank,
                value=1,
            ),
            models.MatchStatistics(
                id=ids["stat_a_impact_points_m3"],
                match_id=ids["match_below_threshold"],
                round=0,
                team_id=ids["team_home"],
                user_id=ids["user_a"],
                hero_id=None,
                name=enums.LogStatsName.ImpactPoints,
                value=0.9,
            ),
            models.MatchStatistics(
                id=ids["stat_a_overperf_m3"],
                match_id=ids["match_below_threshold"],
                round=0,
                team_id=ids["team_home"],
                user_id=ids["user_a"],
                hero_id=None,
                name=enums.LogStatsName.OverperformanceScore,
                value=_OVERPERF_A_BELOW_THRESHOLD,
            ),
            # match_without_impact intentionally carries no impact/overperformance rows.
        ]
    )
    db.commit()

    return ids


def _find_match(matches: list[dict], match_id: int) -> dict:
    return next(m for m in matches if m["id"] == match_id)


def _get_encounters(rpc: RpcHarness, user_id: int, workspace_id: int) -> dict:
    env = rpc.call_sync(
        "rpc.app.users.encounters",
        {
            "id": user_id,
            "query": build_query(
                {
                    "page": 1,
                    "per_page": 10,
                    "sort": "id",
                    "order": "desc",
                    "workspace_id": workspace_id,
                }
            ),
        },
    )
    assert env["ok"] is True
    return env["data"]


def test_get_user_encounters_impact_rank_and_overperformance_badge(rpc: RpcHarness, db: Session) -> None:
    """MVP impact fields on user match reads (task 8):

    - top-1 OverperformanceScore in the match, score >= BADGE_THRESHOLD -> badge True
    - present but not top-1 in the match -> badge False
    - trivially top-1 (only entrant) but below BADGE_THRESHOLD -> badge False
    - no impact rows at all for that match -> impact_rank is None, badge False
    """
    ids = _ensure_impact_badge_fixture(db)

    content_a = _get_encounters(rpc, ids["user_a"], ids["workspace"])
    results_a = content_a["results"]
    assert len(results_a) == 1
    matches_a = results_a[0]["matches"]
    assert len(matches_a) == 3

    with_impact_a = _find_match(matches_a, ids["match_with_impact"])
    assert with_impact_a["impact_rank"] == 1
    assert with_impact_a["impact_points"] == pytest.approx(3.4)
    assert with_impact_a["overperformance_score"] == pytest.approx(_OVERPERF_A_TOP)
    assert with_impact_a["overperformance_badge"] is True

    without_impact_a = _find_match(matches_a, ids["match_without_impact"])
    assert without_impact_a["impact_rank"] is None
    assert without_impact_a["impact_points"] is None
    assert without_impact_a["overperformance_score"] is None
    assert without_impact_a["overperformance_badge"] is False

    below_threshold_a = _find_match(matches_a, ids["match_below_threshold"])
    assert below_threshold_a["impact_rank"] == 1
    assert below_threshold_a["overperformance_score"] == pytest.approx(_OVERPERF_A_BELOW_THRESHOLD)
    assert below_threshold_a["overperformance_badge"] is False  # top-1 but below BADGE_THRESHOLD

    content_b = _get_encounters(rpc, ids["user_b"], ids["workspace"])
    results_b = content_b["results"]
    assert len(results_b) == 1
    matches_b = results_b[0]["matches"]

    with_impact_b = _find_match(matches_b, ids["match_with_impact"])
    assert with_impact_b["impact_rank"] == 2
    assert with_impact_b["overperformance_score"] == pytest.approx(_OVERPERF_B_SECOND)
    assert with_impact_b["overperformance_badge"] is False  # not top-1 in the match
