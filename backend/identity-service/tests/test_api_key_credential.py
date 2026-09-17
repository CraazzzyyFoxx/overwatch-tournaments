"""An API key as a first-class credential, across the four seams it travels.

Each seam gets the one property that used to be missing there:

* ``rehydrate_user`` carries the credential's own identity into a worker, so a
  keyed request stops being indistinguishable from a browser session downstream.
* ``record_audit`` names the key in ``actor_label`` — the whole of "who did this,
  and with what", with no new column and nothing for its 100+ call sites to pass.
* ``resolve_active_principal`` accepts a key where ``resolve_active_user`` must
  keep refusing one, and rejects exactly what the gateway's own validation does.
* the two subscribers that opt in (``get_me``, ``api_key.self``) hold the
  key/session asymmetry: a key may ask who it is, a session has no current key.

The transport tests stub the resolver rather than re-driving it: the resolver has
its own tests above them, and a subscriber's job is only the wiring.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models.platform.audit import AuditLog  # noqa: E402
from shared.rpc.identity import api_key_label, credential_type, rehydrate_user  # noqa: E402
from shared.services.audit import record_audit  # noqa: E402
from src import models, schemas  # noqa: E402
from src.core import db  # noqa: E402
from src.rpc import api_keys as api_keys_rpc  # noqa: E402
from src.rpc import auth as auth_rpc  # noqa: E402
from src.services.api_keys import api_keys  # noqa: E402
from src.services.auth import auth  # noqa: E402
from src.services.auth_users import auth_users  # noqa: E402
from src.services.token_validation import token_validation  # noqa: E402
from tests._fakes import CapturingBroker as _CapturingBroker  # noqa: E402
from tests._fakes import FakeSessionMaker as _SessionMaker  # noqa: E402
from tests._fakes import SilentLogger as _SilentLogger  # noqa: E402
from tests._fakes import handler as _handler  # noqa: E402
from tests._fakes import make_api_key_row  # noqa: E402
from tests._fakes import make_auth_user as _owner  # noqa: E402

_PUBLIC_ID = "publicid"
_SECRET = "secret-token"
_RAW_KEY = f"aqt_sk_{_PUBLIC_ID}_{_SECRET}"


# --- fixtures -------------------------------------------------------------


def _identity(*, keyed: bool) -> dict:
    """The gateway-injected payload, in both credential flavours."""
    payload: dict = {
        "user_id": 7,
        "username": "ada",
        "is_superuser": False,
        "is_active": True,
        "workspaces": [
            {"workspace_id": 11, "rbac_roles": [], "rbac_permissions": [{"resource": "team", "action": "create"}]}
        ],
    }
    if keyed:
        payload["credential_type"] = "api_key"
        payload["api_key"] = {
            "id": 123,
            "public_id": _PUBLIC_ID,
            "workspace_id": 11,
            "scopes": ["team.create"],
        }
    return payload


def _api_key_row(*, revoked_at=None, expires_at=None) -> models.ApiKey:
    return make_api_key_row(revoked_at=revoked_at, expires_at=expires_at)


class _FakeResult:
    def __init__(self, scalar) -> None:
        self._scalar = scalar

    def scalar_one_or_none(self):
        return self._scalar


class _FakeSession:
    """Serves ``execute()`` from a scripted queue, counts commits."""

    def __init__(self, scalars: list | None = None) -> None:
        self._scalars = list(scalars or [])
        self.added: list = []
        self.commit_calls = 0

    def add(self, row) -> None:
        self.added.append(row)

    async def execute(self, _stmt):
        if not self._scalars:
            raise AssertionError("Unexpected execute() call")
        return _FakeResult(self._scalars.pop(0))

    async def commit(self) -> None:
        self.commit_calls += 1


def _key_info(api_key_id: int = 123) -> schemas.TokenApiKeyInfo:
    return schemas.TokenApiKeyInfo(
        id=api_key_id,
        public_id=_PUBLIC_ID,
        workspace_id=11,
        scopes=["team.create"],
    )


async def _owner_authority(_session, user: models.AuthUser):
    """Stands in for the owner's real RBAC lookup: ``validate`` narrows the key's
    scopes against it, and building it for real would mean a live session cache."""
    payload = schemas.TokenPayload(
        sub=user.id,
        email=user.email,
        username=user.username,
        workspaces=[
            schemas.WorkspaceMembership(
                workspace_id=11,
                slug="main",
                rbac_roles=[],
                rbac_permissions=[{"resource": "team", "action": "create"}],
            )
        ],
    )
    return payload, rehydrate_user(payload.model_dump(mode="json"))


# --- rehydration ----------------------------------------------------------


def test_rehydrate_user_carries_the_credential_and_the_keys_identity() -> None:
    """Without this every worker but balancer saw a keyed call as a session."""
    user = rehydrate_user(_identity(keyed=True))

    assert credential_type(user) == "api_key"
    assert api_key_label(user) == f"api key: {_PUBLIC_ID}"
    assert user._api_key_id == 123
    assert user._api_key_workspace_id == 11
    assert user._api_key_scopes == ["team.create"]
    # The key narrows the owner; it never impersonates a different account.
    assert user.id == 7
    assert user.has_workspace_permission(11, "team", "create") is True


def test_rehydrate_user_reports_a_session_for_a_payload_without_a_credential_block() -> None:
    """Behaviour for the ~100 existing session call sites must not move."""
    user = rehydrate_user(_identity(keyed=False))

    assert credential_type(user) == "access_token"
    assert api_key_label(user) is None


@pytest.mark.parametrize("raw_type", [None, "", "cookie", 42, ["api_key"], {"api_key": True}])
def test_credential_type_reads_an_unknown_value_as_a_session(raw_type: object) -> None:
    """A corrupt payload must fail towards the narrower principal: only an API
    key ever unlocks key-scoped behaviour, so "session" is the safe wrong answer."""
    payload = _identity(keyed=True)
    payload["credential_type"] = raw_type

    user = rehydrate_user(payload)

    assert credential_type(user) == "access_token"
    assert api_key_label(user) is None


def test_api_key_label_ignores_a_credential_block_without_a_public_id() -> None:
    payload = _identity(keyed=True)
    payload["api_key"] = {"id": 123, "workspace_id": 11}

    assert api_key_label(rehydrate_user(payload)) is None


# --- audit attribution ----------------------------------------------------


def _record(actor) -> AuditLog:
    session = _FakeSession()
    row = asyncio.run(
        record_audit(
            session,
            action="team.create",
            source="admin",
            actor=actor,
            actor_label=getattr(actor, "username", None),
            workspace_id=11,
        )
    )
    assert session.added == [row]
    return row


def test_audit_row_names_the_api_key_the_actor_acted_through() -> None:
    row = _record(rehydrate_user(_identity(keyed=True)))

    # The account is still the actor — the suffix says which of its credentials.
    assert row.actor_auth_user_id == 7
    assert row.actor_label == f"ada (api key: {_PUBLIC_ID})"
    assert row.source == "api_key"


def test_audit_row_is_unchanged_for_a_session_actor() -> None:
    row = _record(rehydrate_user(_identity(keyed=False)))

    assert row.actor_auth_user_id == 7
    assert row.actor_label == "ada"
    assert row.source == "admin"


def test_audit_row_for_a_machine_actor_stays_actorless() -> None:
    session = _FakeSession()

    row = asyncio.run(record_audit(session, action="team.sync", source="scheduler"))

    assert row.actor_auth_user_id is None
    assert row.actor_label is None


def test_audit_actor_label_clips_the_name_and_keeps_the_credential() -> None:
    """``actor_label`` is ``String(255)``. Which key acted is the new information
    the suffix exists to carry, so the name is what gives way — never the key."""
    user = rehydrate_user(_identity(keyed=True))
    user.username = "n" * 400

    row = _record(user)

    assert len(row.actor_label) <= 255
    assert row.actor_label.endswith(f" (api key: {_PUBLIC_ID})")


def test_audit_label_falls_back_to_the_credential_when_the_name_is_missing() -> None:
    user = rehydrate_user(_identity(keyed=True))
    user.username = None

    assert _record(user).actor_label == f"api key: {_PUBLIC_ID}"


# --- resolve_active_principal --------------------------------------------


def test_resolve_active_principal_accepts_an_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    row = _api_key_row()
    session = _FakeSession([row])
    monkeypatch.setattr(api_keys, "_owner_authority", _owner_authority)

    async def get_identity(_session, user_id: int, **_kwargs) -> models.AuthUser:
        assert user_id == 7
        return _owner()

    monkeypatch.setattr(auth_users, "get_identity", get_identity)

    user, api_key = asyncio.run(token_validation.resolve_active_principal(session, _RAW_KEY))

    assert user.id == 7
    assert api_key is not None
    assert (api_key.id, api_key.public_id, api_key.workspace_id) == (123, _PUBLIC_ID, 11)
    assert api_key.scopes == ["team.create"]


@pytest.mark.parametrize(
    ("row", "raw_token"),
    [
        (_api_key_row(revoked_at=datetime.now(UTC)), _RAW_KEY),
        (_api_key_row(expires_at=datetime.now(UTC) - timedelta(seconds=1)), _RAW_KEY),
        (_api_key_row(), f"aqt_sk_{_PUBLIC_ID}_wrong-secret"),
    ],
)
def test_resolve_active_principal_rejects_a_revoked_expired_or_forged_key(
    monkeypatch: pytest.MonkeyPatch,
    row: models.ApiKey,
    raw_token: str,
) -> None:
    """One 401 for all three: which of them it was is not the caller's business."""
    session = _FakeSession([row])
    monkeypatch.setattr(api_keys, "_owner_authority", _owner_authority)

    async def unreachable(*_args, **_kwargs):
        raise AssertionError("owner must not be loaded for a rejected key")

    monkeypatch.setattr(auth_users, "get_identity", unreachable)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(token_validation.resolve_active_principal(session, raw_token))

    assert exc_info.value.status_code == 401
    assert session.commit_calls == 0


