"""Tests for custom bracket templates: model, conversions and validator.

Does not touch the database -- purely tests the pure-function shared library.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from pydantic import ValidationError  # noqa: E402

from shared.core.enums import StageType  # noqa: E402
from shared.services.bracket.engine import placeholder_bracket  # noqa: E402
from shared.services.bracket.template import (  # noqa: E402
    BracketTemplate,
    skeleton_to_template,
    template_to_skeleton,
    validate_template,
)


def _sketch() -> dict:
    """The organizer's 4+4 sketch: UB R1 x2, UB final, LB R1 x2, LB R2 x2 (cross-drop), LB R3, LB R4, GF."""
    s = lambda **kw: kw  # noqa: E731
    return {
        "upper_seeds": 4,
        "lower_seeds": 4,
        "matches": [
            {"id": 0, "round": 1, "home": s(seed="U1"), "away": s(seed="U4")},
            {"id": 1, "round": 1, "home": s(seed="U2"), "away": s(seed="U3")},
            {"id": 2, "round": 2, "home": s(winner_of=0), "away": s(winner_of=1)},
            {"id": 3, "round": -1, "home": s(seed="L1"), "away": s(seed="L4")},
            {"id": 4, "round": -1, "home": s(seed="L2"), "away": s(seed="L3")},
            {"id": 5, "round": -2, "home": s(winner_of=3), "away": s(loser_of=1)},
            {"id": 6, "round": -2, "home": s(winner_of=4), "away": s(loser_of=0)},
            {"id": 7, "round": -3, "home": s(winner_of=5), "away": s(winner_of=6)},
            {"id": 8, "round": -4, "home": s(winner_of=7), "away": s(loser_of=2)},
            {"id": 9, "round": 3, "home": s(winner_of=2), "away": s(winner_of=8)},
        ],
    }


def _codes(raw: dict, stage_type=StageType.DOUBLE_ELIMINATION) -> list[tuple[int | None, str]]:
    return [(p.match_id, p.code) for p in validate_template(BracketTemplate.model_validate(raw), stage_type)]


def _flags(raw: dict, stage_type=StageType.DOUBLE_ELIMINATION) -> list[tuple[int | None, str | None, str]]:
    return [(p.match_id, p.slot, p.code) for p in validate_template(BracketTemplate.model_validate(raw), stage_type)]


class TemplateValidationTests(TestCase):
    def test_the_sketch_is_valid(self) -> None:
        self.assertEqual([], _codes(_sketch()))

    def test_slot_needs_exactly_one_origin(self) -> None:
        raw = _sketch()
        raw["matches"][0]["home"] = {"seed": "U1", "winner_of": 2}
        with self.assertRaises(ValidationError):
            BracketTemplate.model_validate(raw)

    def test_duplicate_id(self) -> None:
        raw = _sketch()
        raw["matches"][1]["id"] = 0
        self.assertIn((0, "duplicate_id"), _codes(raw))

    def test_zero_round(self) -> None:
        raw = _sketch()
        raw["matches"][0]["round"] = 0
        self.assertIn((0, "zero_round"), _codes(raw))

    def test_unknown_match(self) -> None:
        raw = _sketch()
        raw["matches"][2]["home"] = {"winner_of": 42}
        self.assertIn((2, "unknown_match"), _codes(raw))

    def test_seed_out_of_range_and_unused(self) -> None:
        raw = _sketch()
        raw["matches"][0]["away"] = {"seed": "U5"}
        codes = _codes(raw)
        self.assertIn((0, "seed_out_of_range"), codes)
        self.assertIn((None, "seed_unused"), codes)

    def test_seed_duplicate(self) -> None:
        raw = _sketch()
        raw["matches"][0]["away"] = {"seed": "U2"}
        self.assertIn((0, "seed_duplicate"), _codes(raw))

    def test_upper_seed_cannot_start_in_the_lower_bracket(self) -> None:
        raw = _sketch()
        raw["matches"][3]["home"] = {"seed": "U1"}  # an LB round-1 slot, handed an upper seed
        self.assertIn((3, "home", "seed_bracket"), _flags(raw))

    def test_lower_seed_cannot_start_in_the_upper_bracket(self) -> None:
        raw = _sketch()
        raw["matches"][0]["away"] = {"seed": "L1"}  # a UB round-1 slot, handed a lower seed
        self.assertIn((0, "away", "seed_bracket"), _flags(raw))

    def test_result_reused(self) -> None:
        raw = _sketch()
        raw["matches"][7]["away"] = {"winner_of": 5}
        self.assertIn((7, "result_reused"), _codes(raw))

    def test_round_gap(self) -> None:
        raw = _sketch()
        raw["matches"][2]["round"] = 4  # the UB final jumps a round, leaving round 3 to the GF alone
        self.assertIn((None, "round_gap"), _codes(raw))

    def test_lower_rounds_may_start_deeper_and_skip(self) -> None:
        # The generator numbers an LB round after the upper round dropping into it and
        # skips the all-bye ones, so generated lower rounds start below -1 and have holes.
        raw = _sketch()
        for match in raw["matches"]:
            if match["round"] < 0:
                match["round"] -= 1
        raw["matches"][8]["round"] = -7
        self.assertEqual([], _codes(raw))

    def test_edge_direction_backwards(self) -> None:
        raw = _sketch()
        raw["matches"][5]["home"] = {"winner_of": 7}
        raw["matches"][7]["home"] = {"winner_of": 3}
        self.assertIn((5, "edge_direction"), _codes(raw))

    def test_upper_winner_cannot_drop(self) -> None:
        raw = _sketch()
        raw["matches"][5]["away"] = {"winner_of": 1}
        raw["matches"][2]["away"] = {"loser_of": 1}
        self.assertIn((5, "edge_direction"), _codes(raw))

    def test_two_terminals_means_no_single_final(self) -> None:
        raw = _sketch()
        del raw["matches"][9]  # no GF: the UB final and the LB final both end the bracket
        codes = _codes(raw)
        self.assertIn((2, "final"), codes)
        self.assertIn((8, "final"), codes)

    def test_de_final_needs_lower_winner(self) -> None:
        # One match, so it is the final; nothing comes up from a lower bracket.
        raw = {
            "upper_seeds": 2,
            "lower_seeds": 0,
            "matches": [{"id": 0, "round": 1, "home": {"seed": "U1"}, "away": {"seed": "U2"}}],
        }
        self.assertIn((0, "de_final_needs_lower"), _codes(raw))

    def test_de_upper_loser_must_drop(self) -> None:
        # Match 0's loser no longer drops: its LB slot takes a fifth lower seed instead.
        raw = _sketch()
        raw["lower_seeds"] = 5
        raw["matches"][6]["away"] = {"seed": "L5"}
        self.assertEqual([(0, "de_upper_loser")], _codes(raw))

    def test_de_lower_loser_is_out(self) -> None:
        raw = _sketch()
        raw["matches"][8]["away"] = {"loser_of": 7}
        self.assertIn((8, "de_lower_loser"), _codes(raw))

    def test_single_elimination_has_no_lower_bracket(self) -> None:
        self.assertIn((None, "se_shape"), _codes(_sketch(), StageType.SINGLE_ELIMINATION))


