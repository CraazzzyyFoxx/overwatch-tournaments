from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from shared.rbac import ALL_SCOPE_NAMES  # noqa: E402
from shared.rpc.identity import credential_type, rehydrate_user  # noqa: E402
from src import models, schemas  # noqa: E402
from src.core import key_derivation  # noqa: E402
from src.core.config import settings  # noqa: E402
from src.rpc import _common as c  # noqa: E402
from src.services import api_keys as api_keys_module  # noqa: E402
from src.services.api_keys import api_keys  # noqa: E402
from tests._fakes import FakeExecuteResult as _FakeExecuteResult  # noqa: E402
from tests._fakes import make_api_key_row as _api_key_row  # noqa: E402
from tests._fakes import make_auth_user as _user  # noqa: E402
from tests._fakes import make_workspace as _workspace  # noqa: E402


class _FakeSession:
    def __init__(self, results: list[dict] | None = None) -> None:
        self._results = list(results or [])
        self.added = []
        self.flush_calls = 0
        self.commit_calls = 0
        self.refresh_calls = 0

    def add(self, row) -> None:
        self.added.append(row)

    async def execute(self, stmt):
        if not self._results:
            raise AssertionError("Unexpected execute() call")
        return _FakeExecuteResult(**self._results.pop(0))

    async def commit(self) -> None:
        self.commit_calls += 1

    async def flush(self) -> None:
        self.flush_calls += 1

    async def refresh(self, row) -> None:
        self.refresh_calls += 1
        row.id = 99
        row.created_at = datetime.now(UTC)
        row.updated_at = None


_TEAM_CREATE = [{"resource": "team", "action": "create"}]
_WILDCARD = [{"resource": "*", "action": "*"}]


def _owner_payload(
    *,
    workspace_permissions: list[dict[str, str]] | None = None,
    workspaces: tuple[int, ...] = (11,),
    denies: list[dict[str, object]] | None = None,
    is_superuser: bool = False,
) -> schemas.TokenPayload:
    """The owner's RBAC exactly as ``TokenPayloadBuilder`` would hand it over."""
    return schemas.TokenPayload(
        sub=7,
        email="ada@example.com",
        username="ada",
        is_superuser=is_superuser,
        roles=[],
        permissions=[],
        denies=list(denies or []),
        workspaces=[
            schemas.WorkspaceMembership(
                workspace_id=workspace_id,
                slug="main",
                rbac_roles=[],
                rbac_permissions=list(workspace_permissions or []),
            )
            for workspace_id in workspaces
        ],
    )


def _patch_owner(monkeypatch: pytest.MonkeyPatch, payload: schemas.TokenPayload) -> None:
    """Stub the RBAC *builder* only.

    The rehydration and ``has_workspace_permission`` calls that decide what the
    key may do stay real -- stubbing those would leave the narrowing untested,
    which is the one thing here that can escalate privilege.
    """

    class _Builder:
        async def build(self, _session, _user, *, cached=None) -> schemas.TokenPayload:
            return payload

    monkeypatch.setattr(api_keys, "payloads", _Builder())


