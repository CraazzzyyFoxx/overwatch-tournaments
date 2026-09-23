"""Rehydrate an AuthUser from the gateway-injected identity payload.

The Go gateway validates the JWT locally and resolves RBAC (via identity-svc),
then injects the resolved identity into each RPC request. Headless workers
rehydrate a transient ``AuthUser`` from that payload and check permissions
imperatively — no token parsing, no DB lookup.

Trust model: the RPC subscriber is reachable only over RabbitMQ from the gateway,
so the injected identity is implicitly trusted (no external path can forge it).

The payload shape matches what identity-svc's ``validate_token`` returns and what
the per-service ``_resolve_user_from_db`` consumes:

    {
      "user_id": int,            # or "sub"
      "is_superuser": bool,
      "is_active": bool,
      "roles": [str, ...],                       # global role names
      "permissions": [{"resource","action"}],    # global permissions
      "workspaces": [                            # membership
        {"workspace_id": int,
         "rbac_roles": [...], "rbac_permissions": [{"resource","action"}]}
      ],
      "credential_type": "access_token" | "api_key" | "discord",
      "api_key": {"id","public_id","workspace_id","scopes"} | None
    }

The last two describe the *credential*, not the account: an API key is owned by a
real user, so ``user_id`` is the owner either way and only ``credential_type``
tells a keyed request apart from that same account's browser session. Read them
through ``credential_type``/``api_key_label``, never the raw attributes.
"""

from __future__ import annotations

from typing import Any

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser

__all__ = (
    "rehydrate_user",
    "rehydrate_user_optional",
    "ensure_workspace_permission",
    "ensure_admin_panel_access",
    "credential_type",
    "api_key_label",
    "MissingIdentityError",
)

# Mirrors ``TokenPayload.credential_type``. Anything else on the wire is a
# corrupt payload, and reading it as a session is the safe way to be wrong: a
# session is the narrower principal here, since only API keys unlock key-scoped
# behaviour. ``discord`` is the bot acting for the account that linked the
# Discord user who clicked (``rpc.identity.discord_identity``): a session in
# every permission sense, told apart only so the journal can say so.
_CREDENTIAL_TYPES = frozenset({"access_token", "api_key", "discord"})


class MissingIdentityError(Exception):
    """Raised when an authenticated RPC method gets no identity payload."""


def _payload_user_id(identity: dict[str, Any]) -> int:
    raw = identity.get("user_id", identity.get("sub"))
    try:
        user_id = int(raw)
    except (TypeError, ValueError) as exc:
        raise MissingIdentityError("identity has no valid user_id") from exc
    if user_id <= 0:
        raise MissingIdentityError("identity has no valid user_id")
    return user_id


def rehydrate_user(identity: dict[str, Any] | None) -> AuthUser:
    """Build a transient AuthUser whose permission checks use the cached RBAC.

    No DB access: every AuthUser permission method falls back to the in-memory
    cache set here and only touches ORM relationships when the cache is absent.
    """
    if not identity or not isinstance(identity, dict):
        raise MissingIdentityError("no identity payload")

    user = AuthUser()
    user.id = _payload_user_id(identity)
    user.is_superuser = bool(identity.get("is_superuser", False))
    user.is_active = bool(identity.get("is_active", True))
    # ``TokenPayload.username`` always rides the envelope, and the audit log needs
    # it as an actor label that stays readable after the account is deleted. Left
    # unset when absent (hand-built identities in tests) rather than blanked.
    username = identity.get("username")
    if isinstance(username, str) and username:
        user.username = username

    workspaces = identity.get("workspaces") or []
    workspace_rbac: dict[int, dict] = {}
    for ws in workspaces:
        ws_id = ws.get("workspace_id")
        if ws_id is not None:
            workspace_rbac[int(ws_id)] = {
                "roles": ws.get("rbac_roles", []),
                "permissions": ws.get("rbac_permissions", []),
            }
    user.set_rbac_cache(
        role_names=identity.get("roles", []),
        permissions=identity.get("permissions", []),
        workspaces=workspaces,
        workspace_rbac=workspace_rbac,
        denies=identity.get("denies", []),
    )
    _stamp_credential(user, identity)
    return user


def _stamp_credential(user: AuthUser, identity: dict[str, Any]) -> None:
    """Carry the credential's own identity onto the transient user.

    ``object.__setattr__`` because none of these are Mapped columns — the same
    escape hatch ``set_rbac_cache`` uses for its cache, and the attribute names
    balancer's own resolver already stamps, so a rehydrated principal reads
    identically to one balancer built from the raw payload.

    Until this existed, every worker but balancer dropped both keys, so an API
    key was indistinguishable from a browser session downstream — including in
    the audit journal, where "who did this" silently lost "with what".
    """
    object.__setattr__(user, "_credential_type", _normalize_credential_type(identity.get("credential_type")))

    api_key = identity.get("api_key")
    if not isinstance(api_key, dict):
        return
    # Deliberately not ``limits``: that is balancer's own quota input, and it
    # stamps it itself from the same payload.
    object.__setattr__(user, "_api_key_id", api_key.get("id"))
    object.__setattr__(user, "_api_key_public_id", api_key.get("public_id"))
    object.__setattr__(user, "_api_key_workspace_id", api_key.get("workspace_id"))
    object.__setattr__(user, "_api_key_scopes", list(api_key.get("scopes") or []))


def _normalize_credential_type(value: Any) -> str:
    """One place decides what a credential type is, on the way in and on the way out.

    ``isinstance`` before the membership test, not just for tidiness: an
    unhashable value on the wire (a list, a dict) makes a bare ``in`` raise, and
    a malformed payload must degrade to "session", not to a 500.
    """
    return value if isinstance(value, str) and value in _CREDENTIAL_TYPES else "access_token"


def credential_type(user: AuthUser) -> str:
    """Which credential authenticated this principal.

    Always answers, so a caller branches on a value rather than on the absence
    of an attribute: a user built by any other path (a DB load, a test fixture)
    is a session, because only an API key is ever stamped as one.
    """
    return _normalize_credential_type(getattr(user, "_credential_type", None))


def api_key_label(user: AuthUser) -> str | None:
    """Human-readable name of the key the caller acted through, else ``None``.

    The public id and nothing else: it names the key without authenticating as
    it, so this is safe to write into a log line or an audit row.
    """
    if credential_type(user) != "api_key":
        return None
    public_id = getattr(user, "_api_key_public_id", None)
    if not isinstance(public_id, str) or not public_id:
        return None
    return f"api key: {public_id}"


def rehydrate_user_optional(identity: dict[str, Any] | None) -> AuthUser | None:
    """Like ``rehydrate_user`` but returns ``None`` for anonymous callers.

    The gateway injects ``identity`` only when a valid token is present on an
    AuthOptional route, so a falsy payload means anonymous — never an error.
    Use this on public reads that must still recognise a logged-in viewer.
    """
    if not identity:
        return None
    return rehydrate_user(identity)


def ensure_workspace_permission(user: AuthUser, workspace_id: int, resource: str, action: str) -> None:
    """Imperative form of the route ``_require_workspace_permission`` dependency."""
    if not user.has_workspace_permission(workspace_id, resource, action):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied for workspace {workspace_id}: {resource}.{action} required",
        )


def ensure_admin_panel_access(user: AuthUser, workspace_id: int | None = None) -> None:
    """Imperative form of the router-level ``require_admin_panel_access`` gate."""
    if not user.has_admin_panel_access(workspace_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin panel access required",
        )
