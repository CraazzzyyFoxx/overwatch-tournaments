"""``AggregateNodeConfig``: the score rule is checked on save (spec §7.4, plan Decision 10)."""

import pytest
from pydantic import ValidationError

from shared.domain.flow.config import AggregateNodeConfig

BASE = {"unit": "players", "mode": "sum_all"}


def test_a_valid_formula_is_accepted():
    AggregateNodeConfig.model_validate(
        {**BASE, "score": {"preset": "formula", "formula": "max(0, participants - place + 1) * 2"}}
    )


@pytest.mark.parametrize(
    ("score", "code"),
    [
        ({"preset": "formula", "formula": "place +"}, "ffa_formula_syntax"),
        ({"preset": "formula", "formula": "kills * 2"}, "ffa_formula_unknown_name"),
        ({"preset": "formula", "formula": "x" * 501}, "ffa_formula_too_complex"),
        ({"preset": "formula"}, "aggregate_formula_required"),
        ({"preset": "placement_table", "table": {}}, "aggregate_table_required"),
        ({"preset": "placement_table", "table": {"first": 10}}, "aggregate_table_place"),
    ],
)
def test_an_invalid_score_is_rejected(score, code):
    with pytest.raises(ValidationError) as caught:
        AggregateNodeConfig.model_validate({**BASE, "score": score})
    assert caught.value.errors()[0]["type"] == code


def test_the_error_carries_the_offset():
    with pytest.raises(ValidationError) as caught:
        AggregateNodeConfig.model_validate({**BASE, "score": {"preset": "formula", "formula": "place + kills"}})
    assert caught.value.errors()[0]["ctx"] == {"offset": 8, "name": "kills"}
