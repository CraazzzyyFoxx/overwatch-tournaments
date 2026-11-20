"""Tests for custom bracket templates: model, conversions and validator.

Does not touch the database: ``src.domain.bracket`` is pure.
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
from src.domain.bracket.engine import placeholder_bracket  # noqa: E402
from src.domain.bracket.template import (  # noqa: E402
    BracketTemplate,
    skeleton_to_template,
    template_to_skeleton,
    validate_template,
)


def _seed(ref: str) -> dict:
    return {"seed": ref}


def _winner(match: int) -> dict:
    return {"source_match": match, "source_position": 1}


def _loser(match: int) -> dict:
    return {"source_match": match, "source_position": 2}


def _match(match_id: int, round_number: int, *origins: dict) -> dict:
    return {
        "id": match_id,
        "round": round_number,
        "slots": [{"slot": number, **origin} for number, origin in enumerate(origins, start=1)],
    }


def _set_slot(raw: dict, index: int, slot: int, origin: dict) -> None:
    raw["matches"][index]["slots"][slot - 1] = {"slot": slot, **origin}


def _sketch() -> dict:
    """The organizer's 4+4 sketch: UB R1 x2, UB final, LB R1 x2, LB R2 x2 (cross-drop), LB R3, LB R4, GF."""
    return {
        "upper_seeds": 4,
        "lower_seeds": 4,
        "matches": [
            _match(0, 1, _seed("U1"), _seed("U4")),
            _match(1, 1, _seed("U2"), _seed("U3")),
            _match(2, 2, _winner(0), _winner(1)),
            _match(3, -1, _seed("L1"), _seed("L4")),
            _match(4, -1, _seed("L2"), _seed("L3")),
            _match(5, -2, _winner(3), _loser(1)),
            _match(6, -2, _winner(4), _loser(0)),
            _match(7, -3, _winner(5), _winner(6)),
            _match(8, -4, _winner(7), _loser(2)),
            _match(9, 3, _winner(2), _winner(8)),
        ],
    }


def _codes(raw: dict, stage_type=StageType.DOUBLE_ELIMINATION) -> list[tuple[int | None, str]]:
    return [(p.match_id, p.code) for p in validate_template(BracketTemplate.model_validate(raw), stage_type)]


def _flags(raw: dict, stage_type=StageType.DOUBLE_ELIMINATION) -> list[tuple[int | None, int | None, str]]:
    return [(p.match_id, p.slot, p.code) for p in validate_template(BracketTemplate.model_validate(raw), stage_type)]


