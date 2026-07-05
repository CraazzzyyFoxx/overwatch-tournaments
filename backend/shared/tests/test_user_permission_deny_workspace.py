"""Metadata tests: UserPermissionDeny becomes workspace-scoped (Phase A, Task 7).

``workspace_id IS NULL`` means a global deny; a concrete ``workspace_id`` means
the deny only applies within that workspace. The old plain unique constraint
over ``(user_id, permission_id)`` must be replaced by a workspace-aware unique
expression index (the deny-CHECK logic that consumes this lives in Task 8).
"""

from shared.models.identity.rbac import UserPermissionDeny


def test_user_permission_deny_has_nullable_workspace_fk():
    col = UserPermissionDeny.__table__.columns["workspace_id"]
    assert col.nullable is True
    fk = next(iter(col.foreign_keys))
    assert fk.column.table.name == "workspace"


def test_user_permission_deny_workspace_id_is_indexed():
    col = UserPermissionDeny.__table__.columns["workspace_id"]
    assert col.index is True


def test_old_plain_unique_constraint_is_gone():
    constraint_names = {
        c.name
        for c in UserPermissionDeny.__table__.constraints
        if c.__class__.__name__ == "UniqueConstraint"
    }
    assert "uq_user_permission_deny" not in constraint_names


def test_workspace_aware_unique_index_exists():
    index = next(
        (ix for ix in UserPermissionDeny.__table__.indexes
         if ix.name == "uq_user_permission_deny_user_perm_workspace"),
        None,
    )
    assert index is not None
    assert index.unique is True
    column_names = {c.name for c in index.columns if hasattr(c, "name")}
    assert {"user_id", "permission_id"}.issubset(column_names)
