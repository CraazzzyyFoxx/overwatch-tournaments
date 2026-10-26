"""Completion is not a field edit.

``COMPLETED`` used to be reachable through the plain admin encounter edit, which
wrote ``status`` without ``result_status`` — the route to a ``completed`` +
``disputed`` encounter that no endpoint could repair. These tests pin the new
boundary: the field editor refuses the transition and names the endpoint that
owns it, and it no longer runs advancement or emits a completion event as a side
effect of unrelated edits.

Leaving ``COMPLETED`` is the same boundary from the other side: a bare ``status``
write left ``result_status='confirmed'`` next to a non-COMPLETED status, and the
row died on ``ck_encounter_confirmed_completed`` -- an IntegrityError in
place of a message naming the reopen endpoint, which is the only writer that also
clears the score and unwinds the bracket.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


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
        slot_count=2,
        scoring_preset="wins",
        tournament_id=1,
        scheduled_at=None,
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
        # The bracket coordinate the encounter sits at (``tournament.bracket_encounter``).
        get=AsyncMock(return_value=SimpleNamespace(stage_id=5, stage_item_id=6, round=1)),
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
        # A rename moves nothing standings are computed from.
        recalc.assert_not_awaited()

    async def test_rejects_reopening_through_the_field_editor(self) -> None:
        """Flipping a completed encounter back to ``open`` here wrote ``status``
        alone, leaving ``result_status='confirmed'`` for the check constraint to
        reject -- the edit died on an IntegrityError mid-transaction."""
        with assert_http_status(self, 409):
            await enc_service.encounter_service.update_encounter(
                _session(_encounter()),
                10,
                schemas.EncounterUpdate(status="open"),
            )

    async def test_the_field_editor_carries_no_seat_and_no_standing(self) -> None:
        """A confirmed standing belongs to the line-up that played it. Re-seating
        goes through the slot swap (refused on a settled encounter, see
        ``test_admin_encounter_swap_slot``) and a standing through the result
        writer -- the editor has no field that could write either."""
        fields = set(schemas.EncounterUpdate.model_fields)
        self.assertTrue({"teams", "score", "placement", "result_status", "slot_count"}.isdisjoint(fields))

    async def test_repeating_the_current_status_is_not_a_transition(self) -> None:
        """The admin form posts every field, so renaming a completed encounter
        arrives carrying ``status=completed``. Refusing that edit is what pushed
        admins into flipping the status by hand to get their change through."""
        encounter = _encounter()
        session = _session(encounter)

        with (
            patch.object(enc_service, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(enc_service.encounter_service, "_resolve_stage_refs", AsyncMock(return_value=(5, 6))),
            # ``status`` in the payload marks this a result correction; its
            # downstream-qualification guard queries a DB this fake has not.
            patch.object(enc_service.AdminEncounterService, "_assert_source_correction_allowed", AsyncMock()),
        ):
            await enc_service.encounter_service.update_encounter(
                session,
                10,
                schemas.EncounterUpdate(name="renamed", status="completed"),
            )

        self.assertEqual("renamed", encounter.name)
        self.assertEqual(enums.EncounterStatus.COMPLETED, encounter.status)


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

    def test_observed_scores_duration_and_bound_map_remain_editable(self) -> None:
        body = schemas.MatchUpdate(
            map_id=10,
            duration_s=120.5,
            team_facts=[
                schemas.MatchTeamFactIn(encounter_team_id=1, stat_code="score", value=3),
                schemas.MatchTeamFactIn(encounter_team_id=2, stat_code="score", value=2),
            ],
        )
        assert body.model_dump(exclude_unset=True) == {
            "map_id": 10,
            "duration_s": 120.5,
            "team_facts": [
                {"encounter_team_id": 1, "stat_code": "score", "value": 3.0},
                {"encounter_team_id": 2, "stat_code": "score", "value": 2.0},
            ],
        }
        # A participant is addressed once, and only the observed score is editable.
        with self.assertRaises(ValueError):
            schemas.MatchUpdate(
                team_facts=[
                    schemas.MatchTeamFactIn(encounter_team_id=1, stat_code="score", value=3),
                    schemas.MatchTeamFactIn(encounter_team_id=1, stat_code="score", value=4),
                ]
            )
        with self.assertRaises(ValueError):
            schemas.MatchTeamFactIn(encounter_team_id=1, stat_code="hero_damage_dealt", value=3)
