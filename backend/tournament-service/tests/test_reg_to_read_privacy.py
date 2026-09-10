"""Public participants list visibility contract for ``_reg_to_read``.

The roster renders a column per built-in field and per organizer-defined custom
field, so every one of them has to survive serialization for an anonymous
caller. Smurf tags are declared alternate battle tags (anti-smurf transparency,
same class as the public ``battle_tag``); free-text notes are a
participant-facing form field; custom fields are questions the organizer chose
to ask on a public sign-up form.

``custom_fields_json`` used to be stripped behind an ``include_private`` flag,
which left every custom column on the roster permanently empty under a header
that advertised it. The flag is gone -- one read model, one visibility rule.
"""

from datetime import datetime
from types import SimpleNamespace

# Importing the read model instantiates the service Settings(); this file used
# to rely on whichever sibling test module happened to be collected first.
from shared.core.enums import HeroClass  # noqa: E402
from shared.domain.roster import PlayerRoster, RosterRole  # noqa: E402
from src.schemas.registration_build import _reg_to_read  # noqa: E402


def _roster(rank: int | None, source: str = "registration", *extra: RosterRole) -> PlayerRoster:
    """A one-role roster plus any ``extra`` entries, as the engine hands it over."""
    return PlayerRoster(
        registration_id=1,
        battle_tag="Player#1234",
        display_name=None,
        player_id=42,
        auth_user_id=None,
        workspace_member_id=None,
        roles=(
            RosterRole(
                role=HeroClass.tank,
                rank=rank,
                source=source if rank is not None else "none",
                is_primary=True,
                priority=0,
                subrole=None,
            ),
            *extra,
        ),
        is_full_flex=False,
    )


def _reg_stub() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        tournament_id=78,
        workspace_member=SimpleNamespace(player_id=42),
        battle_tag="Player#1234",
        smurf_tags_json=["Alt#1111", "Alt#2222"],
        discord_nick="player",
        twitch_nick="player_tv",
        boosty_nick="player_boosty",
        stream_pov=False,
        roles=[],
        notes="anything you'd like organizers to know",
        custom_fields_json={"vk": "vk.com/player"},
        status="approved",
        balancer_status="ready",
        checked_in=False,
        submitted_at=datetime(2026, 1, 1),
        reviewed_at=None,
    )


def test_the_roster_read_carries_every_column_it_renders():
    read = _reg_to_read(_reg_stub(), workspace_id=1)

    # Anti-smurf transparency data (the roster's whole point).
    assert read.smurf_tags_json == ["Alt#1111", "Alt#2222"]
    # Notes are a roster column.
    assert read.notes == "anything you'd like organizers to know"
    # The custom columns are built from the form's definitions, so their
    # answers have to arrive or the header lies.
    assert read.custom_fields_json == {"vk": "vk.com/player"}
    # Every identity handle the form collects gets its own column.
    assert read.discord_nick == "player"
    assert read.twitch_nick == "player_tv"
    assert read.boosty_nick == "player_boosty"
    # Balancer progress is public: the roster shows it and the registrant's
    # own card renders the balancing step from it.
    assert read.balancer_status == "ready"
    assert read.balancer_status_meta is not None


def test_ranks_stay_hidden_unless_the_form_publishes_them():
    stub = _reg_stub()
    stub.roles = [
        SimpleNamespace(role="tank", subrole=None, is_primary=True, priority=0, rank_value=3200, hero_entries=[])
    ]

    hidden = _reg_to_read(stub, workspace_id=1, roster=_roster(3200))
    shown = _reg_to_read(stub, workspace_id=1, show_ranks=True, roster=_roster(3200))

    assert hidden.roles[0].rank_value is None
    assert shown.roles[0].rank_value == 3200


def test_follow_reg_uses_inherited_workspace_rank():
    stub = _reg_stub()
    stub.roles = [
        SimpleNamespace(role="tank", subrole=None, is_primary=True, priority=0, rank_value=None, hero_entries=[])
    ]

    read = _reg_to_read(stub, workspace_id=1, show_ranks=True, roster=_roster(3200, "workspace"))

    assert read.roles[0].rank_value == 3200


def test_public_roles_come_from_the_roster_not_the_rows():
    """``all_roles``/``forced`` synthesize roles no DB row carries, so the public
    table reads the roster -- it used to publish one role while the balancer and
    the draft acted on three. An unrated role still publishes no number: the raw
    column is never a fallback for a rating nothing else honours."""
    stub = _reg_stub()
    stub.roles = [
        SimpleNamespace(role="tank", subrole=None, is_primary=True, priority=0, rank_value=3200, hero_entries=[])
    ]
    synthesized = RosterRole(
        role=HeroClass.damage, rank=None, source="none", is_primary=False, priority=1, subrole=None
    )

    read = _reg_to_read(stub, workspace_id=1, show_ranks=True, roster=_roster(3200, "registration", synthesized))

    assert [(role.role, role.rank_value) for role in read.roles] == [("tank", 3200), ("dps", None)]


def test_read_payload_includes_profile_visibility():
    read = _reg_to_read(_reg_stub(), workspace_id=1, profiles_open=True)

    assert read.profiles_open is True
