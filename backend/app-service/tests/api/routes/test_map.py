"""RPC-handler tests for the map surface.

Targets:
- list -> ``rpc.app.read.list`` (entity=map, shared CRUD read engine)

Replaces the former HTTP-client tests against the decommissioned HTTP service;
assertions mirror the old tests on the envelope ``data``. The get-by-id cases
were already commented out in the HTTP suite and stay disabled.
"""

import pytest

from tests.conftest import RpcHarness, build_query


@pytest.mark.parametrize(
    ("page", "per_page", "sort", "order", "entities", "query", "fields"),
    [
        (1, 10, "id", "desc", [], "", []),
        (1, 10, "name", "asc", [], "", []),
        (1, 25, "similarity:name", "desc", [], "nepal", ["name"]),
    ],
)
def test_search_map(
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
            "entity": "map",
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


# get-by-id / get-by-name were commented out in the original HTTP suite
# (no /maps/{id} route); they remain disabled under the RPC engine too.
