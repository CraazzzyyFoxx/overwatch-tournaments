"""Every pure decision about seed ORDER, in one module.

Three layers, all of them here, none of them touching a session:

1. ``SeedRanking`` — the order a stage hands to the bracket engine, which
   treats ``team_ids[0]`` as seed 1 (plays the lowest seed). Lives in
   ``Stage.settings_json.seed_ranking`` (same bag as ``best_of``):

   - ``slot`` (default): keep StageItemInput slot order — standings wiring,
     manual slots, and every existing tournament stay unchanged.
   - ``avg_sr``: highest ``Team.avg_sr`` is seed 1.
   - ``total_sr``: highest ``Team.total_sr`` is seed 1.
   - ``random``: ``random.Random(stage.id)`` shuffle, stable across processes.

2. Group distribution — ``parse_seed_mode`` + ``group_for_index``: the
   ``seed_teams`` vocabulary (``snake_sr``/``by_total_sr``/``random``) and the
   snake/round-robin deal across a stage's groups.

3. Group -> playoff wiring — ``group_advance_counts`` + ``build_seeding``: how
   many teams each group sends (``StageItem.advance_count`` overriding
   ``Stage.advance_count``) and which (group, position) pair lands in which
   playoff slot, ``cross`` or ``snake``.

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
    "advance_split",
    "apply_seed_ranking",
    "bracket_seeds",
    "build_seeding",
    "collect_item_team_ids",
    "group_advance_counts",
    "group_for_index",
    "lower_bracket_item",
    "parse_seed_mode",
    "parse_seed_ranking",
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


def parse_seed_ranking(settings_json: Any) -> SeedRanking:
    if not isinstance(settings_json, dict):
        return SeedRanking.SLOT
    raw = settings_json.get("seed_ranking")
    try:
        return SeedRanking(raw)
    except (TypeError, ValueError):
        return SeedRanking.SLOT


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
    stage: Any,
    sorted_items: list,
    lb_item: Any | None,
    *,
    collect: Any = collect_item_team_ids,
) -> tuple[list[int], list[int]]:
    """The teams wired into ``stage``, split into upper vs lower starters."""
    if stage.stage_type == enums.StageType.DOUBLE_ELIMINATION and getattr(stage, "split_lower_bracket", False):
        if lb_item is not None:
            upper = [tid for item in sorted_items if item is not lb_item for tid in collect(item)]
            return upper, collect(lb_item)
        all_ids = [tid for item in sorted_items for tid in collect(item)]
        half = (len(all_ids) + 1) // 2
        return all_ids[:half], all_ids[half:]
    return [tid for item in sorted_items for tid in collect(item)], []


def advance_split(stage: Any, advance: int) -> tuple[int, int]:
    """How many of each group's ``advance_count`` teams seed upper vs lower."""
    if (
        stage.stage_type == enums.StageType.DOUBLE_ELIMINATION
        and getattr(stage, "split_lower_bracket", False)
        and any(item.type == enums.StageItemType.BRACKET_LOWER for item in stage.items)
    ):
        lower = advance // 2
        return advance - lower, lower
    return advance, 0


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
    stage: Any,
    source_items: Sequence[Any],
    *,
    default_upper: int,
    default_lower: int = 0,
) -> list[tuple[int, int, int]]:
    """Per source group: ``(item_id, upper_count, lower_count)``.

    A group's own ``advance_count`` overrides the stage-wide default for that
    group alone, and is split upper/lower by :func:`advance_split` — the same
    rule auto-wiring applies to ``Stage.advance_count``. Groups without an
    override keep the caller's explicit ``default_upper``/``default_lower``
    verbatim, so a manual wire asking for "3 up, 1 down" is not silently
    re-split into 2/2.

    ``0`` is deliberately NOT "nobody advances from this group": the schema
    rejects it (``ge=1``) and a stored 0 reads here as "no override". A group
    that sends nobody is expressed by leaving it out of the wiring, not by a
    number that is indistinguishable from an unset column.
    """
    counts: list[tuple[int, int, int]] = []
    for item in source_items:
        override = getattr(item, "advance_count", None)
        if override:
            upper, lower = advance_split(stage, override)
        else:
            upper, lower = default_upper, default_lower
        counts.append((item.id, upper, lower))
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
