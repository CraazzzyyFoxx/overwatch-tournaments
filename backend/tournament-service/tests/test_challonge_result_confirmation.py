"""Challonge import is a confirmation, not a status poke.

Two defects are pinned here. The import used to write ``status`` without
``result_status``, so an imported result was invisible to the standings filter
that requires CONFIRMED, and it never emitted EncounterCompletedEvent — the same
result entered by an admin triggered achievement/MVP recalculation, an imported
one silently did not. Its conflict guard also consulted only ``was_completed``,
so a remote score would overwrite a live dispute and destroy the captains'
evidence.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

sync = importlib.import_module("src.services.challonge.sync")
enums = importlib.import_module("shared.core.enums")


def _encounter(*, status, result_status, home=0, away=0) -> SimpleNamespace:
    return SimpleNamespace(
        id=10,
        tournament_id=1,
        stage_id=None,
        stage_item_id=None,
        home_team_id=1,
        away_team_id=2,
        home_score=home,
        away_score=away,
        round=1,
        name="a vs b",
        status=status,
        result_status=result_status,
        closeness=None,
        confirmed_at=None,
    )


class AdvanceCompletedMatches(IsolatedAsyncioTestCase):
    """``_advance_completed_challonge_matches`` re-fires advancement for every
    complete match on every import, so it must be idempotent in the audit too."""

    async def _run(self, encounter):
        added: list = []
        session = SimpleNamespace(add=added.append)
        lookup = SimpleNamespace(get=lambda _s, _m: encounter)
        matches = [(SimpleNamespace(), SimpleNamespace(id=1, state="complete"))]
        captured: dict = {}

        async def fake_finalize(*_a, **kw):
            captured.update(kw)
            if kw.get("result_status") is not None:
                encounter.result_status = kw["result_status"]
            encounter.status = enums.EncounterStatus.COMPLETED
            return SimpleNamespace(encounter=encounter, advanced_encounters=[])

        with patch.object(sync.finalize_service, "finalize_encounter_score", AsyncMock(side_effect=fake_finalize)):
            await sync.sync_service._advance_completed_challonge_matches(session, matches, match_lookup=lookup)
        return captured, added

    async def test_confirms_an_unconfirmed_complete_match(self) -> None:
        encounter = _encounter(
            status=enums.EncounterStatus.COMPLETED,
            result_status=enums.EncounterResultStatus.NONE,
            home=2,
        )
        captured, added = await self._run(encounter)

        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, captured["result_status"])
        self.assertIsNotNone(captured["confirmed_at"])
        audit = [o for o in added if type(o).__name__ == "EncounterResultAudit"]
        self.assertEqual(1, len(audit))
        self.assertEqual(enums.EncounterResultAuditAction.IMPORT, audit[0].action)
        # An external system decided this — that NULL actor is what tells it
        # apart from an admin resolution in the trail.
        self.assertIsNone(audit[0].actor_user_id)

    async def test_leaves_an_already_confirmed_match_alone(self) -> None:
        encounter = _encounter(
            status=enums.EncounterStatus.COMPLETED,
            result_status=enums.EncounterResultStatus.CONFIRMED,
            home=2,
        )
        captured, added = await self._run(encounter)

        # Advancement still re-fires (idempotent), but nothing is re-stamped…
        self.assertIsNone(captured["result_status"])
        self.assertIsNone(captured["confirmed_at"])
        # …and the audit does not grow on every import run.
        self.assertEqual([], [o for o in added if type(o).__name__ == "EncounterResultAudit"])


class ConflictGuardProtectsLocalDecisions(IsolatedAsyncioTestCase):
    """The guard keys on result_status, not just status."""

    def test_a_decision_in_progress_outranks_the_remote_result(self) -> None:
        for result_status in (
            enums.EncounterResultStatus.CONFIRMED,
            enums.EncounterResultStatus.DISPUTED,
            enums.EncounterResultStatus.PENDING_CONFIRMATION,
        ):
            with self.subTest(result_status=result_status):
                encounter = _encounter(status=enums.EncounterStatus.OPEN, result_status=result_status)
                self.assertTrue(sync._has_local_decision(encounter))

    def test_an_untouched_encounter_is_not_protected(self) -> None:
        """Otherwise the importer could never fill in a fresh bracket."""
        encounter = _encounter(status=enums.EncounterStatus.OPEN, result_status=enums.EncounterResultStatus.NONE)
        self.assertFalse(sync._has_local_decision(encounter))

    def test_completed_without_a_result_status_is_still_protected(self) -> None:
        """Legacy rows completed before the state machine existed."""
        encounter = _encounter(status=enums.EncounterStatus.COMPLETED, result_status=enums.EncounterResultStatus.NONE)
        self.assertTrue(sync._has_local_decision(encounter))


class CreatingAnAlreadyCompleteMatch(IsolatedAsyncioTestCase):
    """A match can already be Challonge-``complete`` the first time the
    importer sees it (importing a finished bracket). The row must be born
    self-consistent: ``ck_encounter_result_status_matches_status`` forbids
    ``status=COMPLETED`` with ``result_status`` still ``none``, so creation
    must route through the same finalize+audit path as a live completion
    rather than writing ``status`` alone."""

    def _match(self, *, state: str) -> object:
        return sync.schemas.ChallongeMatch(
            id=1,
            started_at=None,
            created_at=sync.datetime.now(sync.UTC),
            updated_at=None,
            player1_id=None,
            player2_id=None,
            round=1,
            identifier="A1",
            state=state,
            scores_csv="0-2",
            tournament_id=1,
            group_id=None,
        )

    async def _upsert(self, *, state: str):
        tournament = SimpleNamespace(id=1)
        source = sync._ImportSource(challonge_id=100, stage=SimpleNamespace())
        match_lookup = sync._MatchLookup(by_source_key={}, by_challonge_id={}, mapped_keys=set(), unlinked_by_slot={})
        team_lookup = sync._TeamLookup(by_source_key={}, by_key={}, teams_by_id={})

        created: list = []

        async def fake_create(_session, encounter):
            encounter.id = 1
            created.append(encounter)
            return encounter

        audits: list = []

        with (
            patch.object(
                sync.sync_service.structure,
                "_resolve_stage_refs_for_match",
                AsyncMock(return_value=sync.StageRefs(stage_id=None, stage_item_id=None)),
            ),
            patch.object(sync.sync_service.mapping, "_ensure_match_mapping", AsyncMock()),
            patch.object(sync.sync_service.encounter_repo, "create", AsyncMock(side_effect=fake_create)),
            patch.object(sync.finalize_service, "finalize_encounter_score", AsyncMock()) as finalize,
            patch.object(sync, "record_result_transition", side_effect=lambda *_a, **kw: audits.append(kw)),
        ):
            result = await sync.sync_service._upsert_encounter_from_challonge(
                SimpleNamespace(),
                tournament,
                source,
                self._match(state=state),
                match_lookup=match_lookup,
                team_lookup=team_lookup,
            )
        return result, created, finalize, audits

    async def test_confirms_and_finalizes_on_creation(self) -> None:
        result, created, finalize, audits = await self._upsert(state="complete")

        self.assertEqual("created", result.action)
        self.assertTrue(result.newly_completed)
        # Born OPEN, not COMPLETED-without-a-result_status — finalize (mocked
        # here) is what actually moves it to COMPLETED in the real path.
        self.assertEqual(enums.EncounterStatus.OPEN, created[0].status)
        finalize.assert_awaited_once()
        self.assertEqual(enums.EncounterResultStatus.CONFIRMED, finalize.await_args.kwargs["result_status"])
        self.assertIsNotNone(finalize.await_args.kwargs["confirmed_at"])
        self.assertEqual(1, len(audits))
        self.assertEqual(enums.EncounterResultAuditAction.IMPORT, audits[0]["action"])
        self.assertIsNone(audits[0]["actor_user_id"])

    async def test_leaves_an_unfinished_match_alone(self) -> None:
        result, created, finalize, audits = await self._upsert(state="open")

        self.assertEqual("created", result.action)
        self.assertFalse(result.newly_completed)
        self.assertEqual(enums.EncounterStatus.OPEN, created[0].status)
        finalize.assert_not_awaited()
        self.assertEqual([], audits)


class CompletingAnExistingOpenMatch(IsolatedAsyncioTestCase):
    """The create path was already fixed to be born OPEN then finalize.

    The UPDATE path still assigned ``status=COMPLETED`` and flushed before
    finalize, tripping ``ck_encounter_result_status_matches_status``
    (OWT-TOURNAMENTS-295 / 29P).
    """

    async def test_does_not_flush_completed_before_finalize(self) -> None:
        encounter = _encounter(
            status=enums.EncounterStatus.OPEN,
            result_status=enums.EncounterResultStatus.NONE,
        )
        source = sync._ImportSource(challonge_id=100, stage=SimpleNamespace())
        match_lookup = sync._MatchLookup(
            by_source_key={}, by_challonge_id={1: encounter}, mapped_keys=set(), unlinked_by_slot={}
        )
        session = SimpleNamespace(flush=AsyncMock())

        with (
            patch.object(
                sync.sync_service.structure,
                "_resolve_stage_refs_for_match",
                AsyncMock(return_value=sync.StageRefs(stage_id=None, stage_item_id=None)),
            ),
            patch.object(sync.sync_service.mapping, "_ensure_match_mapping", AsyncMock()),
            patch.object(sync, "after_encounter_teams_changed", AsyncMock()),
            patch.object(sync.finalize_service, "finalize_encounter_score", AsyncMock()) as finalize,
            patch.object(sync, "record_result_transition"),
        ):
            result = await sync.sync_service._upsert_encounter_from_challonge(
                session,
                SimpleNamespace(id=1),
                source,
                CreatingAnAlreadyCompleteMatch()._match(state="complete"),
                match_lookup=match_lookup,
                team_lookup=sync._TeamLookup(by_source_key={}, by_key={}, teams_by_id={}),
            )

        self.assertEqual("updated", result.action)
        self.assertTrue(result.newly_completed)
        self.assertEqual(enums.EncounterStatus.OPEN, encounter.status)
        session.flush.assert_awaited()
        finalize.assert_awaited_once()


class AdoptingAnUnlinkedLocalEncounter(IsolatedAsyncioTestCase):
    """A bracket generated locally (StageService.generate_encounters) before its
    Challonge source was ever imported already has real Encounter rows sitting in
    the bracket's slots, with no challonge_match_mapping yet. Importing the same
    slot must adopt that row instead of creating a duplicate sibling next to it —
    the bug behind a double-elimination bracket's later rounds (and the Grand
    Final in particular) rendering twice after a Challonge import."""

    def _match(self) -> object:
        return sync.schemas.ChallongeMatch(
            id=1,
            started_at=None,
            created_at=sync.datetime.now(sync.UTC),
            updated_at=None,
            player1_id=101,
            player2_id=102,
            round=1,
            identifier="A1",
            state="complete",
            scores_csv="2-0",
            tournament_id=1,
            group_id=None,
        )

    async def test_reuses_the_existing_slot_instead_of_creating_a_duplicate(self) -> None:
        tournament = SimpleNamespace(id=1)
        source = sync._ImportSource(challonge_id=100, stage=SimpleNamespace())
        local_encounter = _encounter(status=enums.EncounterStatus.OPEN, result_status=enums.EncounterResultStatus.NONE)
        match_lookup = sync._MatchLookup(
            by_source_key={},
            by_challonge_id={},
            mapped_keys=set(),
            unlinked_by_slot={(None, 1, frozenset({1, 2})): local_encounter},
        )
        team_lookup = sync._TeamLookup(
            by_source_key={},
            by_key={(None, 101): 1, (None, 102): 2},
            teams_by_id={
                1: SimpleNamespace(id=1, name="Home"),
                2: SimpleNamespace(id=2, name="Away"),
            },
        )
        created: list = []

        async def fake_create(_session, encounter):
            created.append(encounter)
            return encounter

        session = SimpleNamespace(flush=AsyncMock())

        with (
            patch.object(
                sync.sync_service.structure,
                "_resolve_stage_refs_for_match",
                AsyncMock(return_value=sync.StageRefs(stage_id=None, stage_item_id=None)),
            ),
            patch.object(sync.sync_service.mapping, "_ensure_match_mapping", AsyncMock()),
            patch.object(sync.sync_service.encounter_repo, "create", AsyncMock(side_effect=fake_create)),
            patch.object(sync.finalize_service, "finalize_encounter_score", AsyncMock()),
            patch.object(sync, "record_result_transition"),
        ):
            result = await sync.sync_service._upsert_encounter_from_challonge(
                session,
                tournament,
                source,
                self._match(),
                match_lookup=match_lookup,
                team_lookup=team_lookup,
            )

        self.assertEqual([], created, "must not create a second row for the same slot")
        self.assertEqual("updated", result.action)
        self.assertIs(local_encounter, result.encounter)
        self.assertEqual(2, local_encounter.home_score)
        self.assertEqual(0, local_encounter.away_score)
        self.assertEqual({}, match_lookup.unlinked_by_slot, "the slot is claimed, not reusable twice")
