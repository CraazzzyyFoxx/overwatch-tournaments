from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.domain.balancer.result_serializer import lobby_document  # noqa: E402
from src.domain.mix_lobbies import seated_member_ids, seated_teams  # noqa: E402


def _payload(*teams: dict[str, list[int]]) -> dict[str, object]:
    """One solver option: a role bucket per team, each holding member ids."""
    return {
        "teams": [
            {"roster": {role: [{"uuid": str(member_id)} for member_id in ids] for role, ids in team.items()}}
            for team in teams
        ]
    }


def test_membership_is_every_seat_of_the_named_option() -> None:
    document = lobby_document([_payload({"tank": [7], "damage": [8, 9]}, {"tank": [10], "damage": [11, 12]})])
    assert seated_member_ids(document, 0) == frozenset({7, 8, 9, 10, 11, 12})


def test_each_option_seats_its_own_lobby() -> None:
    # The pager decides who is playing: two options of one run can seat
    # different people, so the index is not decoration.
    document = lobby_document([_payload({"tank": [7]}), _payload({"tank": [8]})])
    assert seated_member_ids(document, 0) == frozenset({7})
    assert seated_member_ids(document, 1) == frozenset({8})


def test_a_lobby_nobody_balanced_seats_nobody() -> None:
    assert seated_member_ids(None, 0) == frozenset()


def test_an_index_past_the_stored_options_seats_nobody() -> None:
    # A mix re-balanced into fewer options leaves a stale pager behind; that
    # reads as "nobody is playing this lobby", not as a crash.
    document = lobby_document([_payload({"tank": [7]})])
    assert seated_member_ids(document, 1) == frozenset()
    assert seated_member_ids(document, -1) == frozenset()


def test_a_document_stored_before_the_lobby_form_still_answers() -> None:
    # Mixes balanced before ``lobby_document`` hold the raw solver payloads;
    # they are upgraded on read, so membership answers for them too.
    assert seated_member_ids({"variants": [_payload({"tank": [7], "damage": [8]})]}, 0) == frozenset({7, 8})


def test_a_seat_that_is_not_a_member_id_is_skipped_not_fatal() -> None:
    # A bench entry from an older document can carry a non-numeric uuid; the
    # read degrades to "not a member of this lobby" instead of failing the call.
    document = lobby_document([_payload({"tank": [7]})])
    document["variants"][0]["teams"][0]["roster"]["damage"] = ["not-a-member"]
    assert seated_member_ids(document, 0) == frozenset({7})


def test_teams_keep_their_order_so_each_one_gets_its_own_voice() -> None:
    # The voice mover needs team 1 and team 2 apart, not the union membership is.
    document = lobby_document([_payload({"tank": [7], "damage": [8]}, {"tank": [9]})])
    assert seated_teams(document, 0) == ((7, 8), (9,))


def test_teams_of_an_index_past_the_stored_options_are_empty() -> None:
    assert seated_teams(lobby_document([_payload({"tank": [7]})]), 1) == ()
    assert seated_teams(None, 0) == ()


def test_a_seat_that_is_not_a_member_id_is_left_out_of_its_team() -> None:
    document = lobby_document([_payload({"tank": [7]})])
    document["variants"][0]["teams"][0]["roster"]["damage"] = ["not-a-member"]
    assert seated_teams(document, 0) == ((7,),)
