"""Every pure decision about seed ORDER, in one module.

Three layers, all of them here, none of them touching a session:

1. ``SeedRanking`` — the order a stage hands to the bracket engine, which
   treats ``team_ids[0]`` as seed 1 (plays the lowest seed). Lives in
   ``Stage.seed_ranking``:

   - ``slot`` (default): keep StageItemInput slot order — standings wiring,
     manual slots, and every existing tournament stay unchanged.
   - ``avg_sr``: highest ``Team.avg_sr`` is seed 1.
   - ``total_sr``: highest ``Team.total_sr`` is seed 1.
   - ``random``: ``random.Random(stage.id)`` shuffle, stable across processes.

2. Group distribution — ``parse_seed_mode`` + ``group_for_index``: the
   ``seed_teams`` vocabulary (``snake_sr``/``by_total_sr``/``random``) and the
   snake/round-robin deal across a stage's groups.

3. Group -> playoff wiring — ``group_advance_counts`` + ``build_seeding``: how
   many teams each group sends and how many of them start upper
   (``advance_count`` / ``advance_upper_count``, a group's own value overriding
   its stage's), and which (group, position) pair lands in which playoff slot,
   ``cross`` or ``snake``.

The one seeding rule NOT here is the engine's 1-vs-N slot layout
(``shared.services.bracket.seeding_order``): it is shared by every service that
builds a bracket, so it stays next to the generators that apply it.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from dataclasses import replace
from enum import StrEnum
from typing import Any, NamedTuple, Protocol

from shared.core import enums
from shared.services.bracket.types import BracketSkeleton

__all__ = (
    "SEED_TEAMS_MODES",
    "GroupSlice",
    "SeedRanking",
    "apply_seed_ranking",
    "bracket_seeds",
    "build_seeding",
    "collect_item_team_ids",
    "group_advance_counts",
    "group_for_index",
    "lower_bracket_item",
    "parse_seed_mode",
    "rank_team_ids",
    "resolve_seeds",
)


class SeedRanking(StrEnum):
    SLOT = "slot"
    AVG_SR = "avg_sr"
    TOTAL_SR = "total_sr"
    RANDOM = "random"


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
) -> list[int]:
    """Return team ids in engine seed order (index 0 = seed 1)."""
    items = list(teams)
    if ranking is SeedRanking.SLOT:
        return [team.id for team in items]
    if ranking is SeedRanking.AVG_SR:
        return [team.id for team in sorted(items, key=lambda team: (-(team.avg_sr or 0.0), team.id))]
    if ranking is SeedRanking.TOTAL_SR:
        return [team.id for team in sorted(items, key=lambda team: (-(team.total_sr or 0), team.id))]
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
    if ranking is SeedRanking.SLOT or not team_ids:
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
    """Swap placeholder negative seed ids for the teams they stand for."""

    def team_for(seed: int | None) -> int | None:
        if seed is None or seed >= 0:
            return seed
        return teams.get(seed)

    return replace(
        skeleton,
        pairings=[
            replace(pairing, home_team_id=team_for(pairing.home_team_id), away_team_id=team_for(pairing.away_team_id))
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

    ``snake``: all 1st places, then all 2nd places, ... The engine's own 1-vs-N
    layout then spreads them, which is why this is what auto-wiring uses.
    ``cross`` flips every odd column so group A's 1st cannot meet A's 2nd in
    round 1 of a bracket that is NOT re-seeded by the engine.

    Slices may be ragged (groups advancing different counts): a group that has
    run out of positions is skipped for the remaining columns, and the ones
    still advancing keep their alternating order. ``cross``'s guarantee weakens
    there — with A sending 3 and B sending 5, B's 4th and 5th have no partner
    left to alternate against, so a same-group round-1 rematch becomes possible
    again. Auto-wiring uses ``snake`` (the engine re-seeds 1-vs-N anyway), so
    only an explicit ``cross`` wire is exposed to it.
    """
    seeding: list[tuple[int, int]] = []
    for col in range(max((one.count for one in slices), default=0)):
        ordered = list(slices)
        if mode != "snake" and col % 2:
            ordered.reverse()
        seeding.extend((one.item_id, one.start + col) for one in ordered if col < one.count)
    return seeding
