"""Public participants list visibility contract for ``_reg_to_read``.

The roster renders a column per question the organizer chose to ask, so every
PUBLIC answer has to survive serialization for an anonymous caller — smurf tags
(declared alternate battle tags, the anti-smurf transparency the roster exists
for), the participant-facing notes, and the organizer's own custom questions.

The rule is now the schema's, not this module's: ``_reg_to_read`` filters the
flat ``answers`` document to the ``public_keys`` its caller resolved from the
version the registration answered. ``public_keys=None`` is the organizer context
(and the registrant reading their own row) and filters nothing.
"""

from datetime import datetime
from types import SimpleNamespace

# Importing the read model instantiates the service Settings(); this file used
# to rely on whichever sibling test module happened to be collected first.
from shared.core.enums import HeroClass  # noqa: E402
from shared.domain.roster import PlayerRoster, RosterRole  # noqa: E402
from src.schemas.registration_build import _reg_to_read  # noqa: E402

#: What a form that asks the four public questions publishes. ``organizer_notes``
#: is fixed-visibility ``organizers`` in the builtin catalog, and ``staff_note``
#: stands for an organizer-only CUSTOM question.
PUBLIC_KEYS = frozenset({"battle_tag", "smurf_tags", "stream_pov", "public_notes", "roles", "vk"})


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
        identities=[
            SimpleNamespace(provider="discord", handle="player"),
            SimpleNamespace(provider="twitch", handle="player_tv"),
        ],
        stream_pov=False,
        roles=[],
        public_notes="anything you'd like organizers to know",
        organizer_notes="please seed me low",
        custom_fields_json={"vk": "vk.com/player", "staff_note": "watch this one"},
        form_version_id=9,
        status="approved",
        balancer_status="ready",
        checked_in=False,
        submitted_at=datetime(2026, 1, 1),
        reviewed_at=None,
    )


def test_the_roster_read_carries_every_public_answer_it_renders():
    read = _reg_to_read(_reg_stub(), workspace_id=1, public_keys=PUBLIC_KEYS)

    # Anti-smurf transparency data (the roster's whole point).
    assert read.answers["smurf_tags"] == ["Alt#1111", "Alt#2222"]
    # Notes are a roster column.
    assert read.answers["public_notes"] == "anything you'd like organizers to know"
    # The custom columns are built from the form's definitions, so their
    # answers have to arrive or the header lies.
    assert read.answers["vk"] == "vk.com/player"
    # The BattleTag stays top-level: every surface renders it.
    assert read.battle_tag == "Player#1234"
    # Balancer progress is public: the roster shows it and the registrant's
    # own card renders the balancing step from it.
    assert read.balancer_status == "ready"
    assert read.balancer_status_meta is not None


def test_an_anonymous_read_drops_the_answers_the_organizer_kept_to_themselves():
    read = _reg_to_read(_reg_stub(), workspace_id=1, public_keys=PUBLIC_KEYS)

    assert "organizer_notes" not in read.answers
    assert "staff_note" not in read.answers
    # An identity question this form does not publish is not published either.
    assert "identity_discord" not in read.answers


def test_no_public_key_set_is_the_organizer_context_and_filters_nothing():
    read = _reg_to_read(_reg_stub(), workspace_id=1)

    assert read.answers["organizer_notes"] == "please seed me low"
    assert read.answers["staff_note"] == "watch this one"
    assert read.answers["identity_discord"] == "player"
    assert read.answers["identity_twitch"] == "player_tv"


def test_a_registration_answered_against_an_older_version_reads_stale():
    stale = _reg_to_read(_reg_stub(), workspace_id=1, current_version_id=11)
    current = _reg_to_read(_reg_stub(), workspace_id=1, current_version_id=9)

    assert (stale.form_version_id, stale.form_version_stale) == (9, True)
    assert current.form_version_stale is False
    # An unknown current version is never reported as stale: the read simply
    # does not know, and a false badge would nag every reader forever.
    assert _reg_to_read(_reg_stub(), workspace_id=1).form_version_stale is False


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

    assert [(role.role, role.rank_value) for role in read.roles] == [("tank", 3200), ("damage", None)]


def test_read_payload_includes_profile_visibility():
    read = _reg_to_read(_reg_stub(), workspace_id=1, profiles_open=True)

    assert read.profiles_open is True
