"""RPC-handler validation tests for the user-compare surface.

Targets:
- compare            -> ``rpc.stats.users.compare``
- compare/characters -> ``rpc.stats.users.compare_characters``

Every read names its game (``discipline``). The RPC envelope surfaces the
status-derived ``error.code``:
  - HTTP 400 (flow ``invalid_filter``)                     -> envelope ``bad_request``
  - HTTP 422 (query model ``ValidationError``, stat codes) -> envelope ``unprocessable``
"""

import pytest

from tests.conftest import RpcHarness, build_query

pytestmark = pytest.mark.validation


def _query(params: dict) -> dict:
    return build_query({"discipline": "overwatch", **params})


def test_get_user_compare_target_user_missing(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.compare",
        {"id": 599, "query": _query({"baseline": "target_user"})},
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "bad_request"


def test_get_user_compare_invalid_division_range(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.compare",
        {"id": 599, "query": _query({"baseline": "cohort", "div_min": 15, "div_max": 5})},
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "bad_request"


def test_get_user_character_compare_invalid_target_user_id_returns_422(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.compare_characters",
        {"id": 599, "query": _query({"target_user_id": "not-a-number"})},
    )
    # The un-coercible value fails build_query_model -> ValidationError -> unprocessable.
    assert env["ok"] is False
    assert env["error"]["code"] == "unprocessable"


def test_get_user_character_compare_target_user_missing(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.stats.users.compare_characters",
        {"id": 599, "query": _query({"baseline": "target_user"})},
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "bad_request"


@pytest.mark.parametrize("stats", [["score"], ["eliminations", "not_a_stat"]])
def test_get_user_character_compare_undeclared_stat_returns_422(rpc: RpcHarness, stats: list[str]) -> None:
    """A team stat (``score``) or a code the game does not declare is the caller's error, never a 500."""
    env = rpc.call_sync(
        "rpc.stats.users.compare_characters",
        {"id": 599, "query": _query({"stats": stats})},
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "unprocessable"
    assert env["error"]["details"]["fields"][0]["code"] == "stat_not_declared"


def test_compare_reads_require_a_game(rpc: RpcHarness) -> None:
    for topic in ("rpc.stats.users.compare", "rpc.stats.users.compare_characters"):
        env = rpc.call_sync(topic, {"id": 599, "query": build_query({})})
        assert env["ok"] is False
        assert env["error"]["code"] == "unprocessable"
