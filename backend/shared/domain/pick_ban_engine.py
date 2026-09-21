"""Generic pick-ban step engine: pure functions shared by map veto and hero
bans. Generalizes ``tournament-service/src/services/encounter/{veto_session,
map_veto}.py`` to be pool-agnostic (``kind``) and able to run a session whose
sequence grows round by round instead of being fully precomputed at creation.

See ``docs/plans/2026-08-09-generic-pickban-engine.md`` for the design and
decision log this module implements. Deliberately free of any AsyncSession/DB
call — every function here takes plain data and returns plain data or raises
``ValueError`` (the RPC layer translates to HTTP), so the whole engine is
unit-testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from shared.core import enums

# Side-agnostic step tokens. Adds `protect_*` to the existing map-veto
# vocabulary (`ban_first`/`ban_second`/`pick_first`/`pick_second`/`decider`).
PICK_BAN_SEQUENCE_TOKENS = frozenset(
    {
        "ban_first",
        "ban_second",
        "pick_first",
        "pick_second",
        "protect_first",
        "protect_second",
        "decider",
    }
)

Side = Literal["home", "away"]
Action = Literal["ban", "pick", "protect", "decider"]


@dataclass(frozen=True)
class ParsedStep:
    token: str
    action: Action
    side: Side | None  # None only for "decider"


def parse_step_token(token: str) -> ParsedStep:
    """Resolved tokens are e.g. ``ban_home``/``protect_away``/``decider``.

    A token with no ``_`` (and not ``decider``) used to ``ValueError`` on the
    unpack — and ``get_pick_ban_state`` calls this on every poll. Unknown
    action/side already default to ban/home; missing separator does the same.
    """
    if token == "decider":
        return ParsedStep(token, "decider", None)
    action_part, _sep, side_part = token.partition("_")
    action: Action = action_part if action_part in ("ban", "pick", "protect") else "ban"  # type: ignore[assignment]
    side: Side = "away" if side_part == "away" else "home"
    return ParsedStep(token, action, side)


def resolve_sequence_tokens(sequence: list[str], first_side: enums.MapPickSide | str) -> list[str]:
    """Map side-agnostic ``*_first``/``*_second`` tokens onto home/away.

    Identical to ``veto_session.resolve_sequence_tokens``; kept here so both
    map and hero configs share one implementation.
    """
    first = first_side.value if isinstance(first_side, enums.MapPickSide) else first_side
    second = "away" if first == "home" else "home"
    resolved: list[str] = []
    for token in sequence:
        if token == "decider":
            resolved.append("decider")
            continue
        if not isinstance(token, str) or "_" not in token:
            raise ValueError(f"invalid sequence token {token!r}")
        action, slot = token.split("_", 1)
        resolved.append(f"{action}_{first if slot == 'first' else second}")
    return resolved


# ── entry-shaped protocol ────────────────────────────────────────────────────
#
# The engine works over any object exposing these attributes. ``PickBanEntry``
# satisfies it structurally, so the functions stay free of a DB-model import.


class EntryLike:
    """Structural shape the engine reads/writes. Not instantiated directly —
    documents the attributes ``PickBanEntry`` must have."""

    id: int
    item_id: int
    round: int | None
    status: str  # enums.MapPoolEntryStatus value
    action_index: int | None
    order: int
    picked_by: str | None
    protected_by: str | None


def get_current_step(sequence: list[str], pool: list) -> tuple[int, str] | None:
    """Current step index + token, or None once the sequence is exhausted.

    Identical arithmetic to today's engine: count everything not `available`.
    Unchanged deliberately — see design §5.2 ("the smallest possible change to
    a well-tested core").
    """
    completed = sum(1 for e in pool if e.status != enums.MapPoolEntryStatus.AVAILABLE.value)
    if completed >= len(sequence):
        return None
    return completed, sequence[completed]


def current_round(pool: list) -> int | None:
    """The round (map-of-the-series) the engine is resolving, or None in flat
    mode / once complete. Generalizes ``map_veto.current_slot`` — same
    arithmetic, `slot` renamed `round` for a pool-agnostic reading."""
    rounds = [e.round for e in pool if e.status == enums.MapPoolEntryStatus.AVAILABLE.value and e.round is not None]
    return min(rounds) if rounds else None


def in_current_round(entry, active_round: int | None) -> bool:
    """Generalizes ``map_veto.in_current_slot``. `active_round is None` is an
    identity match — a flat pool (no rounds) has no round to be outside of."""
    return active_round is None or entry.round == active_round


def is_entry_bannable(entry, *, active_round: int | None) -> bool:
    """Whether `entry` may be targeted by a `ban` right now: available, in the
    round in play, and not protected."""
    if entry.status != enums.MapPoolEntryStatus.AVAILABLE.value:
        return False
    if entry.protected_by is not None:
        return False
    return in_current_round(entry, active_round)


def settled_in_order(pool: list) -> list:
    """The pool's `picked`/`played` entries in PLAY order — for a map pool this
    is the series' map order, and index + 1 is the map's position in the series
    (``EncounterMapReport.map_index``, ``Match.map_index``).

    Play order is ``action_index``, falling back to the legacy ``order``.
    ``order`` on its own is NOT the position: it is a per-round display/tiebreak
    field spaced by ``round * 1000`` (see ``captain._picked_map_ids``). Mirrors
    the frontend's ``pickedItemsInOrder``.
    """
    settled = (
        entry
        for entry in pool
        if entry.status in (enums.MapPoolEntryStatus.PICKED.value, enums.MapPoolEntryStatus.PLAYED.value)
    )
    return sorted(settled, key=lambda entry: entry.action_index if entry.action_index is not None else entry.order)


# ── undo (both captains agree to take the last action back) ─────────────────


DECIDER_SIDE = enums.MapPickSide.DECIDER.value


def undoable_entries(pool: list) -> list:
    """The trailing committed action(s) an undo would revert, latest first —
    empty when nothing may be taken back.

    Only the LAST action is ever undoable: `get_current_step` counts committed
    entries and indexes that into the sequence, so removing the newest one
    restores exactly the step that produced it, while removing anything older
    would leave a hole the arithmetic cannot express.

    A `decider` pick is not an action anybody took — the engine resolves it the
    moment the sequence reaches that step (``auto_complete_decider``), so it is
    reverted TOGETHER with the captain action beneath it. Undoing it alone would
    be a no-op the next read undoes again.

    Refuses (returns empty) when the round in question is already settled:

    - a `played` entry in that round — the map has been played, so its bans are
      history, not a mistake still fixable;
    - a round beyond it exists in the pool — a later round only opens once this
      one's map is played and reported (``advance_to_next_round``), so the
      trailing action of THIS round is behind that barrier.
    """
    committed = sorted(
        (e for e in pool if e.action_index is not None),
        key=lambda e: e.action_index,
        reverse=True,
    )
    if not committed:
        return []

    group: list = []
    for entry in committed:
        group.append(entry)
        if entry.picked_by != DECIDER_SIDE:
            break
    else:
        # Deciders all the way down: nothing a captain chose, nothing to undo.
        return []

    target_round = group[-1].round
    for entry in pool:
        if entry.round == target_round and entry.status == enums.MapPoolEntryStatus.PLAYED.value:
            return []
        if target_round is not None and entry.round is not None and entry.round > target_round:
            return []
    return group


# ── ledger exclusion (no-repeat) ─────────────────────────────────────────────


@dataclass(frozen=True)
class LedgerRow:
    """One committed BAN, remembered across rounds.

    Protects are deliberately absent: a protect is a round-local immunity, so
    it neither bars a later ban nor is barred by one — bans and protects never
    restrict each other.
    """

    item_id: int
    banned_by_side: str


def excluded_item_ids(
    ledger: list[LedgerRow],
    *,
    scope: enums.PickBanNoRepeatScope,
    side: Side | None = None,
) -> set[int]:
    """Item ids a new round's candidate pool must NOT include, per `scope`.

    ``NONE``: nothing excluded (today's behavior).
    ``ENCOUNTER``: every item the ledger has anywhere, regardless of side —
    Doc 1's "nobody may re-ban a hero for the whole match".
    ``ENCOUNTER_SAME_SIDE``: only items THIS side banned earlier —
    Doc 2's "a team can't repeat its own ban; banning the opponent's earlier
    ban is fine". Requires `side`.
    """
    if scope == enums.PickBanNoRepeatScope.NONE:
        return set()
    if scope == enums.PickBanNoRepeatScope.ENCOUNTER:
        return {row.item_id for row in ledger}
    if side is None:
        raise ValueError("side is required for ENCOUNTER_SAME_SIDE exclusion")
    return {row.item_id for row in ledger if row.banned_by_side == side}


# ── role/attribute uniqueness within one side's actions this round ──────────


def committed_attributes(
    pool: list,
    *,
    action: Action,
    attribute_lookup: dict[int, object],
) -> list[tuple[str | None, int | None, object]]:
    """``(side, round, attribute)`` per action of the SAME KIND as `action`
    already committed in `pool` — the history `violates_unique_attribute`
    measures a new `action` against.

    Bans and protects are tracked SEPARATELY: uniqueness constrains a side's
    bans among its bans and its protects among its protects, never across the
    two — banning a tank does not spend that side's tank protect, and vice
    versa. Status is the discriminator, so the side is read off `picked_by`
    for a ban and `protected_by` for a protect. Picks and deciders carry no
    attribute restriction in either rulebook and are never included.
    """
    if action == "ban":
        status = enums.MapPoolEntryStatus.BANNED.value
        return [(e.picked_by, e.round, attribute_lookup.get(e.item_id)) for e in pool if e.status == status]
    if action == "protect":
        status = enums.MapPoolEntryStatus.PROTECTED.value
        return [(e.protected_by, e.round, attribute_lookup.get(e.item_id)) for e in pool if e.status == status]
    return []


def violates_unique_attribute(
    *,
    candidate_attribute,
    acting_side: Side,
    round_number: int | None,
    committed_this_round: list[tuple[str | None, int | None, object]],
) -> bool:
    """True if `acting_side` already has a committed action of the SAME KIND
    THIS round whose target shares `candidate_attribute` (e.g. hero role).

    `committed_this_round` comes from `committed_attributes`, which keeps the
    ban and protect histories apart — pass the wrong one and a ban would bar a
    protect.
    """
    if candidate_attribute is None:
        return False
    return any(
        side == acting_side and round_ == round_number and attr == candidate_attribute
        for side, round_, attr in committed_this_round
    )


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
    previous_round_winner: Side | None,
    previous_round_loser_choice: Side | None,
) -> Side:
    """Who opens `round_number`'s bans (the side `_first` maps onto).

    Round 1 always uses `session_first_side` (seed resolution — unrelated to
    any rotation setting, since there is no previous map). Round 2+ dispatches
    on `rotation`:

    - `fixed`: same side every round (`session_first_side`).
    - `alternate`: flips each round from `session_first_side`.
    - `result_winner_first` / `result_loser_first`: requires
      `previous_round_winner` (raises `ValueError` if the caller invokes this
      before that map's result is known — a caller bug, not a user error).
    - `result_loser_choice`: requires `previous_round_loser_choice` — if it is
      `None`, raises `RotationNeedsChoice` so the caller creates the round in
      `awaiting_choice` state instead of resolving a side.
    """
    if round_number <= 1:
        return session_first_side

    if rotation == enums.FirstBanRotation.FIXED:
        return session_first_side
    if rotation == enums.FirstBanRotation.ALTERNATE:
        flips = round_number - 1
        return session_first_side if flips % 2 == 0 else _other(session_first_side)
    if rotation in (enums.FirstBanRotation.RESULT_WINNER_FIRST, enums.FirstBanRotation.RESULT_LOSER_FIRST):
        if previous_round_winner is None:
            raise ValueError("previous_round_winner is required for a result-dependent rotation")
        return (
            previous_round_winner
            if rotation == enums.FirstBanRotation.RESULT_WINNER_FIRST
            else _other(previous_round_winner)
        )
    if rotation == enums.FirstBanRotation.RESULT_LOSER_CHOICE:
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


def winner_side(home_score: int, away_score: int) -> Side | None:
    """None on a drawn map score (e.g. a hybrid 0-0 draw per both rulebooks'
    §3.1) — callers must not create a result-dependent next round from a draw
    without their own tiebreak handling; this function only reports what the
    score says."""
    if home_score > away_score:
        return "home"
    if away_score > home_score:
        return "away"
    return None


def series_decided(home_score: int, away_score: int, best_of: int) -> bool:
    """Whether a series standing at ``home_score``-``away_score`` still has a
    map left to play.

    Two independent stop conditions, because neither covers the other: every
    map of the series has been played (``Bo2`` ends 1-1 with nobody past
    half), or one side is past half and the rest cannot change the outcome
    (``Bo3`` ends 2-0 with a map unplayed). Read by the round-progression
    trigger so a decided series stops opening pick-ban rounds for maps that
    will never be played.
    """
    if best_of < 1:
        return False
    return home_score + away_score >= best_of or max(home_score, away_score) * 2 > best_of
