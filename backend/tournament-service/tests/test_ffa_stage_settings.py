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

from shared.domain.ffa_scoring import FFA_MAX_COLUMNS, FFA_MAX_LOBBY_SIZE  # noqa: E402


class FfaScoringSchemaTests(TestCase):
    KILLS = {"key": "kills", "label": "Kills"}

    def _reject(self, **block) -> dict:
        with self.assertRaises(pydantic.ValidationError) as ctx:
            schemas.FfaScoring(**block)
        return ctx.exception.errors()[0]

    def test_an_unconfigured_block_is_one_score_column(self) -> None:
        # A stage that never opened the editor must score exactly what it
        # scored before columns existed.
        scoring = schemas.FfaScoring()
        self.assertEqual(
            [("score", "Счёт", True, "higher")], [(c.key, c.label, c.public, c.better) for c in scoring.columns]
        )
        self.assertEqual("score", scoring.formula)

    def test_negative_placement_points_are_refused(self) -> None:
        # A negative place reward means finishing higher can cost points.
        with self.assertRaises(pydantic.ValidationError):
            schemas.FfaScoring(columns=[self.KILLS], formula="kills", placement_points=[10, -1])

    def test_unknown_ffa_scoring_keys_are_refused(self) -> None:
        # The object is closed: a typo'd key would otherwise be accepted and
        # silently score nothing.
        with self.assertRaises(pydantic.ValidationError):
            schemas.FfaScoring(columns=[self.KILLS], formula="kills", score_points=1)

    def test_a_placement_table_longer_than_a_lobby_is_refused(self) -> None:
        with self.assertRaises(pydantic.ValidationError):
            schemas.FfaScoring(columns=[self.KILLS], formula="kills", placement_points=[1.0] * (FFA_MAX_LOBBY_SIZE + 1))

    def test_a_full_length_placement_table_is_accepted(self) -> None:
        scoring = schemas.FfaScoring(columns=[self.KILLS], formula="kills", placement_points=[1.0] * FFA_MAX_LOBBY_SIZE)
        self.assertEqual(FFA_MAX_LOBBY_SIZE, len(scoring.placement_points))

    def test_a_column_key_must_be_a_usable_identifier(self) -> None:
        self.assertEqual(
            "ffa_column_key_invalid", self._reject(columns=[{"key": "Kills", "label": "K"}], formula="1")["type"]
        )
        self.assertEqual(
            "ffa_column_key_invalid", self._reject(columns=[{"key": "", "label": "K"}], formula="1")["type"]
        )

    def test_a_column_may_not_shadow_a_formula_word(self) -> None:
        for key in ("place", "place_pts", "teams", "min", "round", "if", "if_", "not"):
            self.assertEqual(
                "ffa_column_key_reserved", self._reject(columns=[{"key": key, "label": "K"}], formula="1")["type"], key
            )

    def test_duplicate_and_too_many_columns_are_refused(self) -> None:
        duplicate = self._reject(columns=[{"key": "k", "label": "A"}, {"key": "k", "label": "B"}], formula="k")
        self.assertEqual("ffa_column_duplicate", duplicate["type"])
        self.assertEqual("k", duplicate["ctx"]["name"])
        too_many = self._reject(
            columns=[{"key": f"c{i}", "label": "x"} for i in range(FFA_MAX_COLUMNS + 1)], formula="1"
        )
        self.assertEqual("ffa_columns_too_many", too_many["type"])

    def test_a_blank_label_is_refused(self) -> None:
        self.assertEqual("string_too_short", self._reject(columns=[{"key": "k", "label": "   "}], formula="k")["type"])

    def test_a_broken_formula_is_not_saved_and_carries_its_position(self) -> None:
        unknown = self._reject(columns=[self.KILLS], formula="place_pts + kils")
        self.assertEqual("ffa_formula_unknown_name", unknown["type"])
        self.assertEqual({"offset": 12, "name": "kils"}, unknown["ctx"])

        unsupported = self._reject(columns=[self.KILLS], formula="kills ** 2")
        self.assertEqual("ffa_formula_unsupported", unsupported["type"])
        self.assertEqual(0, unsupported["ctx"]["offset"])

        self.assertEqual("ffa_formula_syntax", self._reject(columns=[self.KILLS], formula="kills +")["type"])

    def test_a_formula_reading_a_column_that_is_not_there_is_refused(self) -> None:
        # The pair is validated together: a column renamed without touching the
        # formula must not be storable.
        error = self._reject(columns=[self.KILLS], formula="kills + deaths")
        self.assertEqual(("ffa_formula_unknown_name", "deaths"), (error["type"], error["ctx"]["name"]))

    def test_a_configured_block_round_trips(self) -> None:
        scoring = schemas.StageUpdate(
            ffa_scoring={
                "columns": [
                    {"key": "kills", "label": " Убийства "},
                    {"key": "deaths", "label": "Смерти", "public": False, "better": "lower"},
                ],
                "placement_points": [10, 7, 5],
                "formula": "place_pts + kills * 2 - deaths",
            }
        ).ffa_scoring
        self.assertEqual("Убийства", scoring.columns[0].label)
        self.assertEqual((False, "lower"), (scoring.columns[1].public, scoring.columns[1].better))
        self.assertEqual([10.0, 7.0, 5.0], scoring.placement_points)


class FfaStageTypeTests(TestCase):
    def test_the_stage_type_accepts_ffa_league(self) -> None:
        # Until the scoring rules landed the API answered 422 on purpose; now
        # the member exists, an ffa_league stage can be created.
        self.assertEqual("ffa_league", schemas.StageCreate(name="FFA", stage_type="ffa_league").stage_type)
