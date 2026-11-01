"""Native match wire declarations (P7 §6.1/6.4): N participants, nullable source team, grains and JSON round-trip."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.schemas.match import (
    MatchEventsRead,
    MatchParticipantRead,
    MatchRead,
    NativeFact,
    NativeMatchStatistics,
)

NOW = datetime(2026, 5, 1, tzinfo=UTC)


def _participant(team_id: int, slot: int, source_position: int, source: int | None, **facts: float) -> dict:
    return {
        "encounter_team_id": team_id,
        "slot": slot,
        "source_position": source_position,
        "tournament_team_id": source,
        "name": f"Team {team_id}",
        "result": None if team_id == 12 else {"score": team_id, "placement": None, "starting_side": None},
        "team_facts": facts,
    }


def _entity(entity_id: int) -> dict:
    return {
        "id": entity_id,
        "created_at": NOW,
        "updated_at": None,
        "discipline": "overwatch",
        "kind": "character",
        "slug": f"e{entity_id}",
        "name": f"E{entity_id}",
        "image_path": None,
        "parent_id": None,
        "attrs": {},
        "aliases": [],
        "active": True,
    }


def _match() -> dict:
    """A header with its statistics document: tournament-service serves them as one ``MatchReadWithStats``."""
    return {
        "id": 5,
        "created_at": NOW,
        "updated_at": None,
        "played_at": None,
        "workspace_id": 1,
        "discipline": "overwatch",
        "encounter_id": 9,
        "encounter_game_id": None,
        "map_index": None,
        "map_id": 3,
        "duration_s": 612.5,
        "log_name": None,
        "raw_status": None,
        "raw_available": False,
        # Three participants, source order reversed against slots, one without a source team and without a result.
        "participants": [
            _participant(10, 1, 3, 100, score=2.0),
            _participant(11, 2, 1, 101),
            _participant(12, 3, 2, None),
        ],
        "statistics": {
            "members": [
                {
                    "encounter_team_id": 12,
                    "workspace_member_id": 7,
                    "player_id": 3,
                    "display": {"name": "Event", "tag": "#1", "canonical": "Canonical Name", "snapshot": None},
                    "handle_snapshot": "Event#1",
                    "observed_role": None,
                }
            ],
            "segments": [{"segment": 1, "kind": "round", "attrs": {}}],
            "facts": [
                {
                    "encounter_team_id": 10,
                    "workspace_member_id": None,
                    "entity_id": None,
                    "segment": 0,
                    "stat_code": "score",
                    "value": 2,
                }
            ],
            "entities": [_entity(1)],
        },
    }


def test_wire_round_trip_keeps_null_source_missing_facts_and_played_at() -> None:
    document = _match()
    wire = MatchRead.model_validate(document).model_dump(mode="json")
    wire["statistics"] = NativeMatchStatistics.model_validate(document["statistics"]).model_dump(mode="json")
    assert [p["tournament_team_id"] for p in wire["participants"]] == [100, 101, None]
    assert [p["source_position"] for p in wire["participants"]] == [3, 1, 2]
    assert wire["participants"][2]["result"] is None
    # An unobserved fact is an absent key, never zero; ``played_at`` stays null rather than inferred.
    assert wire["participants"][1]["team_facts"] == {}
    assert wire["played_at"] is None and wire["duration_s"] == 612.5
    assert wire["statistics"]["members"][0]["workspace_member_id"] == 7
    assert wire["statistics"]["members"][0]["display"]["canonical"] == "Canonical Name"
    assert "player_name" not in wire["statistics"]["members"][0]
    assert "home_participation" not in wire and "rounds" not in wire and "score" not in wire


def test_fact_grains_are_nullable_and_unspecified_ones_are_rejected() -> None:
    team_fact = NativeFact(
        encounter_team_id=1, workspace_member_id=None, entity_id=None, segment=0, stat_code="score", value=3
    )
    assert (team_fact.workspace_member_id, team_fact.entity_id) == (None, None)
    with pytest.raises(ValidationError):
        NativeFact.model_validate({"encounter_team_id": 1, "segment": 0, "stat_code": "score", "value": 3})


def test_a_match_without_a_participant_array_is_invalid() -> None:
    wire = _match()
    del wire["participants"]
    with pytest.raises(ValidationError):
        MatchRead.model_validate(wire)
    with pytest.raises(ValidationError):
        MatchParticipantRead.model_validate({**_participant(1, 1, 1, None), "slot": None})


def test_statistics_and_events_are_discipline_scoped_documents() -> None:
    stats = NativeMatchStatistics(members=[], segments=[], facts=[], entities=[_entity(2)])
    assert stats.entities[0].discipline == "overwatch"
    events = MatchEventsRead.model_validate(
        {
            "match_id": 5,
            "discipline": "overwatch",
            "events": [
                {
                    "id": 1,
                    "segment": 1,
                    "t": 12.5,
                    "type": "kill",
                    "actor_member_id": None,
                    "actor_team_id": 10,
                    "target_member_id": 7,
                    "target_team_id": 12,
                    "entity_id": None,
                    "related_entity_id": None,
                    "data": None,
                }
            ],
            "entities": [],
        }
    )
    assert (events.events[0].actor_member_id, events.events[0].data) == (None, None)
