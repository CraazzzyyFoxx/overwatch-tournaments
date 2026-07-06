import pytest

from src.rpc import workspaces as workspaces_rpc


@pytest.mark.integration
def test_by_host_unknown_returns_null(rpc):
    harness = rpc  # session-scoped harness (skips if DB unreachable)
    harness.register(workspaces_rpc)
    res = harness.call_sync(
        "rpc.app.workspaces.by_host",
        {"query": {"host": ["nope.owt.craazzzyyfoxx.me"]}},
    )
    assert res["ok"] is True
    assert res["data"] is None


@pytest.mark.integration
def test_by_host_missing_host_returns_null(rpc):
    harness = rpc
    harness.register(workspaces_rpc)
    res = harness.call_sync("rpc.app.workspaces.by_host", {"query": {}})
    assert res["ok"] is True
    assert res["data"] is None


@pytest.mark.integration
def test_by_host_non_platform_zone_returns_null(rpc):
    harness = rpc
    harness.register(workspaces_rpc)
    res = harness.call_sync(
        "rpc.app.workspaces.by_host",
        {"query": {"host": ["example.com"]}},
    )
    assert res["ok"] is True
    assert res["data"] is None