class TemplateValidationTests(TestCase):
    def test_the_sketch_is_valid(self) -> None:
        self.assertEqual([], _codes(_sketch()))

    def test_slot_needs_exactly_one_origin(self) -> None:
        raw = _sketch()
        _set_slot(raw, 0, 1, {"seed": "U1", "source_match": 2, "source_position": 1})
        with self.assertRaises(ValidationError):
            BracketTemplate.model_validate(raw)

    def test_slots_are_numbered_without_gap(self) -> None:
        raw = _sketch()
        raw["matches"][0]["slots"][1]["slot"] = 3
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
        _set_slot(raw, 2, 1, _winner(42))
        self.assertIn((2, "unknown_match"), _codes(raw))

    def test_position_out_of_range(self) -> None:
        raw = _sketch()
        _set_slot(raw, 2, 1, {"source_match": 0, "source_position": 3})  # a duel has no third place
        self.assertIn((2, "position_out_of_range"), _codes(raw))

    def test_seed_out_of_range_and_unused(self) -> None:
        raw = _sketch()
        _set_slot(raw, 0, 2, _seed("U5"))
        codes = _codes(raw)
        self.assertIn((0, "seed_out_of_range"), codes)
        self.assertIn((None, "seed_unused"), codes)

    def test_seed_duplicate(self) -> None:
        raw = _sketch()
        _set_slot(raw, 0, 2, _seed("U2"))
        self.assertIn((0, "seed_duplicate"), _codes(raw))

    def test_upper_seed_cannot_start_in_the_lower_bracket(self) -> None:
        raw = _sketch()
        _set_slot(raw, 3, 1, _seed("U1"))  # an LB round-1 slot, handed an upper seed
        self.assertIn((3, 1, "seed_bracket"), _flags(raw))

    def test_lower_seed_cannot_start_in_the_upper_bracket(self) -> None:
        raw = _sketch()
        _set_slot(raw, 0, 2, _seed("L1"))  # a UB round-1 slot, handed a lower seed
        self.assertIn((0, 2, "seed_bracket"), _flags(raw))

    def test_result_reused(self) -> None:
        raw = _sketch()
        _set_slot(raw, 7, 2, _winner(5))
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
        _set_slot(raw, 5, 1, _winner(7))
        _set_slot(raw, 7, 1, _winner(3))
        self.assertIn((5, "edge_direction"), _codes(raw))

    def test_upper_winner_cannot_drop(self) -> None:
        raw = _sketch()
        _set_slot(raw, 5, 2, _winner(1))
        _set_slot(raw, 2, 2, _loser(1))
        self.assertIn((5, "edge_direction"), _codes(raw))

    def test_two_terminals_means_no_single_final(self) -> None:
        raw = _sketch()
        del raw["matches"][9]  # no GF: the UB final and the LB final both end the bracket
        codes = _codes(raw)
        self.assertIn((2, "final"), codes)
        self.assertIn((8, "final"), codes)

    def test_de_final_needs_lower_winner(self) -> None:
        # One match, so it is the final; nothing comes up from a lower bracket.
        raw = {"upper_seeds": 2, "lower_seeds": 0, "matches": [_match(0, 1, _seed("U1"), _seed("U2"))]}
        self.assertIn((0, "de_final_needs_lower"), _codes(raw))

    def test_de_upper_loser_must_drop(self) -> None:
        # Match 0's loser no longer drops: its LB slot takes a fifth lower seed instead.
        raw = _sketch()
        raw["lower_seeds"] = 5
        _set_slot(raw, 6, 2, _seed("L5"))
        self.assertEqual([(0, "de_upper_loser")], _codes(raw))

    def test_de_lower_loser_is_out(self) -> None:
        raw = _sketch()
        _set_slot(raw, 8, 2, _loser(7))
        self.assertIn((8, "de_lower_loser"), _codes(raw))

    def test_single_elimination_has_no_lower_bracket(self) -> None:
        self.assertIn((None, "se_shape"), _codes(_sketch(), StageType.SINGLE_ELIMINATION))

    def test_lower_final_and_its_winner_feeder_may_send_losers_to_bronze(self) -> None:
        raw = _sketch()
        # The bronze card's id and position in the list do not identify it.
        raw["matches"].insert(0, _match(42, 3, _loser(7), _loser(8)))
        self.assertEqual([], _codes(raw))

    def test_a_loser_edge_cannot_hide_behind_another_drop_from_the_same_match(self) -> None:
        raw = _sketch()
        raw["upper_seeds"] = 6
        raw["matches"][0] = _match(0, 1, _seed("U1"), _seed("U4"), _seed("U5"))
        raw["matches"][1] = _match(1, 2, _seed("U2"), _seed("U3"), _winner(0))
        raw["matches"][2] = _match(2, 4, _winner(1), _winner(10))
        raw["matches"][6] = _match(6, -2, _winner(4), {"source_match": 0, "source_position": 3})
        raw["matches"][9]["round"] = 5
        raw["matches"].insert(0, _match(10, 3, _loser(0), _seed("U6")))
        raw["matches"][7]["slots"].append({"slot": 3, **_loser(10)})
        raw["matches"].append(_match(11, 5, _loser(8), _loser(7)))
        self.assertIn((10, 1, "de_upper_loser"), _flags(raw))

    def test_a_lower_final_with_two_losers_cannot_feed_bronze(self) -> None:
        raw = _sketch()
        raw["lower_seeds"] = 5
        raw["matches"][8] = _match(8, -4, _winner(7), _loser(2), _seed("L5"))
        raw["matches"].append(_match(10, 3, _loser(8), _loser(7)))
        self.assertIn((10, "final"), _codes(raw))

    def test_only_one_terminal_bronze_with_exact_sources_and_round_is_allowed(self) -> None:
        bronze = _match(10, 3, _loser(8), _loser(7))
        for extra in (
            [_match(10, 3, _loser(8), _loser(6))],  # wrong lower feeder
            [_match(10, 2, _loser(8), _loser(7))],  # not alongside the final
            [bronze, _match(11, 3, _loser(8), _loser(7))],
            [bronze, _match(11, 4, _winner(10), _winner(9))],
            [bronze, _match(11, 4, _loser(10), _winner(9))],
            [_match(10, 3, _loser(8), _loser(7), _loser(6))],
        ):
            with self.subTest(extra=extra):
                raw = _sketch()
                raw["matches"].extend(extra)
                self.assertTrue(_codes(raw))

    def test_se_quarterfinal_losers_cannot_play_bronze(self) -> None:
        skeleton = placeholder_bracket(StageType.SINGLE_ELIMINATION, 8)
        raw = skeleton_to_template(skeleton, upper_seeds=8, lower_seeds=0).model_dump()
        raw["matches"].append(_match(7, 3, _loser(0), _loser(1)))
        self.assertTrue(_codes(raw, StageType.SINGLE_ELIMINATION))


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
        _set_slot(raw, 0, 1, _seed("U12345"))
        with self.assertRaises(ValidationError):
            BracketTemplate.model_validate(raw)

    def test_the_bounds_themselves_are_accepted(self) -> None:
        raw = _sketch()
        raw["upper_seeds"] = 512
        raw["lower_seeds"] = 512
        raw["matches"][0]["id"] = 10_000
        raw["matches"][3]["round"] = -256
        BracketTemplate.model_validate(raw)  # bounds are inclusive; convention problems are the validator's job


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
                        [(p.team_ids, p.round_number, p.local_id) for p in skeleton.pairings],
                        [(p.team_ids, p.round_number, p.local_id) for p in back.pairings],
                    )
                    self.assertEqual(
                        sorted(skeleton.advancement_edges, key=repr),
                        sorted(back.advancement_edges, key=repr),
                    )

    def test_generated_bronze_loser_links_survive_a_template_round_trip(self) -> None:
        for stage_type, upper, lower in (
            (StageType.SINGLE_ELIMINATION, 5, 0),
            (StageType.DOUBLE_ELIMINATION, 2, 3),
        ):
            with self.subTest(stage_type=stage_type):
                bracket = placeholder_bracket(stage_type, upper, lower_count=lower, third_place_match=True)
                template = skeleton_to_template(bracket, upper_seeds=upper, lower_seeds=lower)
                self.assertEqual([], validate_template(template, stage_type))
                restored = template_to_skeleton(template)
                self.assertEqual({bracket.pairings[-1].local_id}, restored.third_place_ids)
                self.assertCountEqual(bracket.advancement_edges, restored.advancement_edges)

    def test_bronze_keeps_the_largest_previously_editable_bracket_editable(self) -> None:
        bracket = placeholder_bracket(StageType.SINGLE_ELIMINATION, 257, third_place_match=True)
        template = skeleton_to_template(bracket, upper_seeds=257, lower_seeds=0)
        self.assertEqual([], validate_template(template, StageType.SINGLE_ELIMINATION))
        self.assertEqual(257, len(template.matches))
