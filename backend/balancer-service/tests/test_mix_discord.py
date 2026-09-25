from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.domain.mix_discord import build_lineup_embed  # noqa: E402


def _document(*rosters: dict[str, list[tuple[str, int]]]) -> dict:
    """A stored lobby document with one option: a team per roster of ``(name, rating)`` seats."""
    players: dict[str, dict] = {}
    teams = []
    for roster in rosters:
        for bucket, seats in roster.items():
            for name, rating in seats:
                players.setdefault(name, {"name": name, "ratings": {}})["ratings"][bucket] = rating
        teams.append({"roster": {bucket: [name for name, _ in seats] for bucket, seats in roster.items()}})
    return {"players": players, "variants": [{"teams": teams}]}


def _embed(document: dict | None = None, **overrides) -> dict:
    document = document if document is not None else _document()
    kwargs = {
        "mix_name": "Friday Scrim",
        "match_number": 1,
        "variant": document["variants"][0],
        "players": document["players"],
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
    document = _document(
        {"Tank": [("Ana", 3000)]},
        {"Tank": [("Bob", 2900)]},
        {"Tank": [("Cid", 2800)]},
    )
    fields = _embed(document, team_names={1: "Blue"})["fields"]

    assert [field["name"] for field in fields] == ["Team 1", "Blue", "Team 3"]
    assert all(field["inline"] is True for field in fields)


def test_seat_lines_follow_the_roster_buckets_with_human_role_labels() -> None:
    document = _document(
        {
            "Tank": [("Ana", 3000)],
            "Damage": [("Bob", 2900), ("Cid", 2800)],
            "Support": [("Dee", 2700)],
        }
    )
    value = _embed(document)["fields"][0]["value"]

    assert value.splitlines() == [
        "Tank · Ana · 3000",
        "DPS · Bob · 2900",
        "DPS · Cid · 2800",
        "Support · Dee · 2700",
    ]


def test_an_unrecognised_bucket_keeps_its_own_key_as_the_label() -> None:
    value = _embed(_document({"Goalie": [("Ana", 3000)]}))["fields"][0]["value"]
    assert value == "Goalie · Ana · 3000"


def test_footer_only_appears_when_the_mix_plays_for_points() -> None:
    assert "footer" not in _embed()
    assert _embed(points_per_win=25)["footer"] == {"text": "Points per win: 25"}


def test_a_lineup_past_the_field_limit_is_cut_short_with_a_marker() -> None:
    """Discord rejects a field value over 1024 characters outright."""
    seats = [(f"Player {index:02d}", 2500 + index) for index in range(60)]
    value = _embed(_document({"Tank": seats}))["fields"][0]["value"]

    assert len(value) <= 1024
    assert value.endswith("\n…")
    lines = value.splitlines()
    assert lines[0] == "Tank · Player 00 · 2500"
    # Cut, not squeezed: the lines that survive are unchanged whole lines.
    assert all(line.startswith("Tank · Player ") for line in lines[:-1])
    assert len(lines) < 61
