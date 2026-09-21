"""One predicate decides whether an encounter has been played.

Three places used to ask the question with their own OR of ``status`` and
``result_status``. The risk was never the OR itself but that each call site was
free to phrase it differently — an AND here, one column there — so the same
encounter could count as played for standings and not for Swiss round-advance
readiness. Since ``encres0001`` a CHECK constraint makes the two columns
equivalent, so the question has exactly one form and these tests pin it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.core import enums
from shared.domain.tournament_utils import completed_encounters, is_completed_encounter


def _encounter(*, status, result_status, home_team_id=1, away_team_id=2) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        status=status,
        result_status=result_status,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
    )


class TestIsCompletedEncounter:
    def test_a_completed_encounter_counts(self):
        encounter = _encounter(
            status=enums.EncounterStatus.COMPLETED,
            result_status=enums.EncounterResultStatus.CONFIRMED,
        )
        assert is_completed_encounter(encounter)

    @pytest.mark.parametrize(
        "status",
        [enums.EncounterStatus.OPEN, enums.EncounterStatus.PENDING],
    )
    def test_an_unfinished_encounter_does_not(self, status):
        encounter = _encounter(status=status, result_status=enums.EncounterResultStatus.NONE)
        assert not is_completed_encounter(encounter)

    @pytest.mark.parametrize(
        "result_status",
        [
            enums.EncounterResultStatus.PENDING_CONFIRMATION,
            enums.EncounterResultStatus.DISPUTED,
        ],
    )
    def test_a_result_still_under_discussion_does_not(self, result_status):
        """One report in, or two that disagree: the encounter is not played yet,
        and the constraint keeps ``status`` OPEN behind that."""
        encounter = _encounter(status=enums.EncounterStatus.OPEN, result_status=result_status)
        assert not is_completed_encounter(encounter)

    def test_an_encounter_missing_a_team_never_counts(self):
        """An unfilled bracket slot cannot have been played, whatever its
        columns say."""
        for missing in ("home_team_id", "away_team_id"):
            encounter = _encounter(
                status=enums.EncounterStatus.COMPLETED,
                result_status=enums.EncounterResultStatus.CONFIRMED,
                **{missing: None},
            )
            assert not is_completed_encounter(encounter)


class TestCompletedEncounters:
    def test_filters_through_the_same_predicate(self):
        played = _encounter(
            status=enums.EncounterStatus.COMPLETED,
            result_status=enums.EncounterResultStatus.CONFIRMED,
        )
        unplayed = _encounter(
            status=enums.EncounterStatus.OPEN,
            result_status=enums.EncounterResultStatus.NONE,
        )
        assert completed_encounters([played, unplayed]) == [played]