def test_create_api_key_returns_secret_once_and_stores_only_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    tokens = iter(["publicid", "secret-token"])

    async def allow_manage(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(api_keys, "ensure_can_manage", allow_manage)
    monkeypatch.setattr(api_keys_module.secrets, "token_hex", lambda _bytes: next(tokens))

    response = asyncio.run(
        api_keys.create(
            session,
            user=_user(),
            payload=schemas.ApiKeyCreate(name="  Balancer API  ", workspace_id=11),
        )
    )

    stored = session.added[0]
    assert response.key == "owt_sk_publicid_secret-token"
    assert stored.secret_hash == api_keys._hash_secret("secret-token")
    assert stored.secret_hash != "secret-token"
    assert stored.name == "Balancer API"
    assert "secret" not in response.api_key.model_dump()
    # No implicit grant: a key nobody scoped authenticates and authorizes nothing.
    assert [item.scope for item in stored.scopes] == []
    # Balancer quotas are not an identity concern; empty JSON lets each
    # consumer apply its own defaults (gateway rate, balancer job caps).
    assert stored.limits_json == {}
    assert session.flush_calls == 1
    assert session.commit_calls == 1
    assert session.refresh_calls == 1


def test_create_api_key_rejects_scopes_outside_the_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow_manage(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(api_keys, "ensure_can_manage", allow_manage)

    with pytest.raises(api_keys_module.HTTPException) as exc_info:
        asyncio.run(
            api_keys.create(
                _FakeSession(),
                user=_user(),
                payload=schemas.ApiKeyCreate(name="CI", workspace_id=11, scopes=["team.create", "not.a.scope"]),
            )
        )

    assert exc_info.value.status_code == 422
    assert "not.a.scope" in exc_info.value.detail


def test_create_api_key_refuses_a_scope_the_caller_does_not_hold(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delegation only narrows: nobody mints a key stronger than themselves."""

    async def allow_manage(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(api_keys, "ensure_can_manage", allow_manage)
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=_TEAM_CREATE))

    with pytest.raises(api_keys_module.HTTPException) as exc_info:
        asyncio.run(
            api_keys.create(
                _FakeSession(),
                user=_user(),
                payload=schemas.ApiKeyCreate(name="CI", workspace_id=11, scopes=["match.update"]),
            )
        )

    assert exc_info.value.status_code == 403
    assert "match.update" in exc_info.value.detail


def test_create_api_key_stores_normalized_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()
    tokens = iter(["publicid", "secret-token"])

    async def allow_manage(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(api_keys, "ensure_can_manage", allow_manage)
    monkeypatch.setattr(api_keys_module.secrets, "token_hex", lambda _bytes: next(tokens))
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=_TEAM_CREATE))

    asyncio.run(
        api_keys.create(
            session,
            user=_user(),
            payload=schemas.ApiKeyCreate(name="CI", workspace_id=11, scopes=["balancer.jobs", "team.create"]),
        )
    )

    # The legacy alias collapses onto the permission it always meant, deduped.
    assert [item.scope for item in session.added[0].scopes] == ["team.create"]


def test_is_api_key_recognizes_the_current_and_legacy_prefixed_forms() -> None:
    assert api_keys.is_api_key("owt_sk_publicid_secret-token") is True
    assert api_keys.is_api_key("aqt_sk_publicid_secret-token") is True
    assert api_keys.is_api_key("eyJhbGciOiJIUzI1NiJ9.payload.sig") is False


@pytest.mark.parametrize(
    "raw_key",
    ["bad-format", "owt_sk__secret", "owt_sk_publicid_", "sk_owt_publicid_secret", "owt_sk_publicid_secret_extra"],
)
def test_split_key_rejects_malformed_keys(raw_key: str) -> None:
    assert api_keys._split_key(raw_key) is None


def test_verify_secret_accepts_the_legacy_raw_secret_hash() -> None:
    """Keys minted before domain separation stored ``HMAC(JWT_SECRET_KEY, secret)``.

    They must keep validating without a re-issue, while new writes use only the
    derived subkey.
    """
    legacy_hash = key_derivation.legacy_hmac_sha256_hex(settings.JWT_SECRET_KEY, "secret-token")

    assert legacy_hash != api_keys._hash_secret("secret-token")
    assert api_keys._verify_secret("secret-token", legacy_hash) is True
    assert api_keys._verify_secret("wrong", legacy_hash) is False


def test_validate_api_key_accepts_a_legacy_hashed_key(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _api_key_row(secret_hash=key_derivation.legacy_hmac_sha256_hex(settings.JWT_SECRET_KEY, "secret-token"))
    session = _FakeSession([{"scalar": row}])
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=_TEAM_CREATE))

    payload = asyncio.run(api_keys.validate(session, "aqt_sk_publicid_secret-token"))

    assert payload is not None
    assert payload.api_key is not None
    assert payload.api_key.id == 123


def test_validate_api_key_narrows_owner_rbac_to_the_key_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scope list is what was asked for; the permission list is what was granted."""
    row = _api_key_row(scopes=["team.create", "match.update"])
    session = _FakeSession([{"scalar": row}])
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=_TEAM_CREATE))

    payload = asyncio.run(api_keys.validate(session, "aqt_sk_publicid_secret-token"))

    assert payload is not None
    assert payload.credential_type == "api_key"
    assert payload.api_key is not None
    assert payload.api_key.id == 123
    assert payload.api_key.workspace_id == 11
    assert payload.api_key.scopes == ["team.create", "match.update"]
    assert payload.workspaces[0].workspace_id == 11
    # ``match.update`` was requested but the owner does not hold it: a key can
    # never be granted authority its owner lacks.
    assert payload.workspaces[0].rbac_permissions == _TEAM_CREATE
    assert row.last_used_at is not None
    assert session.commit_calls == 1


def test_validate_api_key_normalizes_the_legacy_balancer_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keys issued before scopes were real must keep their exact authority."""
    row = _api_key_row(scopes=["balancer.jobs"])
    session = _FakeSession([{"scalar": row}])
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=_TEAM_CREATE))

    payload = asyncio.run(api_keys.validate(session, "aqt_sk_publicid_secret-token"))

    assert payload is not None
    assert payload.api_key is not None
    assert payload.api_key.scopes == ["team.create"]
    assert payload.workspaces[0].rbac_permissions == _TEAM_CREATE


def test_validate_api_key_never_inherits_superuser_or_role_names(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _api_key_row(scopes=["team.create"])
    session = _FakeSession([{"scalar": row}])
    _patch_owner(monkeypatch, _owner_payload(is_superuser=True))

    payload = asyncio.run(api_keys.validate(session, "aqt_sk_publicid_secret-token"))

    assert payload is not None
    assert payload.is_superuser is False
    assert payload.roles == []
    assert payload.permissions == []
    assert payload.workspaces[0].rbac_roles == []
    # A superuser holds every permission, so the scope is granted -- but only
    # the scope, and only in the key's own workspace.
    assert payload.workspaces[0].rbac_permissions == _TEAM_CREATE


@pytest.mark.parametrize(
    ("owner_permissions", "expected"),
    [(_WILDCARD, _WILDCARD), (_TEAM_CREATE, [])],
)
def test_validate_api_key_grants_the_wildcard_scope_only_to_a_wildcard_owner(
    monkeypatch: pytest.MonkeyPatch,
    owner_permissions: list[dict[str, str]],
    expected: list[dict[str, str]],
) -> None:
    row = _api_key_row(scopes=["admin.*"])
    session = _FakeSession([{"scalar": row}])
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=owner_permissions))

    payload = asyncio.run(api_keys.validate(session, "aqt_sk_publicid_secret-token"))

    assert payload is not None
    assert payload.workspaces[0].rbac_permissions == expected


def test_validate_api_key_applies_and_forwards_the_deny_overlay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative RBAC used to fail open through a key: ``denies`` was never set."""
    row = _api_key_row(scopes=["team.create"])
    session = _FakeSession([{"scalar": row}])
    denies: list[dict[str, object]] = [{"resource": "team", "action": "create", "workspace_id": 11}]
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=_TEAM_CREATE, denies=denies))

    payload = asyncio.run(api_keys.validate(session, "aqt_sk_publicid_secret-token"))

    assert payload is not None
    # The deny outranks the grant, so the scope yields nothing...
    assert payload.workspaces[0].rbac_permissions == []
    # ...and it rides along, so every downstream deny check sees it too.
    assert payload.denies == denies


