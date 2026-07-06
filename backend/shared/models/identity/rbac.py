"""
RBAC (Role-Based Access Control) models
"""

from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, String, Table, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.identity.auth_user import AuthUser
    from shared.models.tenancy.workspace import Workspace

__all__ = ("Role", "Permission", "UserPermissionDeny", "user_roles", "role_permissions")


# Association table for many-to-many relationship between users and roles
user_roles = Table(
    "user_roles",
    db.Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("auth.user.id", ondelete="CASCADE"), nullable=False),
    Column("role_id", Integer, ForeignKey("auth.roles.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", db.DateTime(timezone=True), server_default=text("now()"), nullable=False),
    # FK indexes created CONCURRENTLY by dbarch01 (permission resolution and
    # user/role CASCADE deletes previously seq-scanned this table).
    Index("ix_user_roles_user_id", "user_id"),
    Index("ix_user_roles_role_id", "role_id"),
    schema="auth",
)


class Role(db.TimeStampIntegerMixin):
    """Role model for RBAC"""

    __tablename__ = "roles"
    __table_args__ = (
        Index(
            "uq_roles_name_global",
            "name",
            unique=True,
            postgresql_where=text("workspace_id IS NULL"),
        ),
        Index(
            "uq_roles_name_workspace",
            "name",
            "workspace_id",
            unique=True,
            postgresql_where=text("workspace_id IS NOT NULL"),
        ),
        {"schema": "auth"},
    )

    name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Relations
    users: Mapped[list["AuthUser"]] = relationship(secondary=user_roles, back_populates="roles")
    permissions: Mapped[list["Permission"]] = relationship(secondary="auth.role_permissions", back_populates="roles")
    workspace: Mapped["Workspace | None"] = relationship()

    def __repr__(self):
        return f"<Role id={self.id} name={self.name}>"


class Permission(db.TimeStampIntegerMixin):
    """Permission model for RBAC"""

    __tablename__ = "permissions"
    __table_args__ = ({"schema": "auth"},)

    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    resource: Mapped[str] = mapped_column(String(100), nullable=False, index=True)  # e.g., "tournament", "user", "team"
    action: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # e.g., "create", "read", "update", "delete"
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)

    # Relations
    roles: Mapped[list["Role"]] = relationship(secondary="auth.role_permissions", back_populates="permissions")

    def __repr__(self):
        return f"<Permission id={self.id} name={self.name} resource={self.resource} action={self.action}>"


class UserPermissionDeny(db.TimeStampIntegerMixin):
    """Per-user negative RBAC: an explicit deny of a single permission.

    The grant-only RBAC (roles → permissions) cannot remove a capability from
    one person. A deny row overrides any grant — including the superuser/admin
    bypass — for that exact ``(permission.resource, permission.action)`` only
    (no wildcard expansion). Also used to switch off allow-by-default
    capabilities such as ``account.avatar`` / ``account.social``.
    """

    __tablename__ = "user_permission_deny"
    __table_args__ = (
        Index(
            "uq_user_permission_deny_user_perm_workspace",
            "user_id",
            "permission_id",
            sa.text("COALESCE(workspace_id, 0)"),
            unique=True,
        ),
        Index("ix_user_permission_deny_user_id", "user_id"),
        {"schema": "auth"},
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("auth.user.id", ondelete="CASCADE"), nullable=False)
    permission_id: Mapped[int] = mapped_column(ForeignKey("auth.permissions.id", ondelete="CASCADE"), nullable=False)
    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # FK added by dbarch01 (NOT VALID + VALIDATE); SET NULL keeps the deny row
    # alive when the operator's auth user is deleted.
    created_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text(), nullable=True)

    permission: Mapped["Permission"] = relationship()

    def __repr__(self):
        return f"<UserPermissionDeny user_id={self.user_id} permission_id={self.permission_id}>"


# Association table for many-to-many relationship between roles and permissions
role_permissions = Table(
    "role_permissions",
    db.Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("role_id", Integer, ForeignKey("auth.roles.id", ondelete="CASCADE"), nullable=False),
    Column("permission_id", Integer, ForeignKey("auth.permissions.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", db.DateTime(timezone=True), server_default=text("now()"), nullable=False),
    # FK indexes created CONCURRENTLY by dbarch01.
    Index("ix_role_permissions_role_id", "role_id"),
    Index("ix_role_permissions_permission_id", "permission_id"),
    schema="auth",
)