def test_resolve_active_principal_delegates_a_bearer_token_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """A JWT must take the existing path, keeping its 403-on-inactive contract."""
    session = _FakeSession()
    expected = _owner()

    async def resolve_active_user(_session, raw_token: str) -> models.AuthUser:
        assert raw_token == "eyJhbGciOiJIUzI1NiJ9.payload.sig"
        return expected

    monkeypatch.setattr(token_validation, "resolve_active_user", resolve_active_user)

    user, api_key = asyncio.run(token_validation.resolve_active_principal(session, "eyJhbGciOiJIUzI1NiJ9.payload.sig"))

    assert user is expected
    assert api_key is None


def test_resolve_active_user_still_refuses_an_api_key() -> None:
    """The security boundary: everything behind ``resolve_active_user`` mutates a
    session, a credential or RBAC, so a key must never get through it."""
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(token_validation.resolve_active_user(_FakeSession(), _RAW_KEY))

    assert exc_info.value.status_code == 401


# --- subscribers ----------------------------------------------------------


def _run_handler(module, subject: str, principal, monkeypatch: pytest.MonkeyPatch) -> dict:
    session = _FakeSession()
    monkeypatch.setattr(db, "async_session_maker", _SessionMaker(session))

    async def resolve(_session, raw_token: str):
        assert raw_token == "credential"
        return principal

    monkeypatch.setattr(token_validation, "resolve_active_principal", resolve)
    return asyncio.run(_handler(module, subject)({"access_token": "credential"}, None))


