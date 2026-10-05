"""Scores of the maps whose match log carries no result.

The Workshop log writes ``match_end`` and ``round_end`` of a Push (and Clash)
map as 0:0 whoever won, and nothing else in the log names the winner. So the
log is never trusted for these modes: the score comes from the tournament's
accepted result for that map, or -- when there is none -- by exclusion from the
completed series score and the other maps' logged results. Anything that cannot
be decided exactly stays 0:0; nothing is guessed.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

__all__ = (
    "OBJECTIVELESS_GAMEMODES",
    "AcceptedGame",
    "LoggedMap",
    "Series",
    "resolve_scores",
)

#: Gamemode slugs whose log ``match_end`` is always 0:0.
OBJECTIVELESS_GAMEMODES = frozenset({"push", "clash"})

UNKNOWN = (0, 0)


@dataclass(frozen=True)
class Series:
    home_team_id: int | None
    away_team_id: int | None
    completed: bool
    home_score: int
    away_score: int


@dataclass(frozen=True)
class LoggedMap:
    """One ``matches.match`` row; scores in the row's own (log) orientation."""

    match_id: int
    map_id: int
    home_team_id: int
    home_score: int
    away_score: int
    objectiveless: bool


@dataclass(frozen=True)
class AcceptedGame:
    """A confirmed ``encounter_game``; scores in the encounter's orientation."""

    map_id: int | None
    home_score: int
    away_score: int


def resolve_scores(
    series: Series, maps: Sequence[LoggedMap], games: Sequence[AcceptedGame]
) -> dict[int, tuple[int, int]]:
    """``match_id -> (home, away)`` in the match's orientation, for every
    objectiveless map; ``(0, 0)`` where the result cannot be decided."""
    flipped: dict[int, bool] = {}
    for m in maps:
        if series.home_team_id is not None and m.home_team_id == series.home_team_id:
            flipped[m.match_id] = False
        elif series.away_team_id is not None and m.home_team_id == series.away_team_id:
            flipped[m.match_id] = True

    def orient(m: LoggedMap, score: tuple[int, int]) -> tuple[int, int]:
        return (score[1], score[0]) if flipped[m.match_id] else score

    # A map the series played twice lands on one match row: which play it is
    # cannot be told, so neither game decides it.
    plays = Counter(game.map_id for game in games)
    accepted = {g.map_id: (g.home_score, g.away_score) for g in games if g.map_id is not None and plays[g.map_id] == 1}

    resolved: dict[int, tuple[int, int]] = {}
    unknown: list[LoggedMap] = []
    for m in maps:
        if not m.objectiveless:
            continue
        if m.match_id in flipped and m.map_id in accepted:
            resolved[m.match_id] = orient(m, accepted[m.map_id])
        else:
            unknown.append(m)

    # Exclusion counts every map's winner, so every map must be oriented.
    if unknown and series.completed and len(flipped) == len(maps):
        unknown_ids = {m.match_id for m in unknown}
        # Encounter-oriented scores of every map whose result is known.
        known = [
            orient(m, resolved.get(m.match_id, (m.home_score, m.away_score)))
            for m in maps
            if m.match_id not in unknown_ids
        ]
        winners = _by_exclusion(series, known, len(unknown), played=len(games) or None)
        if winners is not None:
            for m in unknown:
                resolved[m.match_id] = orient(m, winners)

    return {m.match_id: resolved.get(m.match_id, UNKNOWN) for m in maps if m.objectiveless}


def _by_exclusion(
    series: Series, known: Sequence[tuple[int, int]], unknown: int, *, played: int | None
) -> tuple[int, int] | None:
    """The one score every unknown map must have, or ``None`` if it is not forced.

    ``played`` is the number of games the series accepted, when it tracked
    games at all; a log count that differs means a log is missing.
    """
    if played is not None and played != len(known) + unknown:
        return None
    home_left = series.home_score - sum(1 for home, away in known if home > away)
    away_left = series.away_score - sum(1 for home, away in known if away > home)
    # Wins left over must account for every unknown map exactly: fewer means a
    # draw somewhere (or a missing log), more means a log is missing.
    if home_left < 0 or away_left < 0 or home_left + away_left != unknown:
        return None
    # Both sides still owed wins over several maps: which map is whose is open.
    if home_left and away_left:
        return None
    return (1, 0) if home_left else (0, 1)
