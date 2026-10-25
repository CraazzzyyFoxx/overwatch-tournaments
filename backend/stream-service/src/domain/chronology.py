"""Which matches a POV broadcast contains, and how far into its VOD each one starts.

Pure: no session, no I/O. The reader (``src.services.chronology``) loads the timings; this module decides.

Timing source, per encounter: one chapter per logged map when the encounter has any map with a trustworthy log
time (the caller passes only those), else one series chapter from ``started_at`` when that is set, else nothing.
``scheduled_at`` and ``confirmed_at`` are never used: neither says when anybody was playing.

The broadcast covers ``[started_at - delay, last_seen_at - delay]`` of match time: a stream on a delay shows a
moment ``delay`` seconds after it happened, so the content window is the stream window shifted back by it.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

__all__ = ("Chapter", "EncounterTiming", "LoggedMap", "chapters")


@dataclass(frozen=True, slots=True)
class LoggedMap:
    played_at: datetime
    duration_s: float | None
    position: int | None
    map_name: str | None


@dataclass(frozen=True, slots=True)
class EncounterTiming:
    encounter_id: int
    name: str
    started_at: datetime | None
    ended_at: datetime | None
    #: Only maps whose log time is valid; empty when none is.
    maps: tuple[LoggedMap, ...] = ()


@dataclass(frozen=True, slots=True)
class Chapter:
    encounter_id: int
    encounter_name: str
    kind: Literal["map", "series"]
    map_position: int | None
    map_name: str | None
    #: Seconds into the VOD, delay applied; 0 for a match already running when the stream began.
    offset_s: int


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

    def chapter(encounter: EncounterTiming, start: datetime, game: LoggedMap | None) -> Chapter:
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
        if encounter.maps:
            for game in encounter.maps:
                end = game.played_at + timedelta(seconds=game.duration_s or 0)
                if game.played_at <= window_end and end >= window_start:
                    found.append(chapter(encounter, game.played_at, game))
        elif encounter.started_at is not None:
            start, end = encounter.started_at, encounter.ended_at
            if end is not None:
                included = start <= window_end and end >= window_start
            else:
                included = window_start <= start <= window_end
            if included:
                found.append(chapter(encounter, start, None))

    found.sort(key=lambda c: (c.offset_s, c.encounter_id, c.map_position is None, c.map_position or 0))
    return found
