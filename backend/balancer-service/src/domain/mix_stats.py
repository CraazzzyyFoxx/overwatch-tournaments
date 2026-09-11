"""Win/loss bookkeeping for every member who ever sat in a workspace's mixes.

Pure domain algorithm: no I/O, no ORM, no async. The caller (custom game
service) reads one row per recorded seat -- ``casual.player`` joined to its own
team, the other team and the match -- turns each into a :class:`SeatOutcome`
via :func:`outcome_for`, and hands the whole list to
:func:`aggregate_mix_stats`.

One seat is one counted game: a member who played five maps across three
different mixes has five seats, and the mix they belong to never enters the
arithmetic -- this is the workspace-wide scoreboard, not a per-game one. The
seat's *role* is a second, optional axis: the totals always count it, the
per-role split only does when the seat recorded a role at all, so a lineup
balanced without roles still adds up.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

__all__ = ("Outcome", "SeatOutcome", "RoleTally", "MemberMixStats", "aggregate_mix_stats", "outcome_for")

Outcome = Literal["win", "loss", "draw"]


@dataclass(frozen=True)
class SeatOutcome:
    """One recorded seat: who sat, in which role, in which match, and how it went.

    ``match_id`` orders seats in the order they were played -- ids are
    monotonic per recording, ``played_at`` is not guaranteed distinct between
    two maps recorded in the same second -- and is what the streak walks back
    from. ``role`` is the wire spelling (``tank``/``dps``/``support``) or
    ``None`` for a seat recorded without one.
    """

    member_id: int
    role: str | None
    match_id: int
    played_at: datetime
    outcome: Outcome


@dataclass(frozen=True)
class RoleTally:
    games: int
    wins: int
    losses: int
    draws: int


@dataclass(frozen=True)
class MemberMixStats:
    member_id: int
    games: int
    wins: int
    losses: int
    draws: int
    win_rate: float
    streak: int
    last_played_at: datetime | None
    by_role: dict[str, RoleTally]


def outcome_for(own_score: int, other_score: int) -> Outcome:
    """A seat's result is its own team's score against the other side's.

    Relative, never absolute: a casual match stores two scored sides and no
    winner flag, so "did this seat win" is only answerable next to the other
    team's number.
    """
    if own_score > other_score:
        return "win"
    if own_score < other_score:
        return "loss"
    return "draw"


def _streak(outcomes: Sequence[Outcome]) -> int:
    """Current run counted back from the newest match: ``+N`` wins, ``-N`` losses.

    A draw ends the run wherever it lands -- newest match a draw means ``0``,
    since neither a win nor a loss streak is running.
    """
    if not outcomes:
        return 0
    newest = outcomes[0]
    if newest == "draw":
        return 0
    run = 0
    for outcome in outcomes:
        if outcome != newest:
            break
        run += 1
    return run if newest == "win" else -run


def aggregate_mix_stats(seats: Sequence[SeatOutcome]) -> list[MemberMixStats]:
    """Fold every seat into one row per member, best record first.

    Ordering is the scoreboard's own: most wins, then the better win rate,
    then the bigger sample, then member id so equal records never shuffle
    between two reads of the same data.
    """
    by_member: dict[int, list[SeatOutcome]] = {}
    for seat in seats:
        by_member.setdefault(seat.member_id, []).append(seat)

    stats: list[MemberMixStats] = []
    for member_id, member_seats in by_member.items():
        ordered = sorted(member_seats, key=lambda s: s.match_id, reverse=True)
        wins = sum(1 for s in ordered if s.outcome == "win")
        losses = sum(1 for s in ordered if s.outcome == "loss")
        draws = sum(1 for s in ordered if s.outcome == "draw")
        games = len(ordered)

        by_role: dict[str, RoleTally] = {}
        for seat in ordered:
            if seat.role is None:
                continue
            tally = by_role.get(seat.role, RoleTally(0, 0, 0, 0))
            by_role[seat.role] = RoleTally(
                games=tally.games + 1,
                wins=tally.wins + (seat.outcome == "win"),
                losses=tally.losses + (seat.outcome == "loss"),
                draws=tally.draws + (seat.outcome == "draw"),
            )

        stats.append(
            MemberMixStats(
                member_id=member_id,
                games=games,
                wins=wins,
                losses=losses,
                draws=draws,
                # Guard, not a real case: a member only reaches this loop by
                # owning at least one seat.
                win_rate=(wins / games) if games else 0.0,
                streak=_streak([s.outcome for s in ordered]),
                last_played_at=ordered[0].played_at if ordered else None,
                by_role=by_role,
            )
        )

    stats.sort(key=lambda s: (-s.wins, -s.win_rate, -s.games, s.member_id))
    return stats
