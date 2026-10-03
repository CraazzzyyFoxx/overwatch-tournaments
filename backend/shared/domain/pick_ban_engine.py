"""What survived the ruleset-v2 cutover of the pick-ban engine: the pure,
DB-free rules that are NOT about resolving a step.

The step vocabulary, cursor, eligibility, undo target and projection all moved
to ``shared.domain.pick_ban_rules`` (design
``docs/plans/2026-09-28-pick-ban-constructor.md``). What stays here is the
encounter-level arithmetic both kinds still share: which round a board is on,
the play order of its settled picks, who opens the next round under a
result-dependent rotation, and how two captains' map reports reconcile into a
series score.

Deliberately free of any AsyncSession/DB call — every function takes plain
data and returns plain data or raises ``ValueError`` (the RPC layer translates
to HTTP), so the whole module is unit-testable without a database.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from shared.core import enums

Side = Literal["home", "away"]
Action = Literal["ban", "pick", "protect", "decider"]


# ── board arithmetic ────────────────────────────────────────────────────────
#
# Both functions work over any object exposing ``status``/``round``/
# ``action_index``/``order`` -- ``PickBanEntry`` satisfies that structurally,
# so they stay free of a DB-model import.


def current_round(pool: list) -> int | None:
    """The round (map-of-the-series) the engine is resolving, or None in flat
    mode / once complete. Generalizes ``map_veto.current_slot`` — same
    arithmetic, `slot` renamed `round` for a pool-agnostic reading."""
    rounds = [e.round for e in pool if e.status == enums.MapPoolEntryStatus.AVAILABLE.value and e.round is not None]
    return min(rounds) if rounds else None


def settled_in_order(pool: list) -> list:
    """The pool's `picked` entries in PLAY order — for a map pool this is the
    series' map order, and index + 1 is the map's position in the series
    (``encounter_game.position``).

    Play order is ``action_index``, falling back to the legacy ``order``.
    ``order`` on its own is NOT the position: it is a per-round display/tiebreak
    field spaced by ``round * 1000`` (see ``captain._picked_map_ids``). Mirrors
    the frontend's ``pickedItemsInOrder``.
    """
    settled = (entry for entry in pool if entry.status == enums.MapPoolEntryStatus.PICKED.value)
    return sorted(settled, key=lambda entry: entry.action_index if entry.action_index is not None else entry.order)


# ── result-dependent rotation: who opens round N+1 ──────────────────────────


class RotationNeedsChoice(Exception):
    """Raised by `resolve_round_opener` when the rotation is
    `result_loser_choice` and no choice has been made yet — the caller must
    create the round with `first_side=None`, `awaiting_choice=True` and wait
    for an `elect_opener` action instead of resolving a side here."""


def resolve_round_opener(
    *,
    rotation: enums.FirstBanRotation,
    round_number: int,
    session_first_side: Side,
    previous_round_outcome: MapOutcome | None,
    previous_round_loser_choice: Side | None,
) -> Side:
    """Who opens `round_number`'s bans (the side `_first` maps onto).

    Round 1 always uses `session_first_side` (seed resolution — unrelated to
    any rotation setting, since there is no previous map). Round 2+ dispatches
    on `rotation`:

    - `fixed`: same side every round (`session_first_side`).
    - `alternate`: flips each round from `session_first_side`.
    - `result_winner_first` / `result_loser_first`: read
      `previous_round_outcome`. A `"draw"` has no winner and no loser, so the
      rotation falls back to the fixed snapshot side (`session_first_side`).
      `None` means the previous map has no accepted result yet — a caller bug,
      so `ValueError`.
    - `result_loser_choice`: a `"draw"` leaves nobody to elect, so it too
      falls back to `session_first_side`; otherwise it requires
      `previous_round_loser_choice` — if that is `None`, raises
      `RotationNeedsChoice` so the caller creates the round in
      `awaiting_choice` state instead of resolving a side.
    """
    if round_number <= 1:
        return session_first_side

    if rotation == enums.FirstBanRotation.FIXED:
        return session_first_side
    if rotation == enums.FirstBanRotation.ALTERNATE:
        flips = round_number - 1
        return session_first_side if flips % 2 == 0 else _other(session_first_side)
    if rotation in (
        enums.FirstBanRotation.RESULT_WINNER_FIRST,
        enums.FirstBanRotation.RESULT_LOSER_FIRST,
        enums.FirstBanRotation.RESULT_LOSER_CHOICE,
    ):
        if previous_round_outcome is None:
            raise ValueError("previous_round_outcome is required for a result-dependent rotation")
        if previous_round_outcome == "draw":
            return session_first_side
        if rotation == enums.FirstBanRotation.RESULT_WINNER_FIRST:
            return previous_round_outcome
        if rotation == enums.FirstBanRotation.RESULT_LOSER_FIRST:
            return _other(previous_round_outcome)
        if previous_round_loser_choice is None:
            raise RotationNeedsChoice()
        return previous_round_loser_choice
    raise ValueError(f"unhandled rotation {rotation!r}")


def _other(side: Side) -> Side:
    return "away" if side == "home" else "home"


# ── per-map result reconciliation (EncounterMapReport -> Match) ─────────────


@dataclass(frozen=True)
class MapReportPair:
    home_report: tuple[int, int] | None  # (home_score, away_score) as the HOME captain reported it
    away_report: tuple[int, int] | None  # as the AWAY captain reported it


@dataclass(frozen=True)
class ReconciliationResult:
    resolved: tuple[int, int] | None  # (home_score, away_score) if both agree
    disputed: bool


def reconcile_map_reports(pair: MapReportPair) -> ReconciliationResult:
    """Agree -> resolved score. Present but disagree -> disputed. Either
    missing -> neither (still waiting on a captain).

    Mirrors `captain.set_encounter_result`'s series-level reconciliation
    (Decision log #10): "both reports agreeing" is a resolution path there
    too — this is the same rule applied to one map instead of the whole
    series, not a new reconciliation concept.
    """
    if pair.home_report is None or pair.away_report is None:
        return ReconciliationResult(resolved=None, disputed=False)
    if pair.home_report == pair.away_report:
        return ReconciliationResult(resolved=pair.home_report, disputed=False)
    return ReconciliationResult(resolved=None, disputed=True)


MapOutcome = Literal["home", "away", "draw"]


def map_outcome(home_score: int, away_score: int) -> MapOutcome:
    if home_score > away_score:
        return "home"
    if away_score > home_score:
        return "away"
    return "draw"


@dataclass(frozen=True)
class SeriesScore:
    home_wins: int
    away_wins: int
    played: int  # confirmed positions, draws included


def series_score(results: Iterable[tuple[int, int]]) -> SeriesScore:
    """Wins and played positions over CONFIRMED games' accepted (home, away) scores."""
    home = away = played = 0
    for home_score, away_score in results:
        played += 1
        outcome = map_outcome(home_score, away_score)
        home += outcome == "home"
        away += outcome == "away"
    return SeriesScore(home, away, played)


def series_complete(score: SeriesScore, best_of: int) -> bool:
    """Every position played (Bo2 1:1, or a draw consuming the last map), or one
    side past half. Wins alone cannot say this: a drawn map adds no win but does
    use a position (spec §6.3)."""
    if best_of < 1:
        return False
    return score.played >= best_of or max(score.home_wins, score.away_wins) * 2 > best_of


def legal_series_result(home_score: int, away_score: int, best_of: int) -> bool:
    """A score a best-of-N series can actually end on.

    The winner has exactly ``floor(N/2)+1`` maps and the loser has no more than
    the rest. An even N may also be drawn down the middle (Bo2 → 1:1). A 1:0 on
    Bo2 has a map left; a 2:1 has played one map too many.
    """
    if best_of < 1 or home_score < 0 or away_score < 0:
        return False
    wins_needed = best_of // 2 + 1
    if home_score == away_score:
        return best_of % 2 == 0 and home_score == best_of // 2
    winner, loser = max(home_score, away_score), min(home_score, away_score)
    return winner == wins_needed and loser <= best_of - wins_needed