@pytest.mark.parametrize(
    ("row", "raw_key"),
    [
        (_api_key_row(secret="expected"), "bad-format"),
        (_api_key_row(secret="expected"), "aqt_sk_publicid_wrong"),
        (_api_key_row(revoked_at=datetime.now(UTC)), "aqt_sk_publicid_secret-token"),
        (_api_key_row(expires_at=datetime.now(UTC) - timedelta(seconds=1)), "aqt_sk_publicid_secret-token"),
        (_api_key_row(user=_user(active=False)), "aqt_sk_publicid_secret-token"),
        (_api_key_row(workspace=_workspace(active=False)), "aqt_sk_publicid_secret-token"),
    ],
)
def test_validate_api_key_rejects_invalid_revoked_expired_or_inactive(
    monkeypatch: pytest.MonkeyPatch,
    row: models.ApiKey,
    raw_key: str,
) -> None:
    session = _FakeSession([{"scalar": row}])
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=_TEAM_CREATE))

    payload = asyncio.run(api_keys.validate(session, raw_key))

    assert payload is None
    assert session.commit_calls == 0


def test_validate_api_key_rejects_when_the_owner_leaves_the_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """A key must not outlive the membership it was scoped to."""
    row = _api_key_row()
    session = _FakeSession([{"scalar": row}])
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=_TEAM_CREATE, workspaces=(12,)))

    payload = asyncio.run(api_keys.validate(session, "aqt_sk_publicid_secret-token"))

    assert payload is None
    assert session.commit_calls == 0


