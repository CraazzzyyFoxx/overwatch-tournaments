"""RPC-handler tests for the users identity reads app-service keeps.

- ``GET /users``         -> ``rpc.app.users.list``
- ``GET /users/{name}``  -> ``rpc.app.users.by_name``

The statistics reads of ``/users/*`` moved to stats-service (``rpc.stats.users.*``,
``stats-service/tests/api/routes/test_user.py``).
"""

import uuid
from collections.abc import Generator

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from shared import models
from tests.conftest import RpcHarness, build_query


@pytest.fixture(scope="module")
def seeded_name(db: Session) -> Generator[str]:
    """A player named like a battletag (``Seed<hex>#2130``) with a publicly visible
    Battle.net and Twitch account. Committed, because the handlers open their own
    sessions; deleted afterwards (its accounts and visibility rows cascade)."""
    name = f"Seed{uuid.uuid4().hex[:12]}#2130"
    user = models.User(
        name=name,
        social_accounts=[
            models.SocialAccount(provider=provider, username=username, visibilities=[models.SocialAccountVisibility()])
            for provider, username in (("battlenet", name), ("twitch", name.split("#")[0].lower()))
        ],
    )
    db.add(user)
    db.commit()
    yield name
    db.execute(sa.delete(models.User).where(models.User.id == user.id))
    db.commit()


@pytest.mark.parametrize(
    ("page", "per_page", "sort", "order", "entities", "search"),
    [
        (1, 10, "id", "desc", [], False),
        (1, 25, "id", "desc", [], False),
        (1, 10, "id", "desc", ["social_accounts"], False),
        (1, 10, "similarity:name", "asc", ["social_accounts"], True),
    ],
)
def test_search_user(
    rpc: RpcHarness,
    seeded_name: str,
    page: int,
    per_page: int,
    sort: str,
    order: str,
    entities: list[str],
    search: bool,
) -> None:
    query = seeded_name.split("#")[0].lower() if search else ""
    env = rpc.call_sync(
        "rpc.app.users.list",
        {
            "query": build_query(
                {
                    "page": page,
                    "per_page": per_page,
                    "sort": sort,
                    "order": order,
                    "entities": entities,
                    "query": query,
                    "fields": ["name"] if search else [],
                }
            )
        },
    )
    assert env["ok"] is True
    content = env["data"]
    assert content["page"] == page
    assert content["per_page"] == per_page
    assert content["results"]

    if search:
        assert [user["name"] for user in content["results"]] == [seeded_name]


@pytest.mark.parametrize("entities", [[], ["social_accounts"]])
def test_get_user_by_name(rpc: RpcHarness, seeded_name: str, entities: list[str]) -> None:
    env = rpc.call_sync(
        "rpc.app.users.by_name",
        {"name": seeded_name.replace("#", "-"), "query": build_query({"entities": entities})},
    )
    assert env["ok"] is True
    content = env["data"]
    assert content["name"] == seeded_name
    if "social_accounts" in entities:
        assert {s["provider"] for s in content["social_accounts"]} == {"battlenet", "twitch"}
