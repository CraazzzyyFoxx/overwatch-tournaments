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
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

from src.services.balancer.algorithm.entities import Player, Team  # noqa: E402
from src.services.balancer.algorithm.result_serializer import teams_to_json  # noqa: E402

MASK = {"Tank": 1, "Damage": 2, "Support": 2}


def make_player(uuid: str, ratings: dict[str, int], preferences: list[str]) -> Player:
    return Player(name=f"P{uuid}", ratings=ratings, preferences=preferences, uuid=uuid, mask=MASK)


def test_roster_player_exposes_all_discomforts_snapshot() -> None:
    player = make_player("1", {"Tank": 3000, "Damage": 2900}, ["Tank", "Damage"])
    team = Team(1, MASK)
    team.add_player("Tank", player)

    result = teams_to_json([team], MASK)
    serialized = result["teams"][0]["roster"]["Tank"][0]

    # Snapshot mirrors Player.discomfort_map: primary role 0, second pref 100,
    # an unplayable masked role 5000.
    assert serialized["all_discomforts"] == {"Tank": 0, "Damage": 100, "Support": 5000}
    assert serialized["all_discomforts"] == player.discomfort_map


def test_benched_player_exposes_all_discomforts() -> None:
    placed = make_player("1", {"Tank": 3000}, ["Tank"])
    benched = make_player("2", {"Damage": 2800, "Support": 2700}, ["Damage", "Support"])
    team = Team(1, MASK)
    team.add_player("Tank", placed)

    result = teams_to_json([team], MASK, benched_players=[benched])
    assert result["benched_players"][0]["all_discomforts"] == benched.discomfort_map
