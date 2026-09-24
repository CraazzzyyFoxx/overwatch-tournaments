"""Tests for per-captain encounter report submission in tournament-service."""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy import inspect as sa_inspect

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

captain_service = importlib.import_module("src.services.encounter.captain")
enums = importlib.import_module("shared.core.enums")


@contextmanager
def assert_http_status(test_case: IsolatedAsyncioTestCase, expected_status: int):
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - inspect status_code attribute
        status_code = getattr(exc, "status_code", None)
        test_case.assertEqual(status_code, expected_status)
        return
    test_case.fail(f"expected an exception with status_code {expected_status}")


def _mk_user(user_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(id=user_id)


def _mk_report(*, team_id: int, home: int, away: int, closeness: int | None, report_id: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        id=report_id,
        team_id=team_id,
        reporter_user_id=None,
        home_score=home,
        away_score=away,
        closeness=closeness,
        comment=None,
        custom_fields_json={},
        map_codes=[],
    )


def _mk_report_form(built_in: dict | None = None, custom: list | None = None) -> SimpleNamespace:
    """A stand-in for a persisted ``EncounterReportForm`` row."""
    return SimpleNamespace(
        built_in_fields_json=built_in or {},
        custom_fields_json=custom or [],
    )


def _mk_encounter(
    *,
    result_status=enums.EncounterResultStatus.NONE,
    captain_reports: list | None = None,
    home_captain_player_id: int = 100,
    away_captain_player_id: int = 200,
    best_of: int = 3,
) -> SimpleNamespace:
    home_team = SimpleNamespace(id=1, captain_id=home_captain_player_id)
    away_team = SimpleNamespace(id=2, captain_id=away_captain_player_id)
    return SimpleNamespace(
        id=10,
        format=enums.EncounterFormat.DUEL,
        tournament_id=1,
        home_team_id=home_team.id,
        away_team_id=away_team.id,
        home_team=home_team,
        away_team=away_team,
        stage_id=1,
        stage=SimpleNamespace(stage_type="round_robin"),
        result_status=result_status,
        status=enums.EncounterStatus.OPEN,
        best_of=best_of,
        home_score=0,
        away_score=0,
        closeness=None,
        confirmed_at=None,
        captain_reports=captain_reports if captain_reports is not None else [],
    )


def _mk_session(
    encounter: SimpleNamespace | None,
    captain_player_ids: list[int],
    *,
    settled_rows: list[tuple[int, int | None, int]] | None = None,
    report_form_row: SimpleNamespace | None = None,
    # Defaults to published so every pre-existing test (all written before
    # the bracket-preview gate existed) keeps exercising report logic
    # unchanged; only tests that care about the gate pass ``False``.
    stage_published: bool = True,
) -> SimpleNamespace:
    linked_player_id = captain_player_ids[0] if captain_player_ids else None
    execute_count = 0
    rows = settled_rows or []

    async def fake_execute(_query):
        nonlocal execute_count
        execute_count += 1

        # Every result answers unique().scalars().first() -- how the repositories
        # read a single row -- plus scalars().all() and all(), so any query shape
        # is safe regardless of call order: the encounter load, the linked-player
        # lookup, the report-form config load, delete(codes), the picked-pool
        # select, the challonge probe, and the bracket's EncounterLink fan-out.
        result_mock = Mock()
        scalars_mock = Mock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        # ``Result.unique()`` returns the same result, so a repository's
        # ``.unique().scalars()`` lands on the same scalars stub as a bare
        # ``.scalars()`` does.
        result_mock.unique.return_value = result_mock
        result_mock.all.return_value = list(rows)

        if execute_count == 1:  # encounter load
            row = encounter
        elif execute_count == 2:  # linked-player lookup (submit flow)
            row = SimpleNamespace(id=linked_player_id) if linked_player_id is not None else None
        elif execute_count == 3:  # report-form config (None => all defaults)
            row = report_form_row
        else:
            row = None
        scalars_mock.first.return_value = row
        return result_mock

    async def fake_get(model, _pk):
        if model.__name__ == "Stage":
            return SimpleNamespace(is_published=stage_published)
        raise AssertionError(f"unexpected get() model: {model}")

    added: list[object] = []

    async def fake_flush():
        # A real flush turns a pending report persistent, and from then on the
        # first touch of a collection it never loaded emits a lazy SELECT --
        # implicit IO from sync attribute access, i.e. MissingGreenlet under an
        # async session. That is how a team's FIRST report crashed in production
        # (captain.py attaching map codes after the flush), so the writer must
        # seed the collection before flushing. An AsyncMock session can never
        # emit that load, so the invariant is asserted here instead.
        for obj in added:
            if type(obj).__name__ == "EncounterCaptainReport" and "map_codes" in sa_inspect(obj).unloaded:
                raise AssertionError(
                    "flushed a new EncounterCaptainReport whose map_codes collection was never "
                    "loaded; the next touch of it lazy-loads (MissingGreenlet under asyncio)"
                )

    return SimpleNamespace(
        execute=AsyncMock(side_effect=fake_execute),
        get=AsyncMock(side_effect=fake_get),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        flush=AsyncMock(side_effect=fake_flush),
        add=lambda obj: added.append(obj),
        _added=added,
    )


def _audit_rows(session) -> list:
    """Result-audit rows appended during the call, in order."""
    return [obj for obj in session._added if type(obj).__name__ == "EncounterResultAudit"]


class CaptainReportValidation(IsolatedAsyncioTestCase):
    async def test_rejects_closeness_out_of_range(self) -> None:
        session = _mk_session(_mk_encounter(), [100])
        with assert_http_status(self, 422):
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=11
            )

    async def test_rejects_negative_score(self) -> None:
        session = _mk_session(_mk_encounter(), [100])
        with assert_http_status(self, 422):
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=-1, away_score=1, closeness=5
            )

    async def test_rejects_duplicate_map_index(self) -> None:
        session = _mk_session(_mk_encounter(), [100])
        with assert_http_status(self, 422):
            await captain_service.captain_service.submit_captain_report(
                session,
                _mk_user(),
                10,
                home_score=2,
                away_score=1,
                closeness=5,
                map_codes=[(1, "AAA"), (1, "BBB")],
            )

    async def test_non_captain_forbidden(self) -> None:
        session = _mk_session(_mk_encounter(), [999])
        with assert_http_status(self, 403):
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=5
            )

    async def test_confirmed_encounter_rejects_report(self) -> None:
        encounter = _mk_encounter(result_status=enums.EncounterResultStatus.CONFIRMED)
        session = _mk_session(encounter, [100])
        with assert_http_status(self, 400):
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=5
            )

    async def test_stage_not_published_rejects_report(self) -> None:
        """A bracket generated ahead of the stage's activation (organizer
        preview) must not be reportable until the stage goes live."""
        session = _mk_session(_mk_encounter(), [100], stage_published=False)
        with assert_http_status(self, 409):
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=5
            )


