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

from src.domain.mix_discord import build_lineup_embed  # noqa: E402


def _seat(name: str, rating: int, uuid: str = "1") -> dict:
    return {"uuid": uuid, "name": name, "assigned_rating": rating}


def _variant(*rosters: dict) -> dict:
    return {"teams": [{"roster": roster} for roster in rosters]}


def _embed(variant: dict | None = None, **overrides) -> dict:
    kwargs = {
        "mix_name": "Friday Scrim",
        "match_number": 1,
        "variant": variant if variant is not None else _variant(),
        "team_names": {},
        "next_map": None,
        "points_per_win": None,
    }
    kwargs.update(overrides)
    return build_lineup_embed(**kwargs)


def test_title_names_the_mix_and_the_match_about_to_be_played() -> None:
    embed = _embed(match_number=4)
    assert embed["title"] == "Friday Scrim — Match 4"
    assert embed["color"] == 0x14B8A6


def test_description_carries_the_map_and_its_gamemode() -> None:
    assert _embed(next_map=("Busan", "Control"))["description"] == "Map: Busan · Control"


def test_description_omits_a_gamemode_the_map_has_no_name_for() -> None:
    assert _embed(next_map=("Busan", None))["description"] == "Map: Busan"


def test_description_says_so_before_anyone_rolled() -> None:
    """Posting the lineup before the roll is normal, not an empty line."""
    assert _embed(next_map=None)["description"] == "Map: not rolled yet"


def test_one_inline_field_per_team_named_by_the_override_or_its_number() -> None:
    variant = _variant(
        {"Tank": [_seat("Ana", 3000)]},
        {"Tank": [_seat("Bob", 2900)]},
        {"Tank": [_seat("Cid", 2800)]},
    )
    fields = _embed(variant, team_names={1: "Blue"})["fields"]

    assert [field["name"] for field in fields] == ["Team 1", "Blue", "Team 3"]
    assert all(field["inline"] is True for field in fields)


def test_seat_lines_follow_the_roster_buckets_with_human_role_labels() -> None:
    variant = _variant(
        {
            "Tank": [_seat("Ana", 3000)],
            "Damage": [_seat("Bob", 2900), _seat("Cid", 2800)],
            "Support": [_seat("Dee", 2700)],
        }
    )
    value = _embed(variant)["fields"][0]["value"]

    assert value.splitlines() == [
        "Tank · Ana · 3000",
        "DPS · Bob · 2900",
        "DPS · Cid · 2800",
        "Support · Dee · 2700",
    ]


def test_an_unrecognised_bucket_keeps_its_own_key_as_the_label() -> None:
    value = _embed(_variant({"Goalie": [_seat("Ana", 3000)]}))["fields"][0]["value"]
    assert value == "Goalie · Ana · 3000"


def test_footer_only_appears_when_the_mix_plays_for_points() -> None:
    assert "footer" not in _embed()
    assert _embed(points_per_win=25)["footer"] == {"text": "Points per win: 25"}


def test_a_lineup_past_the_field_limit_is_cut_short_with_a_marker() -> None:
    """Discord rejects a field value over 1024 characters outright."""
    seats = [_seat(f"Player {index:02d}", 2500 + index, uuid=str(index)) for index in range(60)]
    value = _embed(_variant({"Tank": seats}))["fields"][0]["value"]

    assert len(value) <= 1024
    assert value.endswith("\n…")
    lines = value.splitlines()
    assert lines[0] == "Tank · Player 00 · 2500"
    # Cut, not squeezed: the lines that survive are unchanged whole lines.
    assert all(line.startswith("Tank · Player ") for line in lines[:-1])
    assert len(lines) < 61
