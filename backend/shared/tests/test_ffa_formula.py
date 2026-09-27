"""The formula language: what it computes, and what it refuses to save.

Pure, no fixtures::

    uv run pytest shared/tests/test_ffa_formula.py -v

Every rejection is checked by ``code`` and by ``offset`` in the string the
organizer typed -- that pair is what the stage editor underlines, so it is the
contract, not the wording of the message.
"""

from __future__ import annotations

import pytest

from shared.domain.ffa_formula import FfaFormulaError, compile_formula, round_half_up

COLUMNS = ("kills", "deaths")


def points(source: str, **values: float) -> float:
    return compile_formula(source, COLUMNS).evaluate(values)


def error(source: str, columns: tuple[str, ...] = COLUMNS) -> FfaFormulaError:
    with pytest.raises(FfaFormulaError) as info:
        compile_formula(source, columns)
    return info.value


def test_every_construct_of_the_grammar_computes() -> None:
    assert points("place_pts + kills * 2 - deaths", place_pts=10, kills=3, deaths=1) == 15
    assert points("1_000 + 0.5") == 1000.5
    assert points("-kills", kills=4) == -4
    assert points("(kills + deaths) / 2", kills=3, deaths=1) == 2
    assert points("teams - place", teams=8, place=3) == 5
    assert points("min(kills, deaths, 5)", kills=9, deaths=7) == 5
    assert points("max(kills, deaths)", kills=9, deaths=7) == 9
    assert points("abs(0 - kills)", kills=4) == 4
    assert points("if(place <= 3, 10, 0)", place=2) == 10
    assert points("if(place <= 3, 10, 0)", place=9) == 0


def test_comparisons_and_logic_are_one_or_zero() -> None:
    assert points("kills == 3", kills=3) == 1.0
    assert points("kills != 3", kills=3) == 0.0
    assert points("1 < kills < 5", kills=3) == 1.0
    assert points("1 < kills < 2", kills=3) == 0.0
    assert points("kills and deaths", kills=3, deaths=0) == 0.0
    assert points("kills or deaths", kills=0, deaths=2) == 1.0
    assert points("not kills", kills=0) == 1.0


def test_a_name_with_no_value_reads_as_zero() -> None:
    # A column added mid-stage: games already played have no value for it.
    assert points("kills + deaths", kills=5) == 5


def test_dividing_by_zero_scores_zero() -> None:
    assert points("kills / deaths", kills=7, deaths=0) == 0.0


def test_an_overflowing_result_scores_zero() -> None:
    assert points("1e308 * 10") == 0.0


def test_round_is_arithmetic_not_bankers() -> None:
    assert points("round(2.5)") == 3
    assert points("round(0 - 2.5)") == -3
    assert points("round(kills / 3, 2)", kills=10) == 3.33
    assert round_half_up(0.1 + 0.2, 4) == 0.3


def test_names_are_the_variables_read_never_the_functions() -> None:
    assert compile_formula("place_pts + kills", COLUMNS).names == frozenset({"place_pts", "kills"})
    assert compile_formula("min(kills, 3)", COLUMNS).names == frozenset({"kills"})
    assert compile_formula("score", ("score",)).names == frozenset({"score"})


@pytest.mark.parametrize(
    "source",
    [
        "kills ** 2",
        "kills % 2",
        "kills // 2",
        "kills.real",
        "[kills][0]",
        "round(kills, ndigits=2)",
        "min(*[1, 2])",
        "(x for x in [1])",
        "lambda: 1",
        "(k := 2)",
        "True",
        "None",
        "1j",
        "'x'",
        "1 in [1]",
        "min(kills)",
        "abs(kills, 1)",
        "if(kills, 1)",
        "round(kills, 7)",
        "round(kills, kills)",
        "min",
    ],
)
def test_everything_outside_the_grammar_is_refused(source: str) -> None:
    assert error(source).code == "ffa_formula_unsupported"


def test_an_unknown_name_carries_the_name_and_its_position() -> None:
    unknown = error("place_pts + kils")
    assert (unknown.code, unknown.offset, unknown.name) == ("ffa_formula_unknown_name", 12, "kils")


def test_positions_point_into_the_string_the_organizer_typed() -> None:
    # ``if(`` is rewritten to ``if_(`` before parsing, so every offset the
    # parser reports is one character too far right per preceding ``if``.
    source = "if(place == 1, kills, kils)"
    assert error(source).offset == 22 and source[22:26] == "kils"

    nested = "if(place == 1, if(kills > 3, 1, 0), kills ** 2)"
    rejected = error(nested)
    assert rejected.code == "ffa_formula_unsupported"
    assert rejected.offset == 36 and nested[36:41] == "kills"


def test_an_unparsable_formula_is_a_syntax_error() -> None:
    assert error("kills +").code == "ffa_formula_syntax"
    assert error("").code == "ffa_formula_syntax"


def test_a_number_too_big_for_a_float_is_refused_with_a_position() -> None:
    # 400 digits fits the length cap, so only the constant check stands between
    # this and an OverflowError escaping as a 500.
    huge = error("place_pts + " + "9" * 400)
    assert (huge.code, huge.offset) == ("ffa_formula_unsupported", 12)
    assert error("9" * 400).code == "ffa_formula_unsupported"


def test_a_formula_too_big_to_walk_is_refused() -> None:
    assert error(" + ".join(["kills"] * 60)).code == "ffa_formula_too_complex"
    assert error("kills * " + "1" * 500).code == "ffa_formula_too_complex"
