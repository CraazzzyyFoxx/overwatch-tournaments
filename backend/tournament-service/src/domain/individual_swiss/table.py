"""Personal table rules for individual Swiss: ordering, totals, qualification cut, captains."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from src.domain.individual_swiss.pool import PoolPlayer


@dataclass(frozen=True)
class StandingLine:
    member_id: int
    role: str
    rank: int
    points: float
    map_diff: float
    buchholz: float


@dataclass(frozen=True)
class SeatResult:
    members: tuple[int, ...]
    score: float
    placement: int | None


@dataclass(frozen=True)
class MatchResult:
    seats: tuple[SeatResult, SeatResult]


@dataclass
class PlayerTotals:
    points: float = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    maps_won: float = 0
    maps_lost: float = 0
    buchholz: float = 0
    matches_played: int = 0

    @property
    def map_diff(self) -> float:
        return self.maps_won - self.maps_lost


def order_role(lines: Sequence[StandingLine], pins: Mapping[int, int]) -> list[int]:
    """Member ids of one role, best first; a pinned member takes its 1-based position."""
    ranked = sorted(lines, key=lambda x: (-x.points, -x.map_diff, -x.buchholz, -x.rank, x.member_id))
    ids = [x.member_id for x in ranked]
    size = len(ids)
    slots: list[int | None] = [None] * size
    known = set(ids)
    pinned = sorted((pos, m) for m, pos in pins.items() if m in known)
    for pos, member in pinned:
        at = min(max(pos, 1), size) - 1
        # a clash (pins clamped to the end, or duplicates) takes the next free slot, else the nearest before
        free = [i for i in range(size) if slots[i] is None]
        slots[next((i for i in free if i >= at), free[-1])] = member
    pinned_ids = {m for _, m in pinned}
    rest = iter(m for m in ids if m not in pinned_ids)
    return [m if m is not None else next(rest) for m in slots]


def compute_totals(
    members: Iterable[int], results: Sequence[MatchResult], *, win: float, draw: float, loss: float
) -> dict[int, PlayerTotals]:
    totals = {m: PlayerTotals() for m in members}
    for match in results:
        for seat, other in (match.seats, match.seats[::-1]):
            first, other_first = seat.placement == 1, other.placement == 1
            for m in seat.members:
                t = totals.setdefault(m, PlayerTotals())
                if first and other_first:
                    t.draws, t.points = t.draws + 1, t.points + draw
                elif first:
                    t.wins, t.points = t.wins + 1, t.points + win
                else:
                    t.losses, t.points = t.losses + 1, t.points + loss
                t.maps_won += seat.score
                t.maps_lost += other.score
                t.matches_played += 1
    # Buchholz needs the opponents' final points, hence the second pass.
    for match in results:
        for seat, other in (match.seats, match.seats[::-1]):
            if other.members:
                mean = sum(totals.setdefault(o, PlayerTotals()).points for o in other.members) / len(other.members)
                for m in seat.members:
                    totals[m].buchholz += mean
    return totals


def qualify(order: Mapping[str, Sequence[int]], shape: Mapping[str, int], k: int) -> set[int]:
    return {m for role, n in shape.items() for m in order[role][: k * n]}


def pick_captains(qualified: Sequence[PoolPlayer], k: int) -> list[int]:
    return [p.member_id for p in sorted(qualified, key=lambda p: (-p.rank, p.member_id))[:k]]
