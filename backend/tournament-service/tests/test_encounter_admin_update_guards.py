"""Completion is not a field edit.

``COMPLETED`` used to be reachable through the plain admin encounter edit, which
wrote ``status`` without ``result_status`` — the route to a ``completed`` +
``disputed`` encounter that no endpoint could repair. These tests pin the new
boundary: the field editor refuses the transition and names the endpoint that
owns it, and it no longer runs advancement or emits a completion event as a side
effect of unrelated edits.
"""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

enc_service = importlib.import_module("src.services.admin.encounter")
schemas = importlib.import_module("src.schemas")
enums = importlib.import_module("shared.core.enums")


@contextmanager
def assert_http_status(test_case: IsolatedAsyncioTestCase, expected_status: int):
    try:
        yield
    except Exception as exc:  # noqa: BLE001 - inspect status_code attribute
        test_case.assertEqual(getattr(exc, "status_code", None), expected_status)
        test_case.assertIn("result", str(getattr(exc, "detail", "")))
        return
    test_case.fail(f"expected an exception with status_code {expected_status}")


def _encounter() -> SimpleNamespace:
    return SimpleNamespace(
        id=10,
        tournament_id=1,
        stage_id=5,
        stage_item_id=6,
        home_team_id=1,
        away_team_id=2,
        home_score=2,
        away_score=0,
        status=enums.EncounterStatus.COMPLETED,
        result_status=enums.EncounterResultStatus.CONFIRMED,
        name="a vs b",
    )


def _session(encounter: SimpleNamespace) -> SimpleNamespace:
    async def fake_execute(_query):
        result = Mock()
        result.scalar_one_or_none.return_value = encounter
        result.unique.return_value = result
        scalars = Mock()
        scalars.all.return_value = []
        scalars.first.return_value = encounter
        result.scalars.return_value = scalars
        result.all.return_value = []
        return result

    return SimpleNamespace(
        execute=AsyncMock(side_effect=fake_execute),
        commit=AsyncMock(),
        refresh=AsyncMock(),
        flush=AsyncMock(),
        add=lambda _obj: None,
    )


class UpdateEncounterGuards(IsolatedAsyncioTestCase):
    async def test_rejects_completing_through_the_field_editor(self) -> None:
        encounter = _encounter()
        encounter.status = enums.EncounterStatus.OPEN
        with assert_http_status(self, 409):
            await enc_service.encounter_service.update_encounter(
                _session(encounter),
                10,
                schemas.EncounterUpdate(status="completed"),
            )

    async def test_rejects_creating_an_already_completed_encounter(self) -> None:
        """Creating with status=completed skipped finalize entirely, so the
        bracket never advanced behind it."""
        with assert_http_status(self, 409):
            await enc_service.encounter_service.create_encounter(
                _session(_encounter()),
                schemas.EncounterCreate(
                    name="a vs b",
                    tournament_id=1,
                    home_team_id=1,
                    away_team_id=2,
                    round=1,
                    status="completed",
                ),
            )

    async def test_editing_a_completed_encounter_does_not_re_advance(self) -> None:
        """The old guard tested the post-write state, not a transition, so every
        unrelated edit of a completed encounter re-ran advancement and re-emitted
        EncounterCompletedEvent. The field editor no longer imports finalize or
        the completion event at all — completion has exactly one writer now."""
        self.assertFalse(hasattr(enc_service, "finalize_encounter_score"))
        self.assertFalse(hasattr(enc_service, "enqueue_encounter_completed"))
        self.assertFalse(hasattr(enc_service.encounter_service, "finalize_encounter_score"))
        self.assertFalse(hasattr(enc_service.encounter_service, "enqueue_encounter_completed"))

        encounter = _encounter()
        session = _session(encounter)

        with (
            patch.object(enc_service, "enqueue_tournament_recalculation", AsyncMock()) as recalc,
            patch.object(enc_service.encounter_service, "_resolve_stage_refs", AsyncMock(return_value=(5, 6))),
        ):
            await enc_service.encounter_service.update_encounter(session, 10, schemas.EncounterUpdate(name="renamed"))

        self.assertEqual("renamed", encounter.name)
        recalc.assert_awaited_once()


class BulkEndpointIsGone(IsolatedAsyncioTestCase):
    async def test_bulk_update_is_removed(self) -> None:
        """Zero frontend callers, and a second unguarded status writer is exactly
        what the single-mechanism rule forbids."""
        self.assertFalse(hasattr(enc_service, "bulk_update_encounters"))
        self.assertFalse(hasattr(schemas, "BulkEncounterUpdate"))


class MatchLogNameIsNotEditable(IsolatedAsyncioTestCase):
    def test_log_name_left_matchupdate(self) -> None:
        """An unvalidated log_name edit detached a match from every log record.
        Since mtchlog001 provenance is a foreign key, so there is nothing left to
        gain by allowing the string to be rewritten."""
        self.assertNotIn("log_name", schemas.MatchUpdate.model_fields)

    def test_the_other_match_fields_are_still_editable(self) -> None:
        fields = set(schemas.MatchUpdate.model_fields)
        assert {"home_score", "away_score", "map_id", "code", "time"} <= fields
