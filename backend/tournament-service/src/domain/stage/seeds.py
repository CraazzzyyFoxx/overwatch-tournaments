"""Every pure decision about seed ORDER, in one module.

Three layers, all of them here, none of them touching a session:

1. ``SeedRanking`` — the order a stage hands to the bracket engine, which
   treats ``team_ids[0]`` as seed 1 (plays the lowest seed). Lives in
   ``Stage.seed_ranking``:

   - ``slot`` (default) / ``source``: keep StageItemInput slot order (standings wiring, manual slots; ``source`` =
     the input's rank order).
   - ``cross`` / ``snake``: regroup the input's rows by ``(stage_item_id, item_rank)`` at seating (:func:`plan_seats`);
     generation keeps the seated slot order, like ``slot``.
   - ``avg_sr``: highest ``Team.avg_sr`` is seed 1.
   - ``total_sr``: highest ``Team.total_sr`` is seed 1.
   - ``random``: ``random.Random(stage.id)`` shuffle, stable across processes.
   - ``captain_rank``: highest captain rank is seed 1. ``seed_teams`` only: the ranks are looked up by the caller,
     and ``Stage.seed_ranking`` (CHECK-constrained) does not carry it.

2. Group distribution — ``parse_seed_mode`` + ``group_for_index``: the
   ``seed_teams`` vocabulary (``snake_sr``/``by_total_sr``/``random``) and the
   snake/round-robin deal across a stage's groups.

3. Result rows -> seats — ``plan_seats`` (+ ``build_seeding`` + ``separate_groups``): which input row lands in which
   stage item and slot. A bracket target is seated in input order or, for ``cross``/``snake``, band by band (upper /
   lower starters): one slice per source group, ``cross`` or ``snake``, then the swaps that keep a group's teams
   apart in the first round. A group target gets a snake (or, for ``random``, shuffled round-robin) deal.

The engine's 1-vs-N slot layout itself (``src.domain.bracket.seeding_order``)
stays next to the generators that apply it; ``separate_groups`` only reads it.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any, NamedTuple, Protocol

from shared.core import enums
from src.domain.bracket import BracketSkeleton
from src.domain.bracket.seeding_order import seeding_order

__all__ = (
    "SEED_TEAMS_MODES",
    "GroupSlice",
    "SeatSource",
    "SeedRanking",
    "apply_seed_ranking",
    "bracket_seeds",
    "build_seeding",
    "collect_item_team_ids",
    "group_advance_counts",
    "group_for_index",
    "lower_bracket_item",
    "parse_seed_mode",
    "plan_seats",
    "rank_team_ids",
    "resolve_seeds",
    "separate_groups",
)


class SeedRanking(StrEnum):
    SLOT = "slot"
    SOURCE = "source"
    AVG_SR = "avg_sr"
    TOTAL_SR = "total_sr"
    RANDOM = "random"
    CAPTAIN_RANK = "captain_rank"
    CROSS = "cross"
    SNAKE = "snake"


# Rankings that put no order of their own on a seated list: generation keeps its slot order.
_SEATED_ORDER = (SeedRanking.SLOT, SeedRanking.SOURCE, SeedRanking.CROSS, SeedRanking.SNAKE)


class RankableTeam(Protocol):
    id: int
    avg_sr: float | None
    total_sr: float | int | None


# ``seed_teams``'s public vocabulary. ``slot`` has no entry: dealing teams into
# groups in "the order they already sit in" is not a distribution.
SEED_TEAMS_MODES: dict[str, SeedRanking] = {
    "snake_sr": SeedRanking.AVG_SR,
    "by_total_sr": SeedRanking.TOTAL_SR,
    "random": SeedRanking.RANDOM,
    "captain_rank": SeedRanking.CAPTAIN_RANK,
}


def parse_seed_mode(mode: str) -> SeedRanking | None:
    """``seed_teams`` mode -> ranking, or ``None`` for an unknown mode."""
    return SEED_TEAMS_MODES.get(mode)


def group_for_index(team_idx: int, num_groups: int, *, snake: bool) -> int:
    """Which group the ``team_idx``-th ranked team is dealt into.

    ``snake``: A, B, C, D, D, C, B, A, A, ... — every other row reversed, so a
    group's total strength stays even however many teams it ends up with.
    Otherwise plain round-robin, which is all a random order needs.
    """
    if not snake:
        return team_idx % num_groups
    row, column = divmod(team_idx, num_groups)
    return column if row % 2 == 0 else num_groups - 1 - column


def rank_team_ids(
    teams: Sequence[RankableTeam],
    ranking: SeedRanking,
    *,
    rng_seed: int,
    captain_ranks: Mapping[int, int | None] | None = None,
) -> list[int]:
    """Return team ids in engine seed order (index 0 = seed 1).

    ``captain_ranks`` (team id -> the captain's rank) is read by ``CAPTAIN_RANK`` only; a team without one sorts last.
    """
    items = list(teams)
    if ranking in _SEATED_ORDER:
        return [team.id for team in items]
    if ranking is SeedRanking.AVG_SR:
        return [team.id for team in sorted(items, key=lambda team: (-(team.avg_sr or 0.0), team.id))]
    if ranking is SeedRanking.TOTAL_SR:
        return [team.id for team in sorted(items, key=lambda team: (-(team.total_sr or 0), team.id))]
    if ranking is SeedRanking.CAPTAIN_RANK:
        ranks = captain_ranks or {}
        return [team.id for team in sorted(items, key=lambda team: (-(ranks.get(team.id) or 0), team.id))]
    if ranking is SeedRanking.RANDOM:
        ids = [team.id for team in items]
        random.Random(rng_seed).shuffle(ids)
        return ids
    return [team.id for team in items]


def apply_seed_ranking(
    team_ids: list[int],
    teams_by_id: Mapping[int, RankableTeam],
    ranking: SeedRanking,
    *,
    rng_seed: int,
) -> list[int]:
    """Reorder ``team_ids`` by ``ranking``. Unknown or placeholder ids keep slot order."""
    if ranking in _SEATED_ORDER or not team_ids:
        return list(team_ids)
    if any(team_id <= 0 or team_id not in teams_by_id for team_id in team_ids):
        return list(team_ids)
    return rank_team_ids([teams_by_id[team_id] for team_id in team_ids], ranking, rng_seed=rng_seed)


def lower_bracket_item(stage: Any, sorted_items: list) -> Any | None:
    """The stage item holding the separate Lower bracket, when the stage has one.

    A "single bracket" double elimination keeps the whole UB+LB structure in one
    item instead, and the engine builds its lower rounds internally.
    """
    if stage.stage_type != enums.StageType.DOUBLE_ELIMINATION:
        return None
    return next((item for item in sorted_items if item.type == enums.StageItemType.BRACKET_LOWER), None)


def collect_item_team_ids(item: Any) -> list[int]:
    return [
        inp.team_id
        for inp in sorted(item.inputs, key=lambda value: value.slot)
        if inp.team_id is not None and getattr(inp, "input_type", None) != enums.StageItemInputType.EMPTY
    ]


def bracket_seeds(
    sorted_items: list,
    lb_item: Any | None,
    *,
    collect: Any = collect_item_team_ids,
) -> tuple[list[int], list[int]]:
    """The teams wired into a bracket stage, split into upper vs lower starters.

    Lower-bracket starters are exactly the ``BRACKET_LOWER`` item's inputs
    (``lower_bracket_item`` is None for anything but double elimination).
    """
    upper = [tid for item in sorted_items if item is not lb_item for tid in collect(item)]
    return upper, (collect(lb_item) if lb_item is not None else [])


def resolve_seeds(skeleton: BracketSkeleton, teams: dict[int, int]) -> BracketSkeleton:
    """Swap placeholder negative seed ids for the teams they stand for.

    Over every SLOT of a pairing, not two sides: a pairing is ``team_ids[i]``
    seeded into slot ``i + 1``, and a placeholder nobody named resolves
    to an empty seat.
    """

    def team_for(seed: int | None) -> int | None:
        if seed is None or seed >= 0:
            return seed
        return teams.get(seed)

    return replace(
        skeleton,
        pairings=[
            replace(pairing, team_ids=tuple(team_for(team_id) for team_id in pairing.team_ids))
            for pairing in skeleton.pairings
        ],
    )


class GroupSlice(NamedTuple):
    """The band of finishing positions one group sends into one bracket half."""

    item_id: int
    #: 1-based first position taken from that group (3 = "from 3rd place down").
    start: int
    count: int


def group_advance_counts(
    source_items: Sequence[Any],
    *,
    default_advance: int,
    default_upper: int | None,
) -> list[tuple[int, int, int]]:
    """Per source group: ``(item_id, upper_count, lower_count)``.

    A group's own ``advance_count`` overrides ``default_advance`` (0 / NULL reads
    as "no override": the schema rejects 0). Its own ``advance_upper_count``
    overrides ``default_upper``; NULL on both means everyone it sends starts in
    the upper bracket. ``0`` upper is real: the whole group starts lower. Upper
    never exceeds what the group actually sends.
    """
    counts: list[tuple[int, int, int]] = []
    for item in source_items:
        advance = getattr(item, "advance_count", None) or default_advance
        own_upper = getattr(item, "advance_upper_count", None)
        upper = own_upper if own_upper is not None else (default_upper if default_upper is not None else advance)
        upper = min(upper, advance)
        counts.append((item.id, upper, advance - upper))
    return counts


def build_seeding(slices: Sequence[GroupSlice], mode: str) -> list[tuple[int, int]]:
    """Ordered (source_item_id, position) pairs wiring a playoff from groups.

    ``snake``: all 1st places, then all 2nd places, ... ``cross`` flips every
    odd column. Neither order alone keeps a group's teams apart in round 1 of
    a generated bracket -- its 1-vs-N layout decides who opens against whom --
    which is :func:`separate_groups`' job.

    Slices may be ragged (groups advancing different counts): a group that has
    run out of positions is skipped for the remaining columns, and the ones
    still advancing keep their alternating order.
    """
    seeding: list[tuple[int, int]] = []
    for col in range(max((one.count for one in slices), default=0)):
        ordered = list(slices)
        if mode != "snake" and col % 2:
            ordered.reverse()
        seeding.extend((one.item_id, one.start + col) for one in ordered if col < one.count)
    return seeding


def separate_groups(seeding: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """``seeding`` rearranged so no first-round match seats two teams of one group.

    A generated bracket lays its seeds out 1-vs-N (``seeding_order``): seed
    ``i`` opens against seed ``size - 1 - i``, the top seeds taking the byes.
    No column order guarantees anything about that -- ``cross`` opens A1
    against A2 in a four-team bracket, ``snake`` C1 against C2 when three
    groups send two. A clash is resolved by swapping the lower seed with
    another team of the same finishing place, so every place keeps its band of
    seeds; one that no such swap resolves stays.
    """
    order = list(seeding)
    count = len(order)
    if count < 2:
        return order
    layout = seeding_order(1 << (count - 1).bit_length())
    opponent: dict[int, int] = {}
    for home, away in zip(layout[::2], layout[1::2], strict=True):
        if home < count and away < count:
            opponent[home], opponent[away] = away, home

    def clashes(seed: int) -> bool:
        other = opponent.get(seed)
        return other is not None and order[seed][0] == order[other][0]

    for better in sorted(opponent):
        lower = opponent[better]
        if lower < better or not clashes(better):
            continue
        for candidate in range(count):
            if candidate in (better, lower) or order[candidate][1] != order[lower][1]:
                continue
            order[lower], order[candidate] = order[candidate], order[lower]
            if not clashes(lower) and not clashes(candidate):
                break
            order[lower], order[candidate] = order[candidate], order[lower]
    return order


@dataclass(frozen=True, slots=True)
class SeatSource:
    """One input result row to seat: who, and where it finished upstream (a group's place, for ``cross``/``snake``)."""

    result_id: int
    team_id: int
    stage_item_id: int | None
    item_rank: int | None
    #: A double-elimination row that starts in the lower bracket (``breakdown["bracket"] == "lower"``).
    lower: bool = False


_BRACKET_ITEMS = (
    enums.StageItemType.BRACKET_UPPER,
    enums.StageItemType.SINGLE_BRACKET,
    enums.StageItemType.BRACKET_LOWER,
)


def _seat_band(
    band: Sequence[SeatSource],
    ranking: SeedRanking,
    *,
    arrange_groups: bool,
    source_item_order: Mapping[int, int],
) -> list[SeatSource]:
    """One bracket half in slot order: the input order, or ``cross``/``snake`` over the groups the rows came from."""
    if ranking not in (SeedRanking.CROSS, SeedRanking.SNAKE) or any(
        one.stage_item_id is None or one.item_rank is None for one in band
    ):
        return list(band)
    by_item: dict[int, list[SeatSource]] = {}
    for one in sorted(band, key=lambda one: one.item_rank or 0):
        by_item.setdefault(one.stage_item_id or 0, []).append(one)
    # A band's places need not be contiguous ("top" over a ragged table), so slices count places, not item_rank.
    slices = [
        GroupSlice(item_id, 1, len(rows))
        for item_id, rows in sorted(
            by_item.items(), key=lambda pair: (source_item_order.get(pair[0], len(by_item)), pair[0])
        )
    ]
    seeding = build_seeding(slices, ranking.value)
    if arrange_groups:
        seeding = separate_groups(seeding)
    return [by_item[item_id][place - 1] for item_id, place in seeding]


def plan_seats(
    sources: Sequence[SeatSource],
    *,
    ranking: SeedRanking,
    target_items: Sequence[Any],
    double_elimination: bool,
    arrange_groups: bool,
    source_item_order: Mapping[int, int],
    rng_seed: int,
) -> dict[int, list[SeatSource]]:
    """Target stage item id -> its sources in slot order.

    Bracket targets (``arrange_groups``: also keep a group's teams apart in round 1 -- off for a bracket template,
    whose layout is fixed): lower starters go to the ``BRACKET_LOWER`` item of a double-elimination stage and
    everyone else to the upper / single bracket; each half is seated by :func:`_seat_band`. Group targets: a snake
    deal in input order, or a shuffled round-robin for ``random``.
    """
    items = sorted(target_items, key=lambda item: item.order)
    if not any(item.type in _BRACKET_ITEMS for item in items):
        rows = list(sources)
        if ranking is SeedRanking.RANDOM:
            random.Random(rng_seed).shuffle(rows)
        plan: dict[int, list[SeatSource]] = {item.id: [] for item in items}
        for index, one in enumerate(rows):
            plan[items[group_for_index(index, len(items), snake=ranking is not SeedRanking.RANDOM)].id].append(one)
        return plan

    lower_item = next((item for item in items if item.type == enums.StageItemType.BRACKET_LOWER), None)
    upper_item = next(item for item in items if item.type != enums.StageItemType.BRACKET_LOWER)
    lower = [one for one in sources if one.lower] if double_elimination else []
    if lower and lower_item is None:
        raise ValueError("lower bracket item missing")
    upper = [one for one in sources if not (double_elimination and one.lower)]
    plan = {item.id: [] for item in items}
    plan[upper_item.id] = _seat_band(upper, ranking, arrange_groups=arrange_groups, source_item_order=source_item_order)
    if lower_item is not None:
        plan[lower_item.id] = _seat_band(
            lower, ranking, arrange_groups=arrange_groups, source_item_order=source_item_order
        )
    return plan
