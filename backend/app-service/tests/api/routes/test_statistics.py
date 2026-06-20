"""RPC-handler tests for the statistics surface.

Targets:
- champion -> ``rpc.app.statistics.champion``

Replaces the former HTTP-client test (``GET /statistics/champion``) against the
decommissioned HTTP service; assertions mirror the old test on the envelope
``data``.
"""

import pytest

from tests.conftest import RpcHarness, build_query


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
        "rpc.app.statistics.champion",
        {
            "query": build_query(
                {
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
    assert content["results"]
