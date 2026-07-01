"""Unit tests: workspace-scoped deny overlay on AuthUser (Phase A, Task 8).

A deny entry now optionally carries ``workspace_id``:
  - ``workspace_id=None`` (or key absent, for back-compat with pre-Task-8 JWTs)
    -> global deny, blocks the capability in every workspace.
  - ``workspace_id=<int>`` -> scoped deny, blocks only that workspace.

Pure logic over ``_cached_denies`` (set via ``set_rbac_cache``) - no DB access.
"""

from shared.models.auth_user import AuthUser


def _mk(u: AuthUser, denies: list[dict]) -> None:
    u.set_rbac_cache(role_names=[], permissions=[], workspace_rbac={}, denies=denies)


def test_global_deny_blocks_all_workspaces() -> None:
    u = AuthUser()
    _mk(u, [{"resource": "registration", "action": "self_register", "workspace_id": None}])
    assert u.can_capability("registration", "self_register", workspace_id=1) is False
    assert u.can_capability("registration", "self_register", workspace_id=2) is False


def test_scoped_deny_blocks_only_its_workspace() -> None:
    u = AuthUser()
    _mk(u, [{"resource": "registration", "action": "self_register", "workspace_id": 1}])
    assert u.can_capability("registration", "self_register", workspace_id=1) is False
    assert u.can_capability("registration", "self_register", workspace_id=2) is True


def test_missing_workspace_id_treated_as_global() -> None:
    # Back-compat: a deny dict shaped like a pre-Task-8 JWT (no workspace_id key at all).
    u = AuthUser()
    _mk(u, [{"resource": "registration", "action": "self_register"}])
    assert u.can_capability("registration", "self_register", workspace_id=1) is False
    assert u.can_capability("registration", "self_register", workspace_id=2) is False


def test_scoped_deny_does_not_block_global_check() -> None:
    # A deny scoped to workspace 1 must not leak into the workspace-agnostic
    # (workspace_id=None) check used by has_permission()/is_denied() defaults.
    u = AuthUser()
    _mk(u, [{"resource": "registration", "action": "self_register", "workspace_id": 1}])
    assert u.can_capability("registration", "self_register") is True
    assert u.is_denied("registration", "self_register") is False


def test_is_denied_signature_accepts_workspace_id() -> None:
    u = AuthUser()
    _mk(u, [{"resource": "registration", "action": "self_register", "workspace_id": 1}])
    assert u.is_denied("registration", "self_register", workspace_id=1) is True
    assert u.is_denied("registration", "self_register", workspace_id=2) is False
