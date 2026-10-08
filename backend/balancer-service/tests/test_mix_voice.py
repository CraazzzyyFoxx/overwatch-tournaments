from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.domain.mix_voice import (  # noqa: E402
    LobbyVoice,
    MixVoiceConfig,
    VoicePlan,
    plan_move,
    report,
    snowflake,
    voice_config_from,
)
from src.schemas.custom_game import CustomGameVoicePatch  # noqa: E402

CONFIG = MixVoiceConfig("5", "10", frozenset({"1"}))


def test_voice_settings_come_out_of_the_workspace_blob() -> None:
    # JSON has one number type, so a general voice may arrive as either; both
    # end up as the digit string the wire and Discord speak.
    config = voice_config_from({"mix_voice_category_id": "10", "mix_general_voice_channel_ids": ["1", 2]}, "5")
    assert config == MixVoiceConfig("5", "10", frozenset({"1", "2"}))


def test_a_workspace_that_configured_nothing_has_no_voices() -> None:
    assert voice_config_from(None, "5") == MixVoiceConfig("5", None, frozenset())
    assert voice_config_from({"mix_discord_channel_id": "555"}, "5") == MixVoiceConfig("5", None, frozenset())
    # A blob whose general list is not a list is as good as unset -- the move
    # refuses rather than guessing a channel out of a malformed setting.
    assert voice_config_from({"mix_general_voice_channel_ids": "1"}, "5") == MixVoiceConfig("5", None, frozenset())


def test_no_guild_is_none_rather_than_an_empty_string() -> None:
    assert voice_config_from({}, "").guild_id is None


def test_snowflakes_travel_as_digit_strings() -> None:
    assert snowflake(None) is None
    assert snowflake(12) == "12"


def test_voice_patch_takes_a_general_voice_and_a_lobbys_two_rooms() -> None:
    patch = CustomGameVoicePatch.model_validate(
        {
            "general_voice_channel_id": "555",
            "lobbies": [{"lobby_index": 1, "team1_voice_channel_id": "1", "team2_voice_channel_id": "2"}],
        }
    )
    assert patch.general_voice_channel_id == "555"
    assert (patch.lobbies[0].team1_voice_channel_id, patch.lobbies[0].team2_voice_channel_id) == ("1", "2")


def test_voice_patch_refuses_one_room_for_both_teams() -> None:
    # Both teams in one voice is not a layout, it is the move doing nothing.
    with pytest.raises(ValidationError):
        CustomGameVoicePatch.model_validate(
            {"lobbies": [{"team1_voice_channel_id": "1", "team2_voice_channel_id": "1"}]}
        )


def test_voice_patch_refuses_the_same_lobby_twice() -> None:
    with pytest.raises(ValidationError):
        CustomGameVoicePatch.model_validate(
            {"lobbies": [{"lobby_index": 0}, {"lobby_index": 0, "team1_voice_channel_id": "1"}]}
        )


def test_voice_patch_refuses_a_channel_id_that_is_not_a_snowflake() -> None:
    with pytest.raises(ValidationError):
        CustomGameVoicePatch.model_validate({"general_voice_channel_id": "general"})


def test_seated_players_with_links_are_planned_into_their_team_voice() -> None:
    lobby = LobbyVoice(0, ((7, 8), (9,)), ("2", "3"))
    plan = plan_move(CONFIG, [lobby], {7: "70", 8: "80", 9: "90"})
    assert plan.moves == [
        {"discord_user_id": "70", "channel_id": "2"},
        {"discord_user_id": "80", "channel_id": "2"},
        {"discord_user_id": "90", "channel_id": "3"},
    ]
    assert plan.rows == []


def test_unlinked_unconfigured_and_general_targets_are_reported_not_moved() -> None:
    lobby = LobbyVoice(0, ((7, 8), (9,)), ("1", None))
    plan = plan_move(CONFIG, [lobby], {7: "70"})
    assert plan.moves == []
    assert [(r["workspace_member_id"], r["status"]) for r in plan.rows] == [
        (7, "channel_outside_category"),
        (8, "channel_outside_category"),
        (9, "not_configured"),
    ]


def test_report_names_members_and_counts_moves() -> None:
    plan = plan_move(CONFIG, [LobbyVoice(0, ((7,), (8,)), ("2", "3"))], {7: "70"})
    body = report(
        plan,
        [{"discord_user_id": "70", "channel_id": "2", "status": "moved", "name": "ana#1"}],
        {7: "Ana", 8: "Bob"},
    )
    assert body == {
        "moved": 1,
        "results": [
            {"workspace_member_id": 8, "name": "Bob", "status": "no_discord_link", "channel_id": "3"},
            {"workspace_member_id": 7, "name": "Ana", "status": "moved", "channel_id": "2"},
        ],
    }


def test_report_of_a_drain_names_people_by_their_discord_name() -> None:
    body = report(
        VoicePlan([], [], {}),
        [{"discord_user_id": "70", "channel_id": "1", "status": "moved", "name": "spectator"}],
        {},
    )
    assert body["results"] == [{"workspace_member_id": None, "name": "spectator", "status": "moved", "channel_id": "1"}]
