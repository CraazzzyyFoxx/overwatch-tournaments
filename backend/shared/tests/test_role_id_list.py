"""``exclude_role_id`` accepts repeated params and a comma-separated value."""

from shared.rpc.query import parse_id_list


def test_parse_id_list_accepts_repeated_and_comma_separated() -> None:
    assert parse_id_list(["3", "9"]) == [3, 9]
    assert parse_id_list(["3,9"]) == [3, 9]
    assert parse_id_list(["3, 9", "3"]) == [3, 9]
    assert parse_id_list(None) == []
    assert parse_id_list("") == []


def test_parse_id_list_rejects_non_integers() -> None:
    try:
        parse_id_list(["nope"])
    except ValueError:
        return
    raise AssertionError("expected ValueError")
