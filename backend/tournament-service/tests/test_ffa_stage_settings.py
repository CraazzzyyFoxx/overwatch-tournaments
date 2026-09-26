"""``FfaScoring``: what an ffa_league stage's scoring may not say.

Pure schema tests -- no session, no fixtures. The point is that a lobby scoring
table that would only explode later, inside the points adder mid-tournament, is
refused at the edit endpoint instead::

    uv run pytest tournament-service/tests/test_ffa_stage_settings.py -q
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import TestCase

import pydantic

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

schemas = importlib.import_module("src.schemas")

from shared.domain.ffa_scoring import FFA_MAX_LOBBY_SIZE  # noqa: E402


class FfaScoringSchemaTests(TestCase):
    def test_negative_placement_points_are_refused(self) -> None:
        # A negative place reward means finishing higher can cost points.
        with self.assertRaises(pydantic.ValidationError):
            schemas.FfaScoring(placement_points=[10, -1])

    def test_unknown_ffa_scoring_keys_are_refused(self) -> None:
        # The object is closed: a typo'd key would otherwise be accepted and
        # silently score nothing.
        with self.assertRaises(pydantic.ValidationError):
            schemas.FfaScoring(score_points=1, extra=1)

    def test_a_placement_table_longer_than_a_lobby_is_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.FfaScoring(placement_points=[1.0] * (FFA_MAX_LOBBY_SIZE + 1))

    def test_a_full_length_placement_table_is_accepted(self) -> None:
        scoring = schemas.FfaScoring(placement_points=[1.0] * FFA_MAX_LOBBY_SIZE)
        self.assertEqual(FFA_MAX_LOBBY_SIZE, len(scoring.placement_points))

    def test_negative_score_points_are_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.FfaScoring(score_points=-1)

    def test_a_stage_edit_carries_the_block_with_its_unsent_defaults(self) -> None:
        scoring = schemas.StageUpdate(ffa_scoring={"placement_points": [10, 7, 5], "score_label": "Kills"}).ffa_scoring
        self.assertEqual(
            ([10.0, 7.0, 5.0], "Kills", 1.0), (scoring.placement_points, scoring.score_label, scoring.score_points)
        )


class FfaStageTypeTests(TestCase):
    def test_the_stage_type_accepts_ffa_league(self) -> None:
        # Until the scoring rules landed the API answered 422 on purpose; now
        # the member exists, an ffa_league stage can be created.
        self.assertEqual("ffa_league", schemas.StageCreate(name="FFA", stage_type="ffa_league").stage_type)
