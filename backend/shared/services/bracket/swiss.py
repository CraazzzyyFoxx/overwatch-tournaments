"""Swiss round generator with Monrad-first pairing preferences.

The generator keeps Monrad ordering as the primary preference:
- higher score groups are processed first
- same-score opponents are preferred over float-down pairings
- within a score group, top-half vs bottom-half pairings are preferred

Re-matches are never allowed. When a full round cannot be built without a
re-match, the Swiss scope must end early.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from .types import BracketSkeleton, Pairing

_NON_CANONICAL_DISTANCE = 10_000


class SwissPairingImpossibleError(ValueError):
    """Raised when no complete Swiss round can be built without a rematch."""


@dataclass(frozen=True)
class SwissStanding:
    team_id: int
    points: float
    buchholz: float = 0.0


@dataclass(frozen=True)
class _TeamMeta:
    rank_index: int
    group_index: int
    pos_in_group: int
    group_size: int

    @property
    def half_size(self) -> int:
        return self.group_size // 2

    @property
    def is_top_half(self) -> bool:
        return self.pos_in_group < self.half_size

    @property
    def is_bottom_half(self) -> bool:
        return self.half_size <= self.pos_in_group < self.half_size * 2


def _bye_candidates(team_ids: list[int], bye_history: set[int]) -> list[int | None]:
    if len(team_ids) % 2 == 0:
        return [None]

    lowest_first = list(reversed(team_ids))
    without_bye = [team_id for team_id in lowest_first if team_id not in bye_history]
    return without_bye or lowest_first


def _build_team_meta(sorted_teams: list[SwissStanding]) -> dict[int, _TeamMeta]:
    metadata: dict[int, _TeamMeta] = {}
    groups: list[list[SwissStanding]] = []
    current_group: list[SwissStanding] = []
    group_key: float | None = None

    for standing in sorted_teams:
        key = standing.points
        if key != group_key and current_group:
            groups.append(current_group)
            current_group = []
        group_key = key
        current_group.append(standing)
    if current_group:
        groups.append(current_group)

    rank_index = 0
    for group_index, group in enumerate(groups):
        group_size = len(group)
        for pos_in_group, standing in enumerate(group):
            metadata[standing.team_id] = _TeamMeta(
                rank_index=rank_index,
                group_index=group_index,
                pos_in_group=pos_in_group,
                group_size=group_size,
            )
            rank_index += 1

    return metadata


def _pair_bucket(anchor: _TeamMeta, candidate: _TeamMeta) -> int:
    if anchor.group_index == candidate.group_index:
        if (
            (anchor.is_top_half and candidate.is_bottom_half)
            or (anchor.is_bottom_half and candidate.is_top_half)
        ):
            return 0
        return 1
    return 2


def _canonical_distance(anchor: _TeamMeta, candidate: _TeamMeta) -> int:
    if anchor.group_index != candidate.group_index:
        return _NON_CANONICAL_DISTANCE

    if anchor.is_top_half and candidate.is_bottom_half:
        expected = anchor.half_size + anchor.pos_in_group
        return abs(candidate.pos_in_group - expected)

    if anchor.is_bottom_half and candidate.is_top_half:
        expected = anchor.pos_in_group - anchor.half_size
        return abs(candidate.pos_in_group - expected)

    return _NON_CANONICAL_DISTANCE


def _pair_priority(
    anchor_team_id: int,
    candidate_team_id: int,
    *,
    metadata: dict[int, _TeamMeta],
) -> tuple[int, int, int, int, int]:
    anchor = metadata[anchor_team_id]
    candidate = metadata[candidate_team_id]

    group_distance = abs(anchor.group_index - candidate.group_index)
    pair_bucket = _pair_bucket(anchor, candidate)
    canonical_distance = _canonical_distance(anchor, candidate)
    rank_distance = abs(candidate.rank_index - anchor.rank_index)

    return (
        pair_bucket,
        group_distance,
        canonical_distance,
        rank_distance,
        candidate.rank_index,
    )


def _find_pairings(
    team_ids: list[int],
    *,
    metadata: dict[int, _TeamMeta],
    played_pairs: set[frozenset[int]],
) -> list[tuple[int, int]] | None:
    ordered_team_ids = tuple(team_ids)

    @cache
    def _search(remaining: tuple[int, ...]) -> tuple[tuple[int, int], ...] | None:
        if not remaining:
            return ()

        anchor_team_id = remaining[0]
        candidates = sorted(
            remaining[1:],
            key=lambda candidate_team_id: _pair_priority(
                anchor_team_id,
                candidate_team_id,
                metadata=metadata,
            ),
        )

        for candidate_team_id in candidates:
            pair_key = frozenset({anchor_team_id, candidate_team_id})
            if pair_key in played_pairs:
                continue

            next_remaining = tuple(
                team_id
                for team_id in remaining[1:]
                if team_id != candidate_team_id
            )
            remainder = _search(next_remaining)
            if remainder is None:
                continue
            return ((anchor_team_id, candidate_team_id),) + remainder

        return None

    result = _search(ordered_team_ids)
    if result is None:
        return None
    return list(result)


def generate_round(
    standings: list[SwissStanding],
    played_pairs: set[frozenset[int]],
    round_number: int,
    *,
    bye_history: set[int] | None = None,
) -> BracketSkeleton:
    """Generate pairings for one Swiss round using Monrad-first preferences.

    Args:
        standings: Current standings.
        played_pairs: Set of frozensets of team_id pairs already played.
        round_number: Round number for generated pairings.
        bye_history: Optional set of team_ids that already received a bye.
    """
    sorted_teams = sorted(
        standings, key=lambda standing: (standing.points, standing.buchholz), reverse=True
    )
    team_ids = [standing.team_id for standing in sorted_teams]
    bye_history = bye_history or set()

    bye_candidate: int | None = None
    pair_order: list[tuple[int, int]] | None = None
    for candidate in _bye_candidates(team_ids, bye_history):
        pairing_standings = [
            standing for standing in sorted_teams if standing.team_id != candidate
        ]
        pairing_team_ids = [standing.team_id for standing in pairing_standings]
        metadata = _build_team_meta(pairing_standings)
        pair_order = _find_pairings(
            pairing_team_ids,
            metadata=metadata,
            played_pairs=played_pairs,
        )
        if pair_order is not None:
            bye_candidate = candidate
            break

    if pair_order is None:
        raise SwissPairingImpossibleError(
            "Unable to generate a complete Swiss round without rematches"
        )

    pairings = [
        Pairing(
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            round_number=round_number,
            name=f"Swiss R{round_number} Match {index}",
            local_id=index - 1,
        )
        for index, (home_team_id, away_team_id) in enumerate(pair_order, start=1)
    ]

    return BracketSkeleton(
        pairings=pairings,
        total_rounds=1,
        bye_team_id=bye_candidate,
    )
