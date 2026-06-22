"""RPC-handler tests for the hero surface.

Targets:
- list     -> ``rpc.app.read.list`` (entity=hero, shared CRUD read engine)
- get      -> ``rpc.app.read.get``  (entity=hero)
- playtime -> ``rpc.app.heroes.playtime``

Replaces the former HTTP-client tests against the decommissioned HTTP service;
assertions mirror the old tests on the envelope ``data``.
"""

import pytest

from tests.conftest import RpcHarness, build_query


@pytest.mark.parametrize(
    ("page", "per_page", "sort", "order", "entities", "query", "fields"),
    [
        (1, 10, "id", "desc", [], "", []),
        (1, 25, "slug", "desc", [], "", []),
        (1, 10, "similarity:name", "asc", [], "han", ["name"]),
        (1, 10, "similarity:name", "desc", [], "hanzo", ["name"]),
    ],
)
def test_search_hero(
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
        "rpc.app.read.list",
        {
            "entity": "hero",
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


@pytest.mark.parametrize(
    ("hero_id",),
    [
        (1,),
        (2,),
        (3,),
        (4,),
        (5,),
    ],
)
def test_get_hero_by_id(rpc: RpcHarness, hero_id: int) -> None:
    env = rpc.call_sync("rpc.app.read.get", {"entity": "hero", "id": hero_id})
    assert env["ok"] is True
    content = env["data"]
    assert content["id"] == hero_id


@pytest.mark.parametrize(
    ("user_id", "page", "per_page", "sort", "order", "entities"),
    [
        ("all", 1, 10, "id", "desc", []),
        ("all", 1, 10, "playtime", "desc", []),
        (599, 1, 10, "id", "desc", []),
        (599, 1, 10, "playtime", "desc", []),
        (79, 1, 10, "id", "desc", []),
        (79, 1, 10, "playtime", "desc", []),
    ],
)
def test_get_hero_playtime(
    rpc: RpcHarness,
    user_id: int,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    entities: list[str],
) -> None:
    env = rpc.call_sync(
        "rpc.app.heroes.playtime",
        {
            "query": build_query(
                {
                    "user_id": user_id,
                    "page": page,
                    "per_page": per_page,
                    "sort": sort,
                    "order": order,
                    "entities": entities,
                }
            )
        },
    )
    assert env["ok"] is True
    content = env["data"]
    assert content["page"] == page
    assert content["per_page"] == per_page
    if content["results"]:
        assert content["results"][0]["playtime"]