def test_grantable_scopes_are_bounded_by_the_callers_own_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=_TEAM_CREATE))

    grantable = asyncio.run(api_keys.grantable_scopes(_FakeSession(), user=_user(), workspace_id=11))

    assert grantable == frozenset({"team.create"})


def test_grantable_scopes_for_a_wildcard_owner_cover_the_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_owner(monkeypatch, _owner_payload(workspace_permissions=_WILDCARD))

    grantable = asyncio.run(api_keys.grantable_scopes(_FakeSession(), user=_user(), workspace_id=11))

    assert grantable == ALL_SCOPE_NAMES


@pytest.mark.parametrize(
    ("role_name", "permissions"),
    [
        ("admin", [{"resource": "team", "action": "create"}]),
        # Workspace owner holds ``admin.*``, stored as the wildcard pair.
        ("owner", [{"resource": "*", "action": "*"}]),
    ],
)
def test_workspace_admin_and_owner_manage_api_keys_via_rbac_alone(
    monkeypatch: pytest.MonkeyPatch,
    role_name: str,
    permissions: list[dict[str, str]],
) -> None:
    """Guards the removal of the legacy role-name shortcut in
    ``_has_workspace_import_access``: authorization must come from the
    workspace RBAC permission set, with no name-based fast path.
    """
    session = _FakeSession()

    async def get_workspace(_session, workspace_id: int) -> models.Workspace:
        assert workspace_id == 11
        return _workspace()

    async def get_member(_session, *, workspace_id: int, auth_user_id: int) -> models.WorkspaceMember:
        assert (workspace_id, auth_user_id) == (11, 7)
        return models.WorkspaceMember(workspace_id=workspace_id, player_id=42)

    async def workspace_rbac(_session, _user_id, _workspace_ids) -> dict:
        return {11: ([role_name], permissions)}

    monkeypatch.setattr(api_keys.workspaces, "get", get_workspace)
    monkeypatch.setattr(api_keys.members, "get_member", get_member)
    monkeypatch.setattr(api_keys.roles, "workspace_rbac_for_user", workspace_rbac)

    # Raises HTTPException(403) on denial; returning None is the pass signal.
    assert asyncio.run(api_keys.ensure_can_manage(session, user=_user(), workspace_id=11)) is None


