"""The chapter rules of a POV VOD, and the routing of the two chronology reads.

The rules are pure (``src.domain.chronology``), so every case is a few datetimes. What each guards:

- a map overlapping the broadcast is in, one outside it is out, and a map already running when the stream began
  links to 0:00 rather than to a negative offset;
- the tournament's stream delay shifts the window AND the offsets — a delayed stream shows a match late;
- a series chapter only stands in when no map has a log time, and an open series counts only if it started on air;
- the encounter read answers a mix's encounter with nothing and an unknown one with 404, before any gate or read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.repository.stream_session import EncounterOwnerRow  # noqa: E402
from src.domain.chronology import EncounterTiming, LoggedMap, chapters  # noqa: E402
from src.rpc import reads  # noqa: E402
from src.services.chronology import stream_chronology_reader  # noqa: E402

T0 = datetime(2026, 10, 25, 17, 0, tzinfo=UTC)


def _min(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _map(minute: float, duration_min: float | None, position: int) -> LoggedMap:
    return LoggedMap(
        played_at=_min(minute),
        duration_s=None if duration_min is None else duration_min * 60,
        position=position,
        map_name=f"map{position}",
    )


def _chapters(*encounters: EncounterTiming, start: float = 0, end: float = 180, delay_s: int = 0) -> list[tuple]:
    found = chapters(encounters, started_at=_min(start), last_seen_at=_min(end), delay_s=delay_s)
    return [(c.encounter_id, c.kind, c.map_position, c.offset_s) for c in found]


class MapChapterTests(TestCase):
    def test_overlapping_maps_are_in_and_the_rest_are_out(self) -> None:
        encounter = EncounterTiming(
            encounter_id=1,
            name="A vs B",
            started_at=None,
            ended_at=None,
            maps=(_map(-30, 10, 1), _map(-5, 10, 2), _map(20, 10, 3), _map(200, 10, 4)),
        )

        # Map 1 ended before the stream; map 2 was running as it began (clamped to 0); map 4 came after it.
        self.assertEqual(_chapters(encounter), [(1, "map", 2, 0), (1, "map", 3, 1200)])

    def test_a_map_without_a_duration_is_a_point(self) -> None:
        encounter = EncounterTiming(1, "A vs B", None, None, maps=(_map(-1, None, 1), _map(30, None, 2)))

        self.assertEqual(_chapters(encounter), [(1, "map", 2, 1800)])

    def test_the_delay_shifts_window_and_offsets(self) -> None:
        # On a 120 s delay the stream shows match time [-2 min, 178 min]: a map that ended just before the stream
        # began is on it, one played in its last minute is not yet, and every offset grows by the delay.
        encounter = EncounterTiming(1, "A vs B", None, None, maps=(_map(-2, 1, 1), _map(170, 5, 2), _map(179, 5, 3)))

        self.assertEqual(_chapters(encounter, delay_s=0), [(1, "map", 2, 10200), (1, "map", 3, 10740)])
        self.assertEqual(_chapters(encounter, delay_s=120), [(1, "map", 1, 0), (1, "map", 2, 10320)])

    def test_maps_win_over_the_series(self) -> None:
        encounter = EncounterTiming(1, "A vs B", started_at=_min(5), ended_at=_min(60), maps=(_map(40, 10, 2),))

        self.assertEqual(_chapters(encounter), [(1, "map", 2, 2400)])


class SeriesChapterTests(TestCase):
    def test_a_finished_series_is_in_on_overlap(self) -> None:
        before = EncounterTiming(1, "A vs B", started_at=_min(-60), ended_at=_min(10))
        gone = EncounterTiming(2, "A vs C", started_at=_min(-60), ended_at=_min(-1))

        self.assertEqual(_chapters(before, gone), [(1, "series", None, 0)])

    def test_an_open_series_counts_only_when_it_started_on_air(self) -> None:
        on_air = EncounterTiming(1, "A vs B", started_at=_min(30), ended_at=None)
        earlier = EncounterTiming(2, "A vs C", started_at=_min(-10), ended_at=None)
        later = EncounterTiming(3, "A vs D", started_at=_min(181), ended_at=None)
        unstarted = EncounterTiming(4, "A vs E", started_at=None, ended_at=None)

        self.assertEqual(_chapters(on_air, earlier, later, unstarted), [(1, "series", None, 1800)])

    def test_chapters_sort_by_offset_then_encounter_then_position(self) -> None:
        series = EncounterTiming(9, "A vs B", started_at=_min(10), ended_at=_min(20))
        maps = EncounterTiming(3, "A vs C", None, None, maps=(_map(10, 1, 2), _map(10, 1, 1)))

        self.assertEqual(_chapters(series, maps), [(3, "map", 1, 600), (3, "map", 2, 600), (9, "series", None, 600)])


class EncounterRoutingTests(IsolatedAsyncioTestCase):
    async def test_a_mix_encounter_answers_an_empty_list_without_a_gate(self) -> None:
        gate = AsyncMock()
        with (
            patch.object(
                stream_chronology_reader._chronology, "encounter_owner", AsyncMock(return_value=EncounterOwnerRow(None))
            ),
            patch.object(reads, "ensure_tournament_viewable", gate),
        ):
            result = await reads.encounter_vods(object(), {"encounter_id": "5"})

        self.assertEqual(result.model_dump(), {"vods": []})
        gate.assert_not_awaited()

    async def test_an_unknown_encounter_is_404(self) -> None:
        with patch.object(stream_chronology_reader._chronology, "encounter_owner", AsyncMock(return_value=None)):
            with self.assertRaises(HTTPException) as caught:
                await reads.encounter_vods(object(), {"encounter_id": "5"})

        self.assertEqual(caught.exception.status_code, 404)

    async def test_a_hidden_tournament_is_rejected_before_any_vod_is_read(self) -> None:
        build = AsyncMock()
        with (
            patch.object(reads, "ensure_tournament_viewable", AsyncMock(side_effect=HTTPException(404, "hidden"))),
            patch.object(stream_chronology_reader, "build", build),
        ):
            with self.assertRaises(HTTPException):
                await reads.tournament_vods(object(), {"tournament_id": "7"})

        build.assert_not_awaited()
