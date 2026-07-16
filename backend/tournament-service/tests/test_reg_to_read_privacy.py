"""Public participants list privacy contract for ``_reg_to_read``.

Smurf tags are declared alternate battle tags (anti-smurf transparency, same
class as the public ``battle_tag``) and must stay visible on the anonymous
participants roster. Free-text notes are a participant-facing form field
rendered as a roster column, so they stay public too. Organizer custom fields
remain admin/self only and must be stripped when ``include_private=False``.
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
        notes="anything you'd like organizers to know",
        custom_fields_json={"phone": "555-1234"},
        status="approved",
        balancer_status="ready",
        checked_in=False,
        submitted_at=datetime(2026, 1, 1),
        reviewed_at=None,
    )


def test_public_list_keeps_smurf_tags_and_notes_strips_custom_fields():
    read = _reg_to_read(_reg_stub(), workspace_id=1, include_private=False)

    # Anti-smurf transparency data stays public (the roster's whole point).
    assert read.smurf_tags_json == ["Alt#1111", "Alt#2222"]
    # Notes are a roster column — public even for anonymous viewers.
    assert read.notes == "anything you'd like organizers to know"
    # Organizer custom fields are genuinely private and stay stripped.
    assert read.custom_fields_json is None
    # Balancer progress is public: the roster shows it and the registrant's
    # own card renders the balancing step from it.
    assert read.balancer_status == "ready"
    assert read.balancer_status_meta is not None


def test_private_context_keeps_everything():
    read = _reg_to_read(_reg_stub(), workspace_id=1, include_private=True)

    assert read.smurf_tags_json == ["Alt#1111", "Alt#2222"]
    assert read.notes == "anything you'd like organizers to know"
    assert read.custom_fields_json == {"phone": "555-1234"}


def test_private_read_payload_includes_profile_visibility():
    read = _reg_to_read(
        _reg_stub(),
        workspace_id=1,
        include_private=True,
        profiles_open=True,
    )

    assert read.profiles_open is True
