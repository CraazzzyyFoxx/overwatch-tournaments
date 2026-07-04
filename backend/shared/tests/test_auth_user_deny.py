"""Unit tests for the per-user deny overlay (negative RBAC) on AuthUser."""

from shared.models.identity.auth_user import AuthUser


def _user(*, superuser=False, permissions=None, denies=None) -> AuthUser:
    u = AuthUser()
    u.is_superuser = superuser
    u.set_rbac_cache(
        role_names=[],
        permissions=permissions or [],
        denies=denies or [],
    )
    return u


def test_deny_blocks_granted_permission() -> None:
    u = _user(
        permissions=[{"resource": "tournament", "action": "update"}],
        denies=[{"resource": "tournament", "action": "update"}],
    )
    assert u.has_permission("tournament", "update") is False


def test_deny_overrides_superuser_for_exact_action_only() -> None:
    u = _user(superuser=True, denies=[{"resource": "account", "action": "avatar"}])
    # Exact denied action is blocked even for a superuser...
    assert u.has_permission("account", "avatar") is False
    assert u.is_denied("account", "avatar") is True
    assert u.can_capability("account", "avatar") is False
    # ...but everything else still bypasses.
    assert u.has_permission("tournament", "read") is True
    assert u.can_capability("account", "social") is True


def test_capability_allowed_by_default_without_deny() -> None:
    u = _user()
    assert u.can_capability("account", "avatar") is True
    assert u.is_denied("account", "avatar") is False


def test_deny_is_exact_match_no_wildcard_expansion() -> None:
    # A deny on a specific action must NOT block a different action of the resource.
    u = _user(
        permissions=[{"resource": "*", "action": "*"}],
        denies=[{"resource": "account", "action": "avatar"}],
    )
    assert u.has_permission("account", "avatar") is False
    assert u.has_permission("account", "social") is True
