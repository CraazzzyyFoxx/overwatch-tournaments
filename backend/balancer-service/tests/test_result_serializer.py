from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.domain.roster_shape import DEFAULT_ROSTER_SHAPE  # noqa: E402
from src.domain.balancer.entities import Team  # noqa: E402
from src.domain.balancer.result_serializer import lobby_document, seat_rating, teams_to_json  # noqa: E402
from tests.factories import DEFAULT_MASK as MASK  # noqa: E402
from tests.factories import make_player  # noqa: E402


def test_response_is_keyed_by_the_mask_slot_codes() -> None:
    # The mask is the tournament's resolved roster shape, so every role-keyed
    # field of the response speaks its slot codes -- not the HeroClass display
    # names a pre-roster-shape run emitted. Clients keyed by the display names
    # must translate; this pins which spelling they translate from.
    mask = DEFAULT_ROSTER_SHAPE.slots
    player = make_player("1", {"tank": 3000, "damage": 2900}, ["tank", "damage"], mask=mask)
    team = Team(1, mask)
    team.add_player("tank", player)

    team_data = teams_to_json([team], mask)["teams"][0]

    assert set(team_data["roster"]) == {"tank", "damage", "support"}
    serialized = team_data["roster"]["tank"][0]
    assert serialized["role_preferences"] == ["tank", "damage"]
    assert set(serialized["all_ratings"]) == {"tank", "damage"}
    assert set(serialized["all_discomforts"]) == {"tank", "damage", "support"}


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


def test_lobby_document_rebuilds_every_seat_the_payloads_carried() -> None:
    # Two options of one lobby seat the same players in different roles: every
    # seat the solver emitted must come back from the players map alone.
    ana = make_player("1", {"Tank": 3000, "Damage": 2500})
    ana.subclasses = {"Damage": "hitscan"}
    bob = make_player("2", {"Tank": 2800, "Damage": 2900})
    cid = make_player("3", {"Support": 2600})
    first, second = Team(1, MASK), Team(1, MASK)
    for team, seating in ((first, (("Tank", ana), ("Damage", bob))), (second, (("Damage", ana), ("Tank", bob)))):
        for role, player in (*seating, ("Support", cid)):
            team.add_player(role, player)
    benched = make_player("4", {"Support": 2400})
    payloads = [teams_to_json([team], MASK, benched_players=[benched]) for team in (first, second)]
    for payload in payloads:
        payload["statistics"]["feasibility"] = {"structural_min_off_role": 1}

    document = lobby_document(payloads)

    players = document["players"]
    assert set(players) == {"1", "2", "3", "4"}
    assert document["feasibility"] == {"structural_min_off_role": 1}
    for payload, option in zip(payloads, document["variants"], strict=True):
        assert "feasibility" not in option["statistics"]
        assert option["benched"] == ["4"]
        emitted = {
            (seat["uuid"], bucket, seat["assigned_rating"], seat["sub_role"])
            for bucket, seats in payload["teams"][0]["roster"].items()
            for seat in seats
        }
        rebuilt = {
            (uuid, bucket, seat_rating(players[uuid], bucket), players[uuid].get("sub_roles", {}).get(bucket))
            for bucket, uuids in option["teams"][0]["roster"].items()
            for uuid in uuids
        }
        assert rebuilt == emitted
