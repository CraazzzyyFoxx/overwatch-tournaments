"""The chapter rules of a POV VOD, and the routing of the two chronology reads.

The rules are pure (``src.domain.chronology``), so every case is a few datetimes. What each guards:

- a map overlapping the broadcast is in, one outside it is out, and a map already running when the stream began
  links to 0:00 rather than to a negative offset;
- the tournament's stream delay shifts the window AND the offsets — a delayed stream shows a match late;
- a map's start: the log's own time, else its file name on the host clock with the UTC offset the server-side
  events agree with, else the end of its round's bans; the decoder's upload-time fallback is never a start;
- a series chapter only stands in when no map is timed, starting at the pre-game room before the organizer's
  start, ending at the confirmation when the organizer set no end; an open one counts only if it started on air;
- the encounter read answers a mix's encounter with nothing and an unknown one with 404, before any gate or read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.repository.stream_session import EncounterOwnerRow  # noqa: E402
from src.domain.chronology import EncounterTiming, LoggedMap, PlayedGame, chapters  # noqa: E402
from src.rpc import reads  # noqa: E402
from src.services.chronology import stream_chronology_reader  # noqa: E402

T0 = datetime(2026, 10, 25, 17, 0, tzinfo=UTC)


def _min(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def _map(minute: float, duration_min: float | None, position: int) -> LoggedMap:
    return LoggedMap(
        position=position,
        map_name=f"map{position}",
        played_at=_min(minute),
        duration_s=None if duration_min is None else duration_min * 60,
        uploaded_at=None,
        filename=None,
    )


def _log(clock: str, *, duration_min: float = 10, position: int | None = 1, uploaded: float = 300) -> LoggedMap:
    """A log whose time is the decoder's fallback: ``played_at`` IS the upload time."""
    return LoggedMap(
        position=position,
        map_name=f"map{position}",
        played_at=_min(uploaded),
        duration_s=duration_min * 60,
        uploaded_at=_min(uploaded),
        filename=f"Log-{clock}.txt",
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


class TimingSourceTests(TestCase):
    def test_the_upload_time_fallback_is_never_a_start(self) -> None:
        encounter = EncounterTiming(1, "A vs B", None, None, maps=(_log("garbage", uploaded=30),))

        self.assertEqual(_chapters(encounter), [])

    def test_a_log_time_of_its_own_wins_over_the_file_name(self) -> None:
        log = LoggedMap(1, "map1", _min(25), 600, _min(300), "Log-2026-10-25-22-20-00.txt")
        encounter = EncounterTiming(1, "A vs B", None, None, maps=(log,), round_ends={1: _min(19)})

        self.assertEqual(_chapters(encounter), [(1, "map", 1, 1500)])

    def test_the_file_name_takes_the_host_offset_nearest_the_end_of_its_rounds_bans(self) -> None:
        # A UTC+5 host's 22:20 is 17:20 UTC, a minute after the room let round 1 start.
        encounter = EncounterTiming(
            1, "A vs B", None, None, maps=(_log("2026-10-25-22-20-00"),), round_ends={1: _min(19)}
        )

        self.assertEqual(_chapters(encounter), [(1, "map", 1, 1200)])

    def test_without_a_round_the_earliest_later_event_decides_the_offset(self) -> None:
        # A UTC+3 host's 20:30, ten minutes long. Against the upload alone, a batch an hour later, UTC+2 (18:30 UTC)
        # would fit too; the map's own result, reported three minutes after its end, only fits UTC+3.
        encounter = EncounterTiming(
            1,
            "A vs B",
            None,
            None,
            confirmed_at=_min(90),
            maps=(_log("2026-10-25-20-30-00", uploaded=100),),
            games=(PlayedGame(1, "map1", _min(43)),),
        )

        self.assertEqual(_chapters(encounter), [(1, "map", 1, 1800)])

    def test_an_untimed_map_starts_where_its_rounds_bans_ended_and_ends_at_its_result(self) -> None:
        # Map 1 was running when the stream began (bans over at -5 min, result at +15): it is in, at 0:00.
        encounter = EncounterTiming(
            1,
            "A vs B",
            None,
            None,
            games=(PlayedGame(1, "Ilios", _min(15)), PlayedGame(2, "Busan", None), PlayedGame(3, "Oasis", None)),
            round_ends={1: _min(-5), 2: _min(20)},
        )

        found = chapters([encounter], started_at=_min(0), last_seen_at=_min(180), delay_s=0)

        self.assertEqual(
            [(c.map_position, c.map_name, c.offset_s) for c in found], [(1, "Ilios", 0), (2, "Busan", 1200)]
        )

    def test_the_series_starts_at_the_pre_game_room_and_ends_at_the_confirmation(self) -> None:
        room = EncounterTiming(1, "A vs B", started_at=_min(5), ended_at=None, room_opened_at=_min(10))
        ready = EncounterTiming(2, "A vs C", started_at=None, ended_at=None, last_ready_at=_min(20))
        # Opened before the stream and confirmed on it: in, at 0:00 — without the confirmation it would be out.
        confirmed = EncounterTiming(3, "A vs D", None, None, confirmed_at=_min(5), room_opened_at=_min(-30))

        self.assertEqual(
            _chapters(room, ready, confirmed),
            [(3, "series", None, 0), (1, "series", None, 600), (2, "series", None, 1200)],
        )


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
