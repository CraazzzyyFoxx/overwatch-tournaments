"""``settings_json['ffa_scoring']``: what the regulation blob may not say.

Pure schema tests -- no session, no fixtures. The point is the same as for
``scoring`` (item 16): a lobby scoring table that only explodes later, inside
the points adder mid-tournament, must be refused at the edit endpoint instead::

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
            schemas.StageSettings.model_validate({"ffa_scoring": {"placement_points": [10, -1]}})

    def test_unknown_ffa_scoring_keys_are_refused(self) -> None:
        # Unlike the surrounding blob, this sub-object is closed: a typo'd key
        # would otherwise be stored and silently score nothing.
        with self.assertRaises(pydantic.ValidationError):
            schemas.StageSettings.model_validate({"ffa_scoring": {"score_points": 1, "extra": 1}})

    def test_a_placement_table_longer_than_a_lobby_is_refused(self) -> None:
        payload = {"ffa_scoring": {"placement_points": [1.0] * (FFA_MAX_LOBBY_SIZE + 1)}}
        with self.assertRaises(pydantic.ValidationError):
            schemas.StageSettings.model_validate(payload)

    def test_a_full_length_placement_table_is_accepted(self) -> None:
        payload = {"ffa_scoring": {"placement_points": [1.0] * FFA_MAX_LOBBY_SIZE}}
        self.assertIsNotNone(schemas.StageSettings.model_validate(payload).ffa_scoring)

    def test_negative_score_points_are_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.StageSettings.model_validate({"ffa_scoring": {"score_points": -1}})

    def test_a_valid_block_is_stored_verbatim(self) -> None:
        # Like ``scoring``: the model validates, the caller's dict is what the
        # stage keeps -- no invented defaults, no dropped keys.
        payload = {"ffa_scoring": {"placement_points": [10, 7, 5], "score_label": "Kills"}}
        self.assertEqual(payload, schemas.StageUpdate(settings_json=payload).settings_json)


class FfaStageTypeTests(TestCase):
    def test_the_stage_type_accepts_ffa_league(self) -> None:
        # Until the scoring rules landed the API answered 422 on purpose; now
        # the member exists, an ffa_league stage can be created.
        self.assertEqual("ffa_league", schemas.StageCreate(name="FFA", stage_type="ffa_league").stage_type)