class CaptainReportFlow(IsolatedAsyncioTestCase):
    async def test_first_report_sets_pending_no_closeness(self) -> None:
        encounter = _mk_encounter()
        session = _mk_session(encounter, [100])  # home captain
        with patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()) as recalc:
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=7
            )
        recalc.assert_awaited_once_with(session, encounter.tournament_id)
        self.assertEqual(encounter.result_status, enums.EncounterResultStatus.PENDING_CONFIRMATION)
        self.assertIsNone(encounter.closeness)
        self.assertEqual(encounter.captain_reports[0].reporter_user_id, 100)
        # A first report decides nothing, so it leaves no result-audit row —
        # who reported is already on the report itself.
        self.assertEqual([], _audit_rows(session))
        self.assertEqual(len(encounter.captain_reports), 1)
        self.assertEqual(encounter.captain_reports[0].team_id, 1)
        session.commit.assert_awaited_once()

    async def test_second_matching_report_auto_confirms_with_avg_closeness(self) -> None:
        existing = _mk_report(team_id=1, home=2, away=1, closeness=8)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=[existing],
        )
        session = _mk_session(encounter, [200])  # away captain

        async def fake_finalize(*_args, **kwargs):
            encounter.status = enums.EncounterStatus.COMPLETED
            encounter.result_status = kwargs["result_status"]
            encounter.home_score = kwargs["home_score"]
            encounter.away_score = kwargs["away_score"]
            return SimpleNamespace(encounter=encounter, advanced_encounters=[])

        with (
            patch.object(
                captain_service.captain_service.finalize,
                "finalize_encounter_score",
                AsyncMock(side_effect=fake_finalize),
            ) as fin,
            patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()) as recalc,
            patch.object(captain_service.captain_service, "_enqueue_encounter_completed", AsyncMock()) as completed,
        ):
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=6
            )

        fin.assert_awaited_once()
        recalc.assert_awaited_once_with(session, encounter.tournament_id)
        completed.assert_awaited_once_with(session, encounter)
        self.assertEqual(encounter.result_status, enums.EncounterResultStatus.CONFIRMED)
        audit = _audit_rows(session)
        self.assertEqual(1, len(audit))
        self.assertEqual(enums.EncounterResultAuditAction.AUTO_CONFIRM, audit[0].action)
        self.assertEqual(200, audit[0].actor_user_id)
        # avg(8, 6) / 10 == 0.7
        self.assertAlmostEqual(encounter.closeness, 0.7)
        session.commit.assert_awaited_once()

    async def test_second_mismatching_report_disputes(self) -> None:
        existing = _mk_report(team_id=1, home=2, away=1, closeness=8)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=[existing],
        )
        session = _mk_session(encounter, [200])  # away captain
        with (
            patch.object(captain_service.captain_service.finalize, "finalize_encounter_score", AsyncMock()) as fin,
            patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()) as recalc,
        ):
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=0, away_score=2, closeness=4
            )
        fin.assert_not_awaited()
        recalc.assert_awaited_once_with(session, encounter.tournament_id)
        self.assertEqual(encounter.result_status, enums.EncounterResultStatus.DISPUTED)
        self.assertIsNone(encounter.closeness)

    async def test_upsert_replaces_own_report(self) -> None:
        existing = _mk_report(team_id=1, home=1, away=2, closeness=3)
        existing.map_codes = [SimpleNamespace(map_index=1, code="OLD", map_id=None)]
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=[existing],
        )
        session = _mk_session(encounter, [100])  # home captain re-submits
        with patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()):
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=0, closeness=9
            )
        self.assertEqual(len(encounter.captain_reports), 1)
        self.assertEqual(existing.home_score, 2)
        self.assertEqual(existing.away_score, 0)
        self.assertEqual(existing.closeness, 9)
        self.assertEqual(existing.map_codes, [])
        self.assertEqual(encounter.result_status, enums.EncounterResultStatus.PENDING_CONFIRMATION)

    async def test_map_codes_resolve_map_id_from_pool_softly(self) -> None:
        encounter = _mk_encounter()
        # Settled pool rows as the query selects them: (order, action_index,
        # map_id). `order` is deliberately the 0-based/round-spaced shape the
        # engine writes, and `action_index` is what decides play order — so map
        # 66 is the FIRST map of the series and map 55 the second.
        session = _mk_session(encounter, [100], settled_rows=[(1000, 5, 55), (0, 3, 66)])
        with patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()):
            await captain_service.captain_service.submit_captain_report(
                session,
                _mk_user(),
                10,
                home_score=2,
                away_score=1,
                closeness=7,
                map_codes=[(1, "AAA"), (2, "BBB"), (3, "CCC"), (4, "  ")],
            )
        report = encounter.captain_reports[0]
        by_index = {mc.map_index: mc for mc in report.map_codes}
        # blank code (index 4) is skipped
        self.assertEqual(set(by_index), {1, 2, 3})
        self.assertEqual(by_index[1].map_id, 66)
        self.assertEqual(by_index[2].map_id, 55)
        self.assertIsNone(by_index[3].map_id)  # soft: index beyond the settled maps
        self.assertEqual(by_index[1].code, "AAA")

    async def test_a_first_report_carries_its_codes_without_reading_them(self) -> None:
        """A team's first report is a brand-new row, so nothing eager-loaded its
        codes: ``submit_captain_report`` has to seed the collection itself before
        it flushes, or attaching the codes lazy-loads and raises MissingGreenlet
        (Sentry, captain.py, 2026-07-24 .. 2026-08-15). ``_mk_session``'s flush
        enforces the seeding; this pins the codes still landing on the report."""
        encounter = _mk_encounter()
        session = _mk_session(encounter, [100])
        with patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()):
            await captain_service.captain_service.submit_captain_report(
                session,
                _mk_user(),
                10,
                home_score=2,
                away_score=0,
                closeness=7,
                map_codes=[(1, "AAA"), (2, "BBB")],
            )
        report = encounter.captain_reports[0]
        self.assertNotIn("map_codes", sa_inspect(report).unloaded)
        self.assertEqual(["AAA", "BBB"], [mc.code for mc in report.map_codes])


