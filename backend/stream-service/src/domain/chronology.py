"""Which matches a POV broadcast contains, and how far into its VOD each one starts.

Pure: no session, no I/O. The reader (``src.services.chronology``) loads the facts; this module decides.

A map's start, first source that answers:

1. the log's own start (``played_at``), unless it is the decoder's fallback — the upload time of a log that carried
   no usable timestamp (``played_at == uploaded_at``);
2. the log's file name: Overwatch's game client names its Workshop logs ``Log-YYYY-MM-DD-HH-MM-SS.txt`` on the host
   PC's local clock. That clock's UTC offset is unknown and differs per host, so it is chosen from server-side
   events: the map starts right after the pre-game room finished the bans of its round, and ends before its result
   was reported, the series confirmed or the log uploaded;
3. no usable log: the moment the pre-game room finished the bans of the map's round — a little before the map
   actually starts, which is the safe side for a viewer.

An encounter with no map timed that way gets one series chapter: the pre-game phase's start (the room opening, else
the last team confirming it is ready), else the organizer's start. Its end is the organizer's end, else the result
confirmation. ``scheduled_at`` is never used: it says when a match was planned, not when anybody played.

The broadcast covers ``[started_at - delay, last_seen_at - delay]`` of match time: a stream on a delay shows a moment
``delay`` seconds after it happened, so the content window is the stream window shifted back by it.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

__all__ = ("Chapter", "EncounterTiming", "LoggedMap", "PlayedGame", "chapters")

_LOG_CLOCK = re.compile(r"Log-(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})")
#: UTC-12 .. UTC+14 in whole hours. ponytail: a :30/:45 zone (India, Nepal) lands its remainder off; try quarter
#: hours only against a round's end, the one anchor tight enough to tell them apart.
_UTC_OFFSETS = tuple(timedelta(hours=hours) for hours in range(-12, 15))
#: How far a host PC's clock may run ahead of the server's and its map still count as ended before an anchor.
_CLOCK_SKEW = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class LoggedMap:
    """One parsed log of the encounter."""

    #: The series position (``encounter.game``) the log is bound to; ``None`` for an unbound log.
    position: int | None
    map_name: str | None
    #: The decoder's start: the upload time when the log carried no usable timestamp.
    played_at: datetime | None
    duration_s: float | None
    #: When the log was handed over (its ingest job's creation); ``None`` once the job is gone.
    uploaded_at: datetime | None
    filename: str | None


@dataclass(frozen=True, slots=True)
class PlayedGame:
    """One position of the series as the tournament decided it."""

    position: int
    map_name: str | None
    #: When its result was accepted (the captains' reports, or an admin): after the map ended.
    confirmed_at: datetime | None


@dataclass(frozen=True, slots=True)
class EncounterTiming:
    encounter_id: int
    name: str
    #: The organizer's own start and end of the series.
    started_at: datetime | None
    ended_at: datetime | None
    #: The series result's confirmation.
    confirmed_at: datetime | None = None
    #: The pre-game room's opening, and the last team confirming it is ready.
    room_opened_at: datetime | None = None
    last_ready_at: datetime | None = None
    maps: tuple[LoggedMap, ...] = ()
    games: tuple[PlayedGame, ...] = ()
    #: When the pre-game room finished each round's bans, keyed by round — a round is a series position.
    round_ends: Mapping[int, datetime] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Chapter:
    encounter_id: int
    encounter_name: str
    kind: Literal["map", "series"]
    map_position: int | None
    map_name: str | None
    #: Seconds into the VOD, delay applied; 0 for a match already running when the stream began.
    offset_s: int


@dataclass(frozen=True, slots=True)
class _MapWindow:
    position: int | None
    map_name: str | None
    start: datetime
    end: datetime


def _log_clock(filename: str | None) -> datetime | None:
    """The host's wall clock at the log's start, carried as if it were UTC until an offset is chosen."""
    found = _LOG_CLOCK.search(filename or "")
    if found is None:
        return None
    try:
        return datetime(*(int(part) for part in found.groups()), tzinfo=UTC)
    except ValueError:
        return None


def _from_log_clock(
    clock: datetime, duration: timedelta, *, round_end: datetime | None, reported: datetime | None
) -> datetime | None:
    """The map's UTC start under the host offset the server-side events agree with.

    With the round's end, the start nearest to it: the map follows its bans within a minute or two. Otherwise the
    latest start whose map still ended before ``reported`` (the earliest event known to come after it).
    """
    starts = [clock - offset for offset in _UTC_OFFSETS]
    if round_end is not None:
        return min(starts, key=lambda start: abs(start - round_end))
    if reported is not None:
        return max((start for start in starts if start + duration <= reported + _CLOCK_SKEW), default=None)
    return None


def _map_windows(encounter: EncounterTiming) -> list[_MapWindow]:
    games = {game.position: game for game in encounter.games}
    windows: list[_MapWindow] = []
    for log in encounter.maps:
        duration = timedelta(seconds=log.duration_s or 0)
        if log.played_at is not None and log.played_at != log.uploaded_at:
            start: datetime | None = log.played_at
        elif (clock := _log_clock(log.filename)) is not None:
            game = games.get(log.position) if log.position is not None else None
            after = [game.confirmed_at if game else None, log.uploaded_at, encounter.confirmed_at]
            start = _from_log_clock(
                clock,
                duration,
                round_end=encounter.round_ends.get(log.position) if log.position is not None else None,
                reported=min((moment for moment in after if moment is not None), default=None),
            )
        else:
            start = None
        if start is not None:
            windows.append(_MapWindow(log.position, log.map_name, start, start + duration))

    timed = {window.position for window in windows}
    for game in encounter.games:
        start = encounter.round_ends.get(game.position)
        if start is not None and game.position not in timed:
            windows.append(_MapWindow(game.position, game.map_name, start, max(start, game.confirmed_at or start)))
    return windows


def chapters(
    encounters: Iterable[EncounterTiming],
    *,
    started_at: datetime,
    last_seen_at: datetime,
    delay_s: int,
) -> list[Chapter]:
    """The chapters of one broadcast, sorted by ``(offset_s, encounter_id, map_position nulls last)``.

    A map is in when it overlaps the content window. A series with an end is in on the same overlap; one with no
    end yet is in only when it started inside the window — an open series that began before the stream is not
    evidence the stream shows any of it.
    """
    window_start = started_at - timedelta(seconds=delay_s)
    window_end = last_seen_at - timedelta(seconds=delay_s)

    def chapter(encounter: EncounterTiming, start: datetime, game: _MapWindow | None) -> Chapter:
        return Chapter(
            encounter_id=encounter.encounter_id,
            encounter_name=encounter.name,
            kind="map" if game is not None else "series",
            map_position=game.position if game is not None else None,
            map_name=game.map_name if game is not None else None,
            offset_s=int(max(timedelta(0), start - window_start).total_seconds()),
        )

    found: list[Chapter] = []
    for encounter in encounters:
        if windows := _map_windows(encounter):
            for window in windows:
                if window.start <= window_end and window.end >= window_start:
                    found.append(chapter(encounter, window.start, window))
            continue
        start = encounter.room_opened_at or encounter.last_ready_at or encounter.started_at
        if start is None:
            continue
        end = encounter.ended_at or encounter.confirmed_at
        if end is not None:
            included = start <= window_end and end >= window_start
        else:
            included = window_start <= start <= window_end
        if included:
            found.append(chapter(encounter, start, None))

    found.sort(key=lambda c: (c.offset_s, c.encounter_id, c.map_position is None, c.map_position or 0))
    return found
