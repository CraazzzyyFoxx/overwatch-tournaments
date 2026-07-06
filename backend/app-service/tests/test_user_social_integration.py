"""Integration test (anak_dev): rpc.app.users.by_name returns the unified
``social_accounts`` field plus backward-compatible legacy groupings.

Skips cleanly when the DB is unreachable / is production (see conftest fixtures).
"""

import sqlalchemy as sa


def test_by_name_returns_social_accounts(rpc, db):
    row = db.execute(
        sa.text(
            "select username from players.social_account "
            "where provider = 'battlenet' and username not like '%-%' "
            "order by id limit 1"
        )
    ).first()
    if row is None:
        import pytest

        pytest.skip("no battlenet social account in dev DB")
    battle_tag = row[0]

    # by_name maps '-' back to '#', so pass the tag with '#' encoded as '-'.
    env = {
        "name": battle_tag.replace("#", "-"),
        "query": {"entities": ["twitch", "discord", "battle_tag"]},
    }
    res = rpc.call_sync("rpc.app.users.by_name", env)
    assert res.get("ok"), res
    data = res["data"]

    # Unified field present and contains the battletag; legacy grouped fields gone.
    assert "social_accounts" in data
    assert "battle_tag" not in data and "discord" not in data and "twitch" not in data
    assert any(s["provider"] == "battlenet" and s["username"] == battle_tag for s in data["social_accounts"]), data[
        "social_accounts"
    ]

    # Every account exposes the unified fields.
    for account in data["social_accounts"]:
        assert {"provider", "username", "is_verified", "is_primary"}.issubset(account)