class ConfigurableReportFields(IsolatedAsyncioTestCase):
    """The tournament's report-form config decides what a report carries."""

    async def test_persists_comment_and_custom_fields(self) -> None:
        encounter = _mk_encounter()
        session = _mk_session(
            encounter,
            [100],
            report_form_row=_mk_report_form(
                custom=[{"key": "vod", "label": "VOD link", "type": "text", "required": True}]
            ),
        )
        with patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()):
            await captain_service.captain_service.submit_captain_report(
                session,
                _mk_user(),
                10,
                home_score=2,
                away_score=1,
                closeness=7,
                comment="  close series  ",
                custom_fields={"vod": "https://example.test/vod", "gone": "dropped"},
            )
        report = encounter.captain_reports[0]
        self.assertEqual("close series", report.comment)
        self.assertEqual({"vod": "https://example.test/vod"}, report.custom_fields_json)

    async def test_a_required_custom_field_blocks_the_submit(self) -> None:
        session = _mk_session(
            _mk_encounter(),
            [100],
            report_form_row=_mk_report_form(
                custom=[{"key": "vod", "label": "VOD link", "type": "text", "required": True}]
            ),
        )
        with assert_http_status(self, 422):
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=7
            )

    async def test_disabled_closeness_leaves_the_encounter_unrated(self) -> None:
        """With the field off, both reports store NULL and there is no average."""
        existing = _mk_report(team_id=1, home=2, away=1, closeness=None)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=[existing],
        )
        session = _mk_session(
            encounter,
            [200],  # away captain
            report_form_row=_mk_report_form(built_in={"closeness": {"enabled": False, "required": False}}),
        )
        with (
            patch.object(captain_service.captain_service.finalize, "finalize_encounter_score", AsyncMock()),
            patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()),
            patch.object(captain_service.captain_service, "_enqueue_encounter_completed", AsyncMock()),
        ):
            await captain_service.captain_service.submit_captain_report(
                session, _mk_user(), 10, home_score=2, away_score=1, closeness=9
            )
        # Submitted 9, but the field is disabled: the value is dropped, not rejected.
        self.assertIsNone(encounter.captain_reports[1].closeness)
        self.assertIsNone(encounter.closeness)

    async def test_required_map_codes_block_a_missing_code(self) -> None:
        session = _mk_session(
            _mk_encounter(),
            [100],
            report_form_row=_mk_report_form(built_in={"map_codes": {"enabled": True, "required": True}}),
        )
        with assert_http_status(self, 422):
            # 2-1 played three maps; only one code supplied.
            await captain_service.captain_service.submit_captain_report(
                session,
                _mk_user(),
                10,
                home_score=2,
                away_score=1,
                closeness=7,
                map_codes=[(1, "AAA")],
            )


