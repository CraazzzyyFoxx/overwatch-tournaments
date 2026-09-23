"""Pure rules behind the captain's pick queue and the fit column.

The end-to-end proof (a queued player reaching the board, and the preview
matching the autopick that follows) lives in ``test_draft_integration.py``
against a real Postgres. What is here is the part that needs no draft at all:
which queued entry wins, at which role, and how a raw fit spread becomes the
1..99 a captain reads.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.core.enums import HeroClass  # noqa: E402
from shared.models.balancer.draft import DraftTeam  # noqa: E402
from src.domain.draft import fit  # noqa: E402
from src.domain.draft.entities import DraftSnapshot, FitResult  # noqa: E402
from src.services.draft.selection import selection_service  # noqa: E402
from tests.factories import roster  # noqa: E402

T, D, SUP = HeroClass.tank, HeroClass.damage, HeroClass.support


def _snapshot(rosters: dict[int, object]) -> DraftSnapshot:
    return DraftSnapshot(teams=(), players=(), picks=(), rosters=rosters)


def _team(queue: list[int]) -> DraftTeam:
    return DraftTeam(id=1, session_id=1, name="T", draft_position=1, pick_queue=queue)


def _choose(queue, rosters, safe, available):
    return selection_service._queued_choice(_team(queue), _snapshot(rosters), safe, available)


# ---- which queued entry wins ----


def test_first_queued_player_with_a_safe_option_wins() -> None:
    rosters = {10: roster(10, ranks={"damage": 2000}), 11: roster(11, ranks={"damage": 4000})}
    choice = _choose([10, 11], rosters, {10: {D}, 11: {D}}, {10, 11})

    # Order, not strength: 11 is the better player and still loses to placement.
    assert (choice.player_id, choice.role, choice.source) == (10, D, "queue")


def test_a_queued_player_somebody_else_already_took_is_skipped() -> None:
    rosters = {10: roster(10, ranks={"damage": 2000}), 11: roster(11, ranks={"damage": 4000})}
    choice = _choose([10, 11], rosters, {11: {D}}, {11})

    assert choice.player_id == 11


def test_a_queued_player_with_no_safe_option_is_skipped_never_forced() -> None:
    # Autopick may not break the draft on a captain's behalf: a queued player
    # whose every role would strand a slot is passed over, not seated anyway.
    rosters = {10: roster(10, ranks={"support": 3000}), 11: roster(11, ranks={"damage": 4000})}
    choice = _choose([10, 11], rosters, {11: {D}}, {10, 11})

    assert choice.player_id == 11


def test_an_exhausted_queue_defers_to_the_fit_strategy() -> None:
    rosters = {10: roster(10, ranks={"support": 3000})}

    assert _choose([10], rosters, {}, {10}) is None
    assert _choose([], rosters, {10: {SUP}}, {10}) is None


# ---- which role the queued player is taken at ----


def test_queued_role_is_the_safe_option_they_rank_highest_on() -> None:
    rosters = {10: roster(10, ranks={"damage": 2600, "support": 3400}, primary="damage")}
    choice = _choose([10], rosters, {10: {D, SUP}}, {10})

    # Their primary is damage, but support is the role they are actually worth
    # more on -- and both are safe, so the team gets the better player.
    assert choice.role is SUP


def test_equally_ranked_safe_options_go_to_the_primary_role() -> None:
    rosters = {10: roster(10, ranks={"support": 3000, "damage": 3000}, primary="support")}
    choice = _choose([10], rosters, {10: {D, SUP}}, {10})

    assert choice.role is SUP


def test_equally_ranked_non_primary_options_fall_back_to_canonical_order() -> None:
    # Nothing to prefer: tank/damage/support is the one order the whole backend
    # spells roles in, so autopick stays reproducible instead of hash-ordered.
    rosters = {10: roster(10, ranks={"tank": 3000, "damage": 3000, "support": 3000}, primary="support")}
    choice = _choose([10], rosters, {10: {T, D}}, {10})

    assert choice.role is T


# ---- raw fit -> the 1..99 a captain reads ----


def _result(player_id: int, score: float) -> FitResult:
    return FitResult(player_id=player_id, role=D, fit_score=score, breakdown={})


def test_normalized_scores_stretch_the_spread_over_the_full_scale() -> None:
    scores = fit.normalized_scores([_result(1, 4200.0), _result(2, 1000.0), _result(3, 2600.0)])

    assert scores[1] == 1
    assert scores[0] == 99
    assert 1 < scores[2] < 99


def test_an_all_equal_field_scores_the_midpoint_not_the_extremes() -> None:
    # Raw fit is unbounded and only its ordering means anything; with no
    # ordering to show, 1 and 99 would both be lies about the same number.
    assert fit.normalized_scores([_result(1, 2500.0), _result(2, 2500.0)]) == [50, 50]
    assert fit.normalized_scores([_result(1, 0.0)]) == [50]
    assert fit.normalized_scores([]) == []