def test_ensure_can_manage_denies_a_workspace_member_without_team_create(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession()

    async def get_workspace(_session, _workspace_id: int) -> models.Workspace:
        return _workspace()

    async def get_member(_session, *, workspace_id: int, auth_user_id: int) -> models.WorkspaceMember:
        return models.WorkspaceMember(workspace_id=workspace_id, player_id=42)

    async def workspace_rbac(_session, _user_id, _workspace_ids) -> dict:
        return {11: (["viewer"], [{"resource": "team", "action": "read"}])}

    monkeypatch.setattr(api_keys.workspaces, "get", get_workspace)
    monkeypatch.setattr(api_keys.members, "get_member", get_member)
    monkeypatch.setattr(api_keys.roles, "workspace_rbac_for_user", workspace_rbac)

    with pytest.raises(api_keys_module.HTTPException) as exc_info:
        asyncio.run(api_keys.ensure_can_manage(session, user=_user(), workspace_id=11))

    assert exc_info.value.status_code == 403
    assert "team.create required" in exc_info.value.detail


@pytest.mark.parametrize(
    ("workspace", "expected_status"),
    [(None, 404), (_workspace(active=False), 403)],
)
def test_ensure_can_manage_rejects_missing_or_inactive_workspace(
    monkeypatch: pytest.MonkeyPatch,
    workspace: models.Workspace | None,
    expected_status: int,
) -> None:
    async def get_workspace(_session, _workspace_id: int) -> models.Workspace | None:
        return workspace

    monkeypatch.setattr(api_keys.workspaces, "get", get_workspace)

    with pytest.raises(api_keys_module.HTTPException) as exc_info:
        asyncio.run(api_keys.ensure_can_manage(_FakeSession(), user=_user(), workspace_id=11))

    assert exc_info.value.status_code == expected_status


def test_list_api_keys_requires_a_workspace() -> None:
    with pytest.raises(api_keys_module.HTTPException) as exc_info:
        asyncio.run(api_keys.list(_FakeSession(), user=_user(), params=schemas.ApiKeyListParams(workspace_id=None)))

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "workspace_id is required"


def test_list_api_keys_returns_page_and_workspace_wide_status_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    """The counts row must survive pagination and default missing buckets to 0."""
    session = _FakeSession()

    async def allow_manage(*args, **kwargs) -> None:
        return None

    async def list_page(_session, _params, *, workspace_id: int, search: str | None):
        assert (workspace_id, search) == (11, None)
        return [_api_key_row()], 4

    async def status_counts(_session, *, workspace_id: int, now) -> dict[str, int]:
        assert workspace_id == 11
        # ``expired`` deliberately absent: the tally query omits empty buckets.
        return {"active": 3, "revoked": 1}

    async def grantable(_session, *, user, workspace_id: int) -> frozenset[str]:
        assert (user.id, workspace_id) == (7, 11)
        return frozenset({"team.read", "team.create"})

    monkeypatch.setattr(api_keys, "ensure_can_manage", allow_manage)
    monkeypatch.setattr(api_keys, "grantable_scopes", grantable)
    monkeypatch.setattr(api_keys.keys, "list_page", list_page)
    monkeypatch.setattr(api_keys.keys, "status_counts", status_counts)

    result = asyncio.run(api_keys.list(session, user=_user(), params=schemas.ApiKeyListParams(workspace_id=11)))

    assert result["total"] == 4
    assert [row.id for row in result["results"]] == [123]
    assert result["results"][0].owner_username == "ada"
    counts = result["counts"]
    assert (counts.total, counts.active, counts.expired, counts.revoked) == (4, 3, 0, 1)
    # Sorted so the create form renders deterministically.
    assert result["available_scopes"] == ["team.create", "team.read"]


def test_list_api_key_envelope_keeps_available_scopes_on_the_wire() -> None:
    """The service computed ``available_scopes``; the RPC serializer dropped it.

    With an empty list the create form offers no scopes at all, so every key
    minted from the UI is inert -- and the picker, handed ``undefined``, took
    the admin page down with it.
    """
    envelope = c.paginated_dump(
        {
            "results": [api_keys.describe(_api_key_row())],
            "total": 1,
            "page": 1,
            "per_page": 20,
            "counts": schemas.ApiKeyStatusCounts(total=1, active=1, expired=0, revoked=0),
            "available_scopes": ["team.create", "team.read"],
        }
    )

    assert envelope["available_scopes"] == ["team.create", "team.read"]
    assert envelope["counts"] == {"total": 1, "active": 1, "expired": 0, "revoked": 0}
    assert [row["id"] for row in envelope["results"]] == [123]


def test_validated_key_payload_authorizes_exactly_its_scopes_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam this whole design rests on.

    ``validate`` builds the payload the gateway injects; ``rehydrate_user`` is
    what every worker turns it back into. Both sides are covered on their own,
    but only end to end does a shape mismatch between them show up -- and the
    failure mode is silent over-permission, not an error.
    """
    row = _api_key_row(scopes=["team.create", "match.update"])
    session = _FakeSession([{"scalar": row}])
    _patch_owner(
        monkeypatch,
        _owner_payload(workspace_permissions=[*_TEAM_CREATE, {"resource": "team", "action": "read"}]),
    )

    payload = asyncio.run(api_keys.validate(session, "aqt_sk_publicid_secret-token"))
    assert payload is not None

    user = rehydrate_user(payload.model_dump(mode="json"))

    assert credential_type(user) == "api_key"
    assert user.id == 7
    # Granted: requested AND held by the owner.
    assert user.has_workspace_permission(11, "team", "create") is True
    # Held by the owner but never requested -- delegation is opt-in.
    assert user.has_workspace_permission(11, "team", "read") is False
    # Requested but not held by the owner.
    assert user.has_workspace_permission(11, "match", "update") is False
    # Another workspace is out of reach whatever the scope says.
    assert user.has_workspace_permission(12, "team", "create") is False
    assert user.is_workspace_member(12) is False
    # No blanket bypass survived the narrowing.
    assert user.is_superuser is False
    assert user.is_workspace_admin(11) is False
