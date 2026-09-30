"""The draft format is a tournament rule, normalized at the schema edge.

Two things are pinned here: the column never stores round rules a non-custom
format would ignore, and the tournament -> session projection pads or truncates
those rules to the round count the roster shape implies *today* (the shape may
have changed since the format was saved).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from shared.core.enums import DraftFormat
from shared.schemas.draft_format import (
    DraftFormatSettings,
    normalize_draft_format,
    session_format_from_tournament,
)

_CUSTOM = {
    "format": "custom",
    "round_rules": ["reverse", "weakest_first"],
    "avg_tie_seed_reverse": True,
}


@pytest.mark.parametrize("fmt", ["snake", "linear"])
def test_a_non_custom_format_drops_the_rules_it_cannot_apply(fmt: str) -> None:
    stored = normalize_draft_format({**_CUSTOM, "format": fmt})

    assert stored == {"format": fmt, "round_rules": [], "avg_tie_seed_reverse": False}


def test_custom_keeps_its_rules() -> None:
    assert normalize_draft_format(_CUSTOM) == _CUSTOM


def test_none_passes_through_as_the_inherited_default() -> None:
    assert normalize_draft_format(None) is None


def test_an_empty_payload_normalizes_to_snake() -> None:
    assert normalize_draft_format({}) == {"format": "snake", "round_rules": [], "avg_tie_seed_reverse": False}


@pytest.mark.parametrize(
    "raw",
    [
        {"format": "custom", "round_rules": ["sideways"]},
        {"format": "zigzag"},
    ],
)
def test_an_unknown_rule_or_format_is_rejected(raw: dict) -> None:
    with pytest.raises(ValidationError):
        normalize_draft_format(raw)


def test_a_null_column_projects_to_snake_with_no_settings_keys() -> None:
    assert session_format_from_tournament(None, 4) == (DraftFormat.SNAKE, {})


def test_linear_contributes_no_settings_keys_either() -> None:
    # Exactly what the wizard used to send: the keys are meaningless here, and
    # writing them would make the session look custom-configured.
    assert session_format_from_tournament({"format": "linear"}, 4) == (DraftFormat.LINEAR, {})


def test_custom_rules_are_padded_with_linear_to_the_round_count() -> None:
    fmt, settings = session_format_from_tournament(_CUSTOM, 4)

    assert fmt is DraftFormat.CUSTOM
    assert settings == {
        "round_rules": ["reverse", "weakest_first", "linear", "linear"],
        "avg_tie_seed_reverse": True,
    }


def test_custom_rules_are_truncated_to_the_round_count() -> None:
    _, settings = session_format_from_tournament(
        {"format": "custom", "round_rules": ["reverse", "weakest_first", "team_avg_asc"]}, 2
    )

    assert settings == {"round_rules": ["reverse", "weakest_first"], "avg_tie_seed_reverse": False}


def test_the_projection_emits_plain_strings_for_settings_json() -> None:
    # settings_json is read back as JSON by `round_seat_order`, which compares
    # against rule strings -- an enum member here would survive in-process and
    # break after a round trip.
    _, settings = session_format_from_tournament(_CUSTOM, 2)

    assert [type(rule) for rule in settings["round_rules"]] == [str, str]


def test_settings_model_defaults_to_snake() -> None:
    settings = DraftFormatSettings()

    assert (settings.format, settings.round_rules, settings.avg_tie_seed_reverse) == (DraftFormat.SNAKE, [], False)
