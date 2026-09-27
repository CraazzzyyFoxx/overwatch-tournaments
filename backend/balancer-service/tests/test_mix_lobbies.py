from __future__ import annotations

import sys
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from src.domain.balancer.result_serializer import lobby_document  # noqa: E402
from src.domain.mix_lobbies import seated_member_ids  # noqa: E402


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
