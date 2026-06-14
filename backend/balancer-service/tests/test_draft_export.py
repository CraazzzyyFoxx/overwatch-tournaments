from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from shared.core.enums import DraftRole  # noqa: E402
from shared.models.draft import DraftPlayer, DraftTeam  # noqa: E402
from src.services.draft.export import _draft_to_balancer_payload  # noqa: E402


def _team(tid: int, pos: int, name: str) -> DraftTeam:
    return DraftTeam(id=tid, session_id=1, draft_position=pos, name=name)


def _player(pid: int, *, captain=False, bt=None, role=DraftRole.DPS, rank=3000, sub=None, uid=None) -> DraftPlayer:
    return DraftPlayer(
        id=pid,
        session_id=1,
        is_captain=captain,
        battle_tag=bt,
        primary_role=role.value,
        rank_value=rank,
        sub_role=sub,
        user_id=uid,
    )


def test_payload_orders_by_draft_position() -> None:
    teams = [_team(1, 2, "B"), _team(2, 1, "A")]
    roster = {1: [_player(10, captain=True, bt="Bcap#1")], 2: [_player(20, captain=True, bt="Acap#1")]}
    payload = _draft_to_balancer_payload(teams, roster)
    assert [p.name for p in payload] == ["Acap#1", "Bcap#1"]  # position 1 (A) first


def test_payload_uses_captain_battle_tag_as_name() -> None:
    teams = [_team(1, 1, "Display")]
    roster = {1: [_player(10, captain=True, bt="Captain#1234"), _player(11, bt="Mate#1")]}
    payload = _draft_to_balancer_payload(teams, roster)
    assert payload[0].name == "Captain#1234"


def test_payload_falls_back_to_team_name_without_captain_tag() -> None:
    teams = [_team(1, 1, "Fallback")]
    roster = {1: [_player(10, captain=True, bt=None)]}
    payload = _draft_to_balancer_payload(teams, roster)
    assert payload[0].name == "Fallback"


def test_payload_totals_and_members() -> None:
    teams = [_team(1, 1, "T")]
    roster = {
        1: [
            _player(10, captain=True, bt="Cap#1", role=DraftRole.TANK, rank=4000),
            _player(11, bt="A#1", role=DraftRole.DPS, rank=3000),
            _player(12, bt="B#1", role=DraftRole.SUPPORT, rank=3500),
        ]
    }
    payload = _draft_to_balancer_payload(teams, roster)
    team = payload[0]
    assert team.total_sr == 10500
    assert team.avg_sr == 3500.0
    assert len(team.members) == 3
    roles = {m.name: m.role for m in team.members}
    assert roles == {"Cap#1": "tank", "A#1": "dps", "B#1": "support"}


def test_payload_empty_roster_team() -> None:
    teams = [_team(1, 1, "Empty")]
    payload = _draft_to_balancer_payload(teams, {})
    assert payload[0].total_sr == 0
    assert payload[0].avg_sr == 0.0
    assert payload[0].members == []
