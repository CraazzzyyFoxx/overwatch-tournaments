"""A stage read reports the scoring rule it was saved with; it never re-runs the write-time checks.

The formula language may reserve more names later: a stage saved before that must still read, or every list that
embeds it would answer 422. Writes keep ``StageScoring`` and its validation.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src import schemas

# A column the formula language now owns the name of, and a formula that no longer compiles.
_STORED = {"preset": "points", "columns": [{"key": "and", "label": "And"}], "formula": "and +"}


def test_a_stored_rule_reads_back_as_saved() -> None:
    read = schemas.StageSummaryRead.model_validate(
        {
            "id": 1,
            "tournament_id": 1,
            "name": "Groups",
            "description": None,
            "stage_type": "ffa_league",
            "order": 0,
            "is_active": True,
            "is_completed": False,
            "scoring": _STORED,
        }
    )

    assert (read.scoring.formula, read.scoring.columns[0].key) == ("and +", "and")


def test_a_write_still_checks_the_rule() -> None:
    with pytest.raises(ValidationError):
        schemas.StageScoring.model_validate(_STORED)