class TemplateBoundsTests(TestCase):
    """A template arrives from the network: every number it carries is bounded."""

    def _rejects(self, **overrides) -> None:
        raw = _sketch()
        raw.update(overrides)
        with self.assertRaises(ValidationError):
            BracketTemplate.model_validate(raw)

    def test_upper_seeds_above_512(self) -> None:
        self._rejects(upper_seeds=513)

    def test_lower_seeds_above_512(self) -> None:
        self._rejects(lower_seeds=513)

    def test_round_below_minus_256(self) -> None:
        raw = _sketch()
        raw["matches"][3]["round"] = -257
        with self.assertRaises(ValidationError):
            BracketTemplate.model_validate(raw)

    def test_match_id_above_10000(self) -> None:
        raw = _sketch()
        raw["matches"][0]["id"] = 10_001
        with self.assertRaises(ValidationError):
            BracketTemplate.model_validate(raw)

    def test_seed_longer_than_five_characters(self) -> None:
        raw = _sketch()
        raw["matches"][0]["home"] = {"seed": "U12345"}
        with self.assertRaises(ValidationError):
            BracketTemplate.model_validate(raw)

    def test_the_bounds_themselves_are_accepted(self) -> None:
        raw = _sketch()
        raw["upper_seeds"] = 512
        raw["lower_seeds"] = 512
        raw["matches"][0]["id"] = 10_000
        raw["matches"][3]["round"] = -256
        BracketTemplate.model_validate(raw)  # bounds are inclusive; §5.2 problems are the validator's job


class TemplateRoundTripTests(TestCase):
    def test_every_generated_bracket_is_a_valid_template_and_round_trips(self) -> None:
        for stage_type, lowers in (
            (StageType.SINGLE_ELIMINATION, (0,)),
            (StageType.DOUBLE_ELIMINATION, range(0, 13)),
        ):
            for upper in range(2, 9):
                for lower in lowers:
                    if stage_type == StageType.DOUBLE_ELIMINATION and (upper, lower) == (2, 0):
                        # degenerate 2-team DE: the generator's GF takes the UB loser, no lower
                        # bracket -- pre-existing, reset can never trigger; a template of it is
                        # rightly rejected.
                        continue
                    skeleton = placeholder_bracket(stage_type, upper, lower_count=lower)
                    template = skeleton_to_template(skeleton, upper_seeds=upper, lower_seeds=lower)
                    self.assertEqual([], validate_template(template, stage_type), (stage_type, upper, lower))
                    back = template_to_skeleton(template)
                    self.assertEqual(
                        [(p.home_team_id, p.away_team_id, p.round_number, p.local_id) for p in skeleton.pairings],
                        [(p.home_team_id, p.away_team_id, p.round_number, p.local_id) for p in back.pairings],
                    )
                    self.assertEqual(
                        sorted(skeleton.advancement_edges, key=repr),
                        sorted(back.advancement_edges, key=repr),
                    )
