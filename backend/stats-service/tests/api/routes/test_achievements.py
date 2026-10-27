"""RPC-handler tests for the achievements surface.

Targets:
- list  -> ``rpc.stats.achievements.list``
- get   -> ``rpc.stats.achievements.get``
- user  -> ``rpc.stats.achievements.user``

Replaces the former HTTP-client tests; the reads are headless RPC handlers.
Assertions mirror the old HTTP tests against the envelope ``data``; the conflict
case (HTTP 400) maps to the envelope ``error.code`` = ``bad_request`` (the
gateway maps 400 -> bad_request).
"""

import pytest

from tests.conftest import RpcHarness, build_query, seeded_db


@seeded_db
@pytest.mark.parametrize(
    ("page", "per_page", "sort", "order", "entities", "query", "fields"),
    [
        (1, 10, "id", "desc", [], "", []),
        (1, 25, "slug", "desc", [], "", []),
        (1, 10, "name", "asc", [], "", []),
        (1, 10, "rarity", "asc", [], "", []),
    ],
)
def test_search_achievement(
    rpc: RpcHarness,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    entities: list[str],
    query: str,
    fields: list[str],
) -> None:
    env = rpc.call_sync(
        "rpc.stats.achievements.list",
        {
            "query": build_query(
                {
                    "page": page,
                    "per_page": per_page,
                    "sort": sort,
                    "order": order,
                    "entities": entities,
                    "query": query,
                    "fields": fields,
                }
            ),
        },
    )
    assert env["ok"] is True
    content = env["data"]
    assert content["page"] == page
    assert content["per_page"] == per_page
    assert content["results"]

    if query:
        assert query in content["results"][0]["name"].lower()


@seeded_db
@pytest.mark.parametrize(
    ("achievement_id",),
    [
        (1,),
        (2,),
        (3,),
        (4,),
        (5,),
    ],
)
def test_get_achievement_by_id(rpc: RpcHarness, achievement_id: int) -> None:
    env = rpc.call_sync("rpc.stats.achievements.get", {"id": achievement_id})
    assert env["ok"] is True
    content = env["data"]
    assert content["id"] == achievement_id


@seeded_db
@pytest.mark.parametrize(
    ("user_id",),
    [
        (599,),
        (79,),
        (461,),
        (583,),
    ],
)
def test_get_achievement_by_user(rpc: RpcHarness, user_id: int) -> None:
    env = rpc.call_sync("rpc.stats.achievements.user", {"id": user_id})
    assert env["ok"] is True
    content = env["data"]
    assert content.__len__() > 0


@seeded_db
@pytest.mark.parametrize(
    ("user_id",),
    [
        (599,),
        (79,),
        (461,),
        (583,),
    ],
)
def test_get_achievement_by_user_filter_without_tournament(rpc: RpcHarness, user_id: int) -> None:
    env = rpc.call_sync(
        "rpc.stats.achievements.user",
        {"id": user_id, "query": build_query({"without_tournament": True, "entities": ["tournaments"]})},
    )
    assert env["ok"] is True
    content = env["data"]

    for achievement in content:
        assert achievement["tournaments"] == []


@seeded_db
@pytest.mark.parametrize(
    ("user_id",),
    [
        (599,),
        (79,),
        (461,),
        (583,),
    ],
)
def test_get_achievement_by_user_filter_tournament(rpc: RpcHarness, user_id: int) -> None:
    initial_env = rpc.call_sync(
        "rpc.stats.achievements.user", {"id": user_id, "query": build_query({"entities": ["tournaments"]})}
    )
    assert initial_env["ok"] is True
    initial_content = initial_env["data"]

    tournament_id = None
    for achievement in initial_content:
        if achievement["tournaments"]:
            tournament_id = achievement["tournaments"][0]["id"]
            break

    if tournament_id is None:
        tournament_id = -1

    env = rpc.call_sync(
        "rpc.stats.achievements.user",
        {"id": user_id, "query": build_query({"tournament_id": tournament_id, "entities": ["tournaments"]})},
    )
    assert env["ok"] is True
    content = env["data"]

    for achievement in content:
        assert tournament_id in {tournament["id"] for tournament in achievement["tournaments"]}


def test_get_achievement_by_user_filter_conflict(rpc: RpcHarness) -> None:
    env = rpc.call_sync(
        "rpc.stats.achievements.user",
        {"id": 599, "query": build_query({"tournament_id": 1, "without_tournament": True})},
    )
    # HTTP 400 (ApiHTTPException invalid_request) -> envelope error.code bad_request.
    assert env["ok"] is False
    assert env["error"]["code"] == "bad_request"