class AdminSetResult(IsolatedAsyncioTestCase):
    ADMIN = 900

    async def _set(self, encounter, **kwargs):
        """Run set_encounter_result with finalize mocked to capture its score."""
        session = _mk_session(encounter, [])
        captured: dict = {}

        async def fake_finalize(*_args, **kw):
            captured.update(kw)
            encounter.status = enums.EncounterStatus.COMPLETED
            encounter.result_status = kw["result_status"]
            encounter.home_score = kw["home_score"]
            encounter.away_score = kw["away_score"]
            return SimpleNamespace(encounter=encounter, advanced_encounters=[])

        with (
            patch.object(
                captain_service.captain_service.finalize,
                "finalize_encounter_score",
                AsyncMock(side_effect=fake_finalize),
            ),
            patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()),
            patch.object(captain_service.captain_service, "_enqueue_encounter_completed", AsyncMock()),
            patch.object(captain_service, "resolve_encounter_challonge", AsyncMock(return_value={})),
        ):
            await captain_service.captain_service.set_encounter_result(session, 10, actor_user_id=self.ADMIN, **kwargs)
        return captured, session

    async def test_pending_single_report_adopts_reported_score(self) -> None:
        # The encounter score stays 0-0 until an auto-confirm, so confirming a
        # pending single-report encounter must adopt the captain's reported
        # score instead of finalizing a bogus 0-0 draw.
        report = _mk_report(team_id=1, home=3, away=0, closeness=7)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=[report],
        )
        captured, session = await self._set(encounter)
        self.assertEqual((captured["home_score"], captured["away_score"]), (3, 0))
        self.assertEqual(encounter.result_status, enums.EncounterResultStatus.CONFIRMED)
        self.assertAlmostEqual(encounter.closeness, 0.7)

        audit = _audit_rows(session)
        self.assertEqual(1, len(audit))
        self.assertEqual(enums.EncounterResultAuditAction.CONFIRM, audit[0].action)
        self.assertEqual(self.ADMIN, audit[0].actor_user_id)
        self.assertEqual((0, 0), (audit[0].home_score_before, audit[0].away_score_before))
        self.assertEqual((3, 0), (audit[0].home_score_after, audit[0].away_score_after))

    async def test_averages_only_the_reports_that_carry_a_rating(self) -> None:
        """A disabled match-quality field leaves NULL ratings the average must skip."""
        rated = _mk_report(team_id=1, home=2, away=0, closeness=8, report_id=1)
        unrated = _mk_report(team_id=2, home=2, away=0, closeness=None, report_id=2)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.DISPUTED,
            captain_reports=[rated, unrated],
        )
        await self._set(encounter)
        self.assertAlmostEqual(encounter.closeness, 0.8)

    async def test_all_unrated_reports_leave_the_encounter_unrated(self) -> None:
        reports = [
            _mk_report(team_id=1, home=2, away=0, closeness=None, report_id=1),
            _mk_report(team_id=2, home=2, away=0, closeness=None, report_id=2),
        ]
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=reports,
        )
        await self._set(encounter)
        self.assertIsNone(encounter.closeness)

    async def test_explicit_score_wins_over_every_report(self) -> None:
        home = _mk_report(team_id=1, home=2, away=0, closeness=5, report_id=1)
        away = _mk_report(team_id=2, home=0, away=3, closeness=9, report_id=2)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.DISPUTED,
            captain_reports=[home, away],
        )
        captured, _ = await self._set(encounter, home_score=2, away_score=1)
        self.assertEqual((captured["home_score"], captured["away_score"]), (2, 1))

    async def test_adopting_one_side_takes_that_report_verbatim(self) -> None:
        """The dispute-resolution path: "team 2 was right" is one call, not an
        edit followed by a confirm."""
        home = _mk_report(team_id=1, home=2, away=0, closeness=5, report_id=1)
        away = _mk_report(team_id=2, home=0, away=3, closeness=9, report_id=2)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.DISPUTED,
            captain_reports=[home, away],
        )
        captured, session = await self._set(encounter, adopt_report_team_id=2)
        self.assertEqual((captured["home_score"], captured["away_score"]), (0, 3))
        self.assertEqual(2, _audit_rows(session)[0].adopted_team_id)

    async def test_keeps_an_already_edited_encounter_score(self) -> None:
        home = _mk_report(team_id=1, home=2, away=0, closeness=5, report_id=1)
        away = _mk_report(team_id=2, home=0, away=3, closeness=9, report_id=2)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.DISPUTED,
            captain_reports=[home, away],
        )
        encounter.home_score = 2
        encounter.away_score = 1
        captured, _ = await self._set(encounter)
        self.assertEqual((captured["home_score"], captured["away_score"]), (2, 1))

    async def test_explicit_closeness_overrides_the_report_average(self) -> None:
        report = _mk_report(team_id=1, home=3, away=0, closeness=2)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=[report],
        )
        await self._set(encounter, closeness=9)
        self.assertAlmostEqual(encounter.closeness, 0.9)

    async def test_rejects_an_unresolvable_score(self) -> None:
        """No explicit score, no report to adopt and a still-0-0 encounter: a
        bogus draw would also 400 on elimination stages."""
        encounter = _mk_encounter(result_status=enums.EncounterResultStatus.NONE)
        session = _mk_session(encounter, [])
        with assert_http_status(self, 422):
            await captain_service.captain_service.set_encounter_result(session, 10, actor_user_id=self.ADMIN)

    async def test_rejects_a_half_specified_score(self) -> None:
        encounter = _mk_encounter(result_status=enums.EncounterResultStatus.NONE)
        session = _mk_session(encounter, [])
        with assert_http_status(self, 422):
            await captain_service.captain_service.set_encounter_result(
                session, 10, actor_user_id=self.ADMIN, home_score=2
            )

    async def test_rejects_adopting_a_team_that_never_reported(self) -> None:
        report = _mk_report(team_id=1, home=3, away=0, closeness=7)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.PENDING_CONFIRMATION,
            captain_reports=[report],
        )
        session = _mk_session(encounter, [])
        with assert_http_status(self, 422):
            await captain_service.captain_service.set_encounter_result(
                session, 10, actor_user_id=self.ADMIN, adopt_report_team_id=2
            )

    async def test_rejects_reconfirming_a_confirmed_result(self) -> None:
        """Unlike the old confirm, ``none`` is now a legal starting point — the
        only refusal is a result that is already confirmed."""
        encounter = _mk_encounter(result_status=enums.EncounterResultStatus.CONFIRMED)
        session = _mk_session(encounter, [])
        with assert_http_status(self, 409):
            await captain_service.captain_service.set_encounter_result(
                session, 10, actor_user_id=self.ADMIN, home_score=2, away_score=0
            )


