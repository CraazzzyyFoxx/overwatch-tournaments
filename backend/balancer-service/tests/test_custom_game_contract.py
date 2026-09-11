from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from shared.core import enums  # noqa: E402


def _schemas():
    try:
        from src.schemas import custom_game
    except ImportError as exc:
        pytest.fail(f"custom-game schemas are missing: {exc}")
    return custom_game


def test_player_patch_accepts_one_participation_enum() -> None:
    patch = _schemas().CustomGamePlayerPatch.model_validate({"participation": "benched"})
    assert patch.participation is enums.MixParticipation.BENCHED
    assert patch.model_fields_set == {"participation"}


def test_player_patch_rejects_legacy_boolean_state() -> None:
    with pytest.raises(ValidationError):
        _schemas().CustomGamePlayerPatch.model_validate({"is_active": False, "must_play": True})


def test_player_patch_does_not_coerce_string_to_boolean() -> None:
    with pytest.raises(ValidationError):
        _schemas().CustomGamePlayerPatch.model_validate({"is_flex": "false"})


def test_roles_preserve_explicit_empty_and_inherited_null() -> None:
    explicit = _schemas().CustomGamePlayerPatch.model_validate({"roles": []})
    inherited = _schemas().CustomGamePlayerPatch.model_validate({"roles": None})
    assert explicit.roles == []
    assert inherited.roles is None
    assert explicit.model_fields_set == inherited.model_fields_set == {"roles"}


def test_bulk_participation_requires_unique_members() -> None:
    with pytest.raises(ValidationError):
        _schemas().CustomGamePlayersParticipationPatch.model_validate(
            {
                "players": [
                    {"workspace_member_id": 7, "participation": "pool"},
                    {"workspace_member_id": 7, "participation": "benched"},
                ]
            }
        )


def test_record_outcome_takes_the_outcome_the_client_sends() -> None:
    """The wire field is ``outcome``, and only 1/2/null are decided outcomes."""
    body = _schemas().CustomGameRecordOutcome.model_validate(
        {"outcome": {"winner": 2}, "variant_index": 0, "map_id": None}
    )
    assert body.outcome.winner == 2


def test_record_outcome_rejects_an_impossible_winner() -> None:
    with pytest.raises(ValidationError):
        _schemas().CustomGameRecordOutcome.model_validate({"outcome": {"winner": 3}, "variant_index": 0})


def test_post_discord_accepts_a_png_screenshot_and_posts_without_one() -> None:
    """The lineup image is optional: no capture means the text embed instead."""
    png = base64.b64encode(b"\x89PNG\r\n\x1a\nmatchup").decode("ascii")
    with_image = _schemas().CustomGamePostDiscord.model_validate({"variant_index": 0, "image_b64": png})
    without = _schemas().CustomGamePostDiscord.model_validate({"variant_index": 0})
    assert with_image.image_b64 == png
    assert without.image_b64 is None


def test_post_discord_rejects_a_payload_that_is_not_a_png() -> None:
    """The blob is forwarded to Discord unread, so this is the only checkpoint."""
    with pytest.raises(ValidationError):
        _schemas().CustomGamePostDiscord.model_validate(
            {"variant_index": 0, "image_b64": base64.b64encode(b"GIF89a").decode("ascii")}
        )
    with pytest.raises(ValidationError):
        _schemas().CustomGamePostDiscord.model_validate({"variant_index": 0, "image_b64": "not base64"})
