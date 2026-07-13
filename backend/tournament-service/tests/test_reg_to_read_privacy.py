"""Public participants list privacy contract for ``_reg_to_read``.

Smurf tags are declared alternate battle tags (anti-smurf transparency, same
class as the public ``battle_tag``) and must stay visible on the anonymous
participants roster. Free-text notes and organizer custom fields are admin/self
only and must be stripped when ``include_private=False``.
"""

from datetime import datetime
from types import SimpleNamespace

from src.schemas.registration_build import _reg_to_read


def _reg_stub() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        tournament_id=78,
        workspace_member=SimpleNamespace(player_id=42),
        battle_tag="Player#1234",
        smurf_tags_json=["Alt#1111", "Alt#2222"],
        discord_nick="player",
        twitch_nick="player_tv",
        stream_pov=False,
        roles=[],
        notes="private note with PII",
        custom_fields_json={"phone": "555-1234"},
        status="approved",
        checked_in=False,
        submitted_at=datetime(2026, 1, 1),
        reviewed_at=None,
    )


def test_public_list_keeps_smurf_tags_strips_notes_and_custom_fields():
    read = _reg_to_read(_reg_stub(), workspace_id=1, include_private=False)

    # Anti-smurf transparency data stays public (the roster's whole point).
    assert read.smurf_tags_json == ["Alt#1111", "Alt#2222"]
    # Genuinely private fields are stripped for anonymous viewers.
    assert read.notes is None
    assert read.custom_fields_json is None


def test_private_context_keeps_everything():
    read = _reg_to_read(_reg_stub(), workspace_id=1, include_private=True)

    assert read.smurf_tags_json == ["Alt#1111", "Alt#2222"]
    assert read.notes == "private note with PII"
    assert read.custom_fields_json == {"phone": "555-1234"}