class AdminReopenResult(IsolatedAsyncioTestCase):
    ADMIN = 900

    async def test_reopen_clears_the_result_and_keeps_the_reports(self) -> None:
        report = _mk_report(team_id=1, home=3, away=0, closeness=7)
        encounter = _mk_encounter(
            result_status=enums.EncounterResultStatus.CONFIRMED,
            captain_reports=[report],
        )
        encounter.status = enums.EncounterStatus.COMPLETED
        encounter.home_score = 3
        encounter.closeness = 0.7
        session = _mk_session(encounter, [])

        with patch.object(captain_service.captain_service, "_enqueue_tournament_recalculation", AsyncMock()) as recalc:
            await captain_service.captain_service.reopen_encounter_result(session, 10, actor_user_id=self.ADMIN)

        self.assertEqual(enums.EncounterResultStatus.NONE, encounter.result_status)
        self.assertEqual(enums.EncounterStatus.OPEN, encounter.status)
        self.assertEqual((0, 0), (encounter.home_score, encounter.away_score))
        self.assertIsNone(encounter.closeness)
        self.assertIsNone(encounter.confirmed_at)
        # The captains' submissions are the evidence — a correction is not a purge.
        self.assertEqual([report], encounter.captain_reports)
        recalc.assert_awaited_once_with(session, encounter.tournament_id)

        audit = _audit_rows(session)
        self.assertEqual(1, len(audit))
        self.assertEqual(enums.EncounterResultAuditAction.REOPEN, audit[0].action)
        self.assertEqual(self.ADMIN, audit[0].actor_user_id)
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, audit[0].from_result_status)

    async def test_rejects_reopening_an_untouched_encounter(self) -> None:
        encounter = _mk_encounter(result_status=enums.EncounterResultStatus.NONE)
        session = _mk_session(encounter, [])
        with assert_http_status(self, 409):
            await captain_service.captain_service.reopen_encounter_result(session, 10, actor_user_id=self.ADMIN)


class ResolveOptionalViewerSide(IsolatedAsyncioTestCase):
    """Regression for OWT-TOURNAMENTS-24C.

    ``resolve_optional_viewer_side`` imported the captain *module* as
    ``captain_service`` and called ``resolve_captain_side`` on it. The
    method lives on the ``CaptainService`` instance.
    """

    async def test_uses_the_service_instance(self) -> None:
        from src.schemas.captain import resolve_optional_viewer_side

        session, user, encounter = object(), object(), object()
        with patch(
            "src.schemas.captain.captain_mod.captain_service.resolve_captain_side",
            new=AsyncMock(return_value="home"),
        ) as resolve:
            side = await resolve_optional_viewer_side(session, user, encounter)

        self.assertEqual("home", side)
        resolve.assert_awaited_once_with(session, user, encounter)

    async def test_non_captain_is_none(self) -> None:
        from src.schemas.captain import resolve_optional_viewer_side

        forbidden = captain_service.HTTPException(status_code=403, detail="nope")
        with patch(
            "src.schemas.captain.captain_mod.captain_service.resolve_captain_side",
            new=AsyncMock(side_effect=forbidden),
        ):
            side = await resolve_optional_viewer_side(object(), object(), object())

        self.assertIsNone(side)
