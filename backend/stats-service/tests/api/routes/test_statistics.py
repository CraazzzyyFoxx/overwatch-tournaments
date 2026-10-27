"""RPC-handler tests for the statistics surface.

Targets:
- champion -> ``rpc.stats.statistics.champion``

Replaces the former HTTP-client test (``GET /statistics/champion``) against the
decommissioned HTTP service; assertions mirror the old test on the envelope
``data``.
"""

import pytest

from tests.conftest import RpcHarness, build_query, seeded_db


@seeded_db
@pytest.mark.parametrize(
    ("page", "per_page", "sort", "order", "entities"),
    [
        (1, 10, "id", "desc", []),
        (1, 25, "name", "desc", []),
        (1, 10, "value", "asc", []),
    ],
)
def test_get_champions(
    rpc: RpcHarness,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    entities: list[str],
) -> None:
    env = rpc.call_sync(
        "rpc.stats.statistics.champion",
        {
            "query": build_query(
                {
                    "page": page,
                    "per_page": per_page,
                    "sort": sort,
                    "order": order,
                    "entities": entities,
                    "discipline": "overwatch",
                }
            )
        },
    )
    assert env["ok"] is True
    content = env["data"]
    assert content["page"] == page
    assert content["per_page"] == per_page
    assert content["results"]


LEADERBOARDS = ("rpc.stats.statistics.champion", "rpc.stats.statistics.winrate", "rpc.stats.statistics.players")


@pytest.mark.parametrize("topic", LEADERBOARDS)
@pytest.mark.parametrize("discipline", [None, "all"])
def test_a_leaderboard_without_a_game_is_every_game(rpc: RpcHarness, topic: str, discipline: str | None) -> None:
    params: dict[str, object] = {"page": 1, "per_page": 10, "order": "desc"}
    if discipline is not None:
        params["discipline"] = discipline
    env = rpc.call_sync(topic, {"query": build_query(params)})
    assert env["ok"] is True, env
    assert env["data"]["page"] == 1


@pytest.mark.parametrize("topic", LEADERBOARDS)
def test_a_leaderboard_never_reads_an_unknown_game(rpc: RpcHarness, topic: str) -> None:
    env = rpc.call_sync(topic, {"query": build_query({"discipline": "chess", "per_page": 10})})
    assert env["ok"] is False
    assert env["error"]["code"] == "not_found"
    assert env["error"]["details"]["fields"][0]["code"] == "discipline_not_installed"


@pytest.mark.parametrize(
    ("topic", "data"),
    [
        ("rpc.stats.statistics.records", {"query": build_query({"discipline": "chess"})}),
        ("rpc.stats.statistics.maps", {"discipline": "chess", "query": {}}),
    ],
)
def test_records_and_maps_never_read_an_unknown_game(rpc: RpcHarness, topic: str, data: dict) -> None:
    env = rpc.call_sync(topic, data)
    assert env["ok"] is False
    assert env["error"]["details"]["fields"][0]["code"] == "discipline_not_installed"


def test_the_players_sort_is_validated(rpc: RpcHarness) -> None:
    env = rpc.call_sync("rpc.stats.statistics.players", {"query": build_query({"sort": "value"})})
    assert env["ok"] is False
    assert env["error"]["code"] == "unprocessable"
