"""Play-order helpers for user encounter / map-result assembly."""

from datetime import UTC, datetime
from types import SimpleNamespace

from shared.schemas.match import NativeFact
from src.schemas.user import UserMatchViewer
from src.services.user._mappers import (
    UserMatchStats,
    encounter_play_key,
    sort_user_matches,
    to_match_with_user_stats,
)


def _match(id_: int, map_id: int, map_index: int):
    return SimpleNamespace(id=id_, map_id=map_id, map_index=map_index)


def test_encounter_play_key_prefers_ended_at_over_id():
    earlier = SimpleNamespace(
        id=99,
        ended_at=datetime(2026, 8, 1, tzinfo=UTC),
        started_at=None,
        scheduled_at=None,
        created_at=datetime(2026, 8, 10, tzinfo=UTC),
    )
    later = SimpleNamespace(
        id=1,
        ended_at=datetime(2026, 8, 16, tzinfo=UTC),
        started_at=None,
        scheduled_at=None,
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
    )
    assert encounter_play_key(earlier) < encounter_play_key(later)


def test_encounter_play_key_uses_confirmed_at_not_insert_order():
    group = SimpleNamespace(
        id=6136,
        ended_at=None,
        confirmed_at=datetime(2026, 8, 15, 18, 0, tzinfo=UTC),
        started_at=None,
        created_at=datetime(2026, 8, 16, 10, 0, tzinfo=UTC),
    )
    playoff = SimpleNamespace(
        id=6104,
        ended_at=None,
        confirmed_at=datetime(2026, 8, 16, 18, 32, tzinfo=UTC),
        started_at=None,
        created_at=datetime(2026, 8, 14, 10, 0, tzinfo=UTC),
    )
    assert encounter_play_key(group) < encounter_play_key(playoff)


def test_sort_user_matches_uses_map_index():
    matches = [_match(3, 15, 3), _match(1, 31, 2), _match(2, 44, 1)]
    assert [m.id for m in sort_user_matches(matches)] == [2, 1, 3]


def test_sort_user_matches_keeps_repeated_maps_and_stable_position_ties():
    matches = [_match(12, 31, 3), _match(11, 31, 2), _match(10, 31, 2)]
    assert [m.id for m in sort_user_matches(matches)] == [10, 11, 12]


def test_sort_user_matches_accepts_no_observed_games():
    assert sort_user_matches([]) == []


def _participant(seat_id: int, slot: int, source_position: int, team_id: int | None, **facts: float):
    return SimpleNamespace(
        seat=SimpleNamespace(id=seat_id, slot=slot, team_id=team_id, name=f"Seat {seat_id}"),
        source_position=source_position,
        result=None,
        team_facts=facts,
    )


def test_match_mapper_uses_historical_game_context():
    stamp = datetime(2026, 5, 1, tzinfo=UTC)
    context = SimpleNamespace(
        match=SimpleNamespace(
            id=17,
            duration_s=600,
            map_entity_id=31,
            mode_entity_id=None,
            created_at=stamp,
            updated_at=None,
            played_at=None,
            workspace_id=7,
            discipline="overwatch",
            encounter_id=9,
            encounter_game_id=50,
        ),
        game=SimpleNamespace(encounter_id=9, position=2),
        encounter=SimpleNamespace(id=9),
        job=None,
        # Three participants: the log's order reversed against the seats, one without a source team.
        participants=(
            _participant(21, 1, 3, 2155, score=3.0),
            _participant(22, 2, 1, 2152, score=0.0),
            _participant(23, 3, 2, None),
        ),
        display_filename="observed-match.txt",
        mode=None,
        map=SimpleNamespace(
            id=31,
            created_at=stamp,
            updated_at=None,
            discipline="overwatch",
            kind="map",
            slug="ilios",
            name="Ilios",
            image_path=None,
            parent_id=None,
            attrs={},
            aliases=[],
            active=True,
        ),
    )
    stats = UserMatchStats(
        viewer=UserMatchViewer(encounter_team_id=21, workspace_member_id=5, facts={"impact_rank": 1.0}),
        member_totals=[
            NativeFact(
                encounter_team_id=21, workspace_member_id=5, entity_id=None, segment=0, stat_code="score", value=3.0
            )
        ],
    )
    result = to_match_with_user_stats(context, stats)
    assert [(p.encounter_team_id, p.tournament_team_id) for p in result.participants] == [
        (21, 2155),
        (22, 2152),
        (23, None),
    ]
    # An observed zero is a fact and a missing score is none; neither is invented.
    assert [p.team_facts for p in result.participants] == [{"score": 3.0}, {"score": 0.0}, {}]
    assert [p.source_position for p in result.participants] == [3, 1, 2]
    assert (result.encounter_id, result.map_index, result.duration_s) == (9, 2, 600)
    assert result.log_name == "observed-match.txt"
    assert result.map.name == "Ilios"
    assert (result.viewer.workspace_member_id, result.viewer.facts) == (5, {"impact_rank": 1.0})
    assert [(f.stat_code, f.value) for f in result.member_totals] == [("score", 3.0)]
    assert {"code", "score", "home_team_id", "impact_rank", "heroes"}.isdisjoint(result.model_dump())
    assert to_match_with_user_stats(context).viewer is None
