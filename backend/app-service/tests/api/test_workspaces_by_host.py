import asyncio
import uuid
from datetime import UTC, datetime

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
    """A syntactically valid, non-platform host with no matching custom domain
    now exercises the Phase 2 custom-domain branch (rather than short-circuiting
    on a missing subdomain label) and still resolves to ``None``."""
    harness = rpc
    harness.register(workspaces_rpc)
    res = harness.call_sync(
        "rpc.app.workspaces.by_host",
        {"query": {"host": ["example.com"]}},
    )
    assert res["ok"] is True
    assert res["data"] is None


@pytest.mark.integration
def test_by_host_invalid_custom_domain_format_returns_null(rpc):
    """A host that is neither a platform-zone subdomain nor a valid FQDN (no
    dot) fails ``normalize_custom_domain`` and short-circuits to ``None``
    without attempting a custom-domain lookup."""
    harness = rpc
    harness.register(workspaces_rpc)
    res = harness.call_sync(
        "rpc.app.workspaces.by_host",
        {"query": {"host": ["nodot"]}},
    )
    assert res["ok"] is True
    assert res["data"] is None


@pytest.fixture
def custom_domain_workspace():
    """Create a verified + an unverified custom-domain workspace directly in the
    DB, committed (not rolled back) so the ``by_host`` RPC — which opens its own
    connection via ``db.async_session_maker`` — can see them in a separate
    transaction. Both rows are deleted in teardown so nothing lingers in the
    dev DB.

    Skips cleanly when the DB is unreachable or has no default division grid
    version configured (mirrors the ``rpc`` fixture / ``test_workspace_member_helpers``
    DB-skip pattern).
    """
    from shared.models.tenancy.workspace import Workspace
    from shared.services.division_grid_access import get_default_division_grid_version_id
    from src.core import db as db_module

    suffix = uuid.uuid4().hex[:12]
    verified_domain = f"verified-{suffix}.example.com"
    unverified_domain = f"unverified-{suffix}.example.com"
    verified_slug = f"cdom-verified-{suffix}"

    async def _create() -> tuple[int, int] | None:
        async with db_module.async_session_maker() as session:
            grid_version_id = await get_default_division_grid_version_id(session)
            if grid_version_id is None:
                return None
            verified = Workspace(
                slug=verified_slug,
                name=f"Custom Domain Verified {suffix}",
                default_division_grid_version_id=grid_version_id,
                custom_domain=verified_domain,
                custom_domain_verified_at=datetime.now(UTC),
            )
            unverified = Workspace(
                slug=f"cdom-unverified-{suffix}",
                name=f"Custom Domain Unverified {suffix}",
                default_division_grid_version_id=grid_version_id,
                custom_domain=unverified_domain,
                custom_domain_verified_at=None,
            )
            session.add_all([verified, unverified])
            await session.commit()
            return verified.id, unverified.id

    async def _delete(ids: tuple[int, int]) -> None:
        async with db_module.async_session_maker() as session:
            for workspace_id in ids:
                workspace = await session.get(Workspace, workspace_id)
                if workspace is not None:
                    await session.delete(workspace)
            await session.commit()

    try:
        created = asyncio.run(_create())
    except Exception as exc:  # noqa: BLE001 -- any connect failure => skip, not fail
        pytest.skip(f"database unreachable: {exc}")
        return
    if created is None:
        pytest.skip("no default division grid version configured in dev DB")
        return

    verified_id, unverified_id = created
    try:
        yield {
            "verified_id": verified_id,
            "verified_slug": verified_slug,
            "verified_domain": verified_domain,
            "unverified_domain": unverified_domain,
        }
    finally:
        asyncio.run(_delete((verified_id, unverified_id)))


@pytest.mark.integration
def test_by_host_verified_custom_domain_resolves(rpc, custom_domain_workspace):
    harness = rpc
    harness.register(workspaces_rpc)
    # Mixed case + explicit port exercises normalize_custom_domain's lowercasing
    # and port-stripping on the way into the lookup.
    host = custom_domain_workspace["verified_domain"].upper() + ":8443"
    res = harness.call_sync("rpc.app.workspaces.by_host", {"query": {"host": [host]}})
    assert res["ok"] is True
    assert res["data"] == {
        "workspace_id": custom_domain_workspace["verified_id"],
        "slug": custom_domain_workspace["verified_slug"],
    }


@pytest.mark.integration
def test_by_host_unverified_custom_domain_returns_null(rpc, custom_domain_workspace):
    """Fail-closed guarantee: a workspace that has claimed a custom domain but
    has not yet completed DNS verification must not resolve."""
    harness = rpc
    harness.register(workspaces_rpc)
    res = harness.call_sync(
        "rpc.app.workspaces.by_host",
        {"query": {"host": [custom_domain_workspace["unverified_domain"]]}},
    )
    assert res["ok"] is True
    assert res["data"] is None
