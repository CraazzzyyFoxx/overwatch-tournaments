"""RPC-handler validation tests for the user-compare surface.

Targets:
- compare        -> ``rpc.app.users.compare``
- compare/heroes -> ``rpc.app.users.compare_heroes``

Replaces the former HTTP-client tests. The old suite asserted on the
FastAPI ``content["detail"][0]["code"]`` machine code; the RPC envelope drops
that per-item code and surfaces only the status-derived ``error.code``:
  - HTTP 400 (flow ``invalid_filter``)        -> envelope ``bad_request``
  - HTTP 422 (query model ``ValidationError``) -> envelope ``unprocessable``
"""

import pytest

from shared.core import enums
from tests.conftest import RpcHarness, build_query

pytestmark = pytest.mark.validation


def test_performance_stat_is_treated_as_ascending() -> None:
    assert enums.is_ascending_stat(enums.LogStatsName.Performance) is True


def test_get_user_compare_target_user_missing(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.app.users.compare",
        {"id": 599, "query": build_query({"baseline": "target_user"})},
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "bad_request"


def test_get_user_compare_invalid_division_range(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.app.users.compare",
        {"id": 599, "query": build_query({"baseline": "cohort", "div_min": 15, "div_max": 5})},
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "bad_request"


def test_get_user_hero_compare_invalid_target_user_id_returns_422(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.app.users.compare_heroes",
        {"id": 599, "query": build_query({"target_user_id": "not-a-number"})},
    )
    # FastAPI returned 422 for the un-coercible query param; in RPC the same
    # invalid value fails build_query_model -> ValidationError -> unprocessable.
    assert env["ok"] is False
    assert env["error"]["code"] == "unprocessable"


def test_get_user_hero_compare_target_user_missing(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.app.users.compare_heroes",
        {"id": 599, "query": build_query({"baseline": "target_user"})},
    )
    assert env["ok"] is False
    assert env["error"]["code"] == "bad_request"