def test_get_me_answers_an_api_key_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    async def get_me(_session, user_id: int):
        assert user_id == 7
        return SimpleNamespace(model_dump=lambda mode="json": {"id": user_id, "username": "ada"})

    monkeypatch.setattr(auth, "get_me", get_me)

    reply = _run_handler(auth_rpc, "rpc.identity.get_me", (_owner(), _key_info()), monkeypatch)

    assert reply == {"ok": True, "data": {"id": 7, "username": "ada"}}


def test_get_me_answers_a_session_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Widening the door must not close it on the credential that already used it."""

    async def get_me(_session, user_id: int):
        return SimpleNamespace(model_dump=lambda mode="json": {"id": user_id})

    monkeypatch.setattr(auth, "get_me", get_me)

    reply = _run_handler(auth_rpc, "rpc.identity.get_me", (_owner(), None), monkeypatch)

    assert reply == {"ok": True, "data": {"id": 7}}


def test_api_key_self_returns_the_calling_keys_own_descriptor(monkeypatch: pytest.MonkeyPatch) -> None:
    async def describe_self(_session, *, api_key_id: int):
        assert api_key_id == 123
        return api_keys.describe(_api_key_row())

    monkeypatch.setattr(api_keys, "describe_self", describe_self)

    reply = _run_handler(api_keys_rpc, "rpc.identity.api_key.self", (_owner(), _key_info()), monkeypatch)

    assert reply["ok"] is True
    assert reply["data"]["id"] == 123
    assert reply["data"]["public_id"] == _PUBLIC_ID
    assert reply["data"]["name"] == "Balancer API"
    assert reply["data"]["scopes"] == ["team.create"]


def test_api_key_self_rejects_a_session_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """A browser session has no "current key", so there is nothing to describe."""

    async def unreachable(*_args, **_kwargs):
        raise AssertionError("no key to describe")

    monkeypatch.setattr(api_keys, "describe_self", unreachable)

    reply = _run_handler(api_keys_rpc, "rpc.identity.api_key.self", (_owner(), None), monkeypatch)

    assert reply == {"ok": False, "error": {"code": "forbidden", "message": "API key credential required"}}


_KEY_CRUD_SUBJECTS = (
    "rpc.identity.list_api_keys",
    "rpc.identity.create_api_key",
    "rpc.identity.update_api_key",
    "rpc.identity.revoke_api_key",
    "rpc.identity.api_key.quota_set",
    "rpc.identity.api_key.quota_usage",
)

#: Reachable *with* a key, and read-only: what am I, and what budget do I have.
_KEY_SELF_SUBJECTS = ("rpc.identity.api_key.self", "rpc.identity.api_key.self_quota")


def test_api_key_management_stays_jwt_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole point of the narrow door: a key that could mint a sibling or
    extend its own life is not workspace-scoped in any meaningful sense."""
    broker = _CapturingBroker()
    api_keys_rpc.register(broker, _SilentLogger())

    assert set(broker.handlers) == {*_KEY_CRUD_SUBJECTS, *_KEY_SELF_SUBJECTS}

    resolved: list[str] = []

    async def jwt_only(_logger, _token, _op, **_kwargs) -> dict:
        resolved.append("with_active_user")
        return {"ok": True, "data": None}

    async def forbidden(*_args, **_kwargs) -> dict:
        raise AssertionError("API-key management must not accept an API key")

    monkeypatch.setattr(api_keys_rpc.c, "with_active_user", jwt_only)
    monkeypatch.setattr(api_keys_rpc.c, "with_active_principal", forbidden)

    for subject in _KEY_CRUD_SUBJECTS:
        asyncio.run(broker.handlers[subject]({"access_token": "credential"}, None))

    assert resolved == ["with_active_user"] * len(_KEY_CRUD_SUBJECTS)
