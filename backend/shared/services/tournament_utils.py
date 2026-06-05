"""Shared tournament utility functions used by both parser-service and
app-service (Phase E consolidation).

Eliminates the duplication of ``sort_matches`` and ``_completed_encounters``
between parser-service/services/standings/service.py,
parser-service/services/standings/flows.py and
app-service/services/standings/flows.py.
"""

from __future__ import annotations

import typing
from collections.abc import Sequence

from shared.core import enums
from shared.models.encounter import Encounter

__all__ = (
    "sort_bracket_matches",
    "is_completed_encounter",
    "completed_encounters",
    "completed_encounters_in_finished_rounds",
    "has_incomplete_playable_rounds",
    "get_double_elimination_round_order",
)


def is_completed_encounter(encounter: Encounter) -> bool:
    """Canonical "this encounter counts toward standings" predicate.

    Phase B: the single source of truth is ``status == COMPLETED``.
    ``result_status == CONFIRMED`` also counts (captain submission flow).
    Non-zero scores alone do NOT — that rule previously masked state desyncs.
    """
    if encounter.home_team_id is None or encounter.away_team_id is None:
        return False
    return (
        encounter.status == enums.EncounterStatus.COMPLETED
        or encounter.result_status == enums.EncounterResultStatus.CONFIRMED
    )


def completed_encounters(
    encounters: Sequence[Encounter],
) -> list[Encounter]:
    """Filter encounters through :func:`is_completed_encounter`."""
    return [e for e in encounters if is_completed_encounter(e)]


def _playable_rounds(
    encounters: Sequence[Encounter],
) -> dict[int, list[Encounter]]:
    rounds: dict[int, list[Encounter]] = {}
    for encounter in encounters:
        if encounter.home_team_id is None or encounter.away_team_id is None:
            continue
        rounds.setdefault(encounter.round, []).append(encounter)
    return rounds


def completed_encounters_in_finished_rounds(
    encounters: Sequence[Encounter],
) -> list[Encounter]:
    """Return completed encounters that belong to fully closed playable rounds.

    A round is considered playable only when both participants are known.
    If at least one playable encounter in a round is still open/pending, the
    whole round is ignored for standings/reseeding purposes.
    """
    completed: list[Encounter] = []
    for round_encounters in _playable_rounds(encounters).values():
        if all(is_completed_encounter(encounter) for encounter in round_encounters):
            completed.extend(round_encounters)
    return completed


def has_incomplete_playable_rounds(
    encounters: Sequence[Encounter],
) -> bool:
    """Return True when any playable round still has unfinished encounters."""
    return any(
        any(not is_completed_encounter(encounter) for encounter in round_encounters)
        for round_encounters in _playable_rounds(encounters).values()
    )


def get_double_elimination_round_order(round_num: int) -> float:
    """Returns a chronological order score for a given round number in a
    Double Elimination bracket. Smaller values indicate earlier rounds.

    Progression:
      - UB R1 (1) -> LB R1 (-1)
      - UB R2 (2) -> LB R2 (-2) -> LB R3 (-3)
      - UB R3 (3) -> LB R4 (-4) -> LB R5 (-5)
      - UB R4 (4) -> LB R6 (-6) -> LB R7 (-7)
      ...
    """
    if round_num == 1:
        return 1.0
    elif round_num == -1:
        return 2.0
    elif round_num > 1:
        return 3.0 * round_num - 3.0
    elif round_num < -1:
        val = abs(round_num)
        if val % 2 == 0:
            k = val // 2
            return 3.0 * k + 1.0
        else:
            k = (val - 1) // 2
            return 3.0 * k + 2.0
    return 0.0


def sort_bracket_matches(
    matches: Sequence[typing.Any],
) -> list[typing.Any]:
    """Order encounters/pairings so the matches are sorted chronologically
    by their round number, handling both upper (positive) and lower (negative)
    bracket rounds correctly.

    Works with any object that has a ``round`` attribute (models.Encounter,
    schemas.EncounterRead, bracket Pairing).
    """
    if not matches:
        return []

    # Check if there are any negative rounds, which implies Double Elimination
    has_negative_rounds = any(m.round < 0 for m in matches)

    def sort_key(match: typing.Any) -> tuple[float, int]:
        match_id = getattr(match, "id", 0) or 0
        if has_negative_rounds:
            return get_double_elimination_round_order(match.round), match_id
        else:
            # For non-Double Elimination stages, sort by round number ascending
            return float(match.round), match_id

    return sorted(matches, key=sort_key)
