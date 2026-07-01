from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.oauth import OAuthConnection
    from shared.models.rbac import Role
    from shared.models.user import User

__all__ = ("AuthUser", "RefreshToken")

ADMIN_EQUIVALENT_ROLE_NAMES = {"admin"}
ADMIN_PANEL_ROLE_NAMES = {"admin", "tournament_organizer", "moderator"}


def _permission_grants_admin_panel_access(resource: str, action: str) -> bool:
    return (resource == "*" and action == "*") or action != "read"


def _permission_payload_grants_admin_panel_access(permissions: list[dict[str, str]]) -> bool:
    for permission in permissions:
        if not isinstance(permission, dict):
            continue
        resource = permission.get("resource", "")
        action = permission.get("action", "")
        if _permission_grants_admin_panel_access(resource, action):
            return True
    return False


class AuthUser(db.TimeStampIntegerMixin):
    """User model for authentication"""

    __tablename__ = "user"
    __table_args__ = ({"schema": "auth"},)

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    username: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    is_superuser: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    is_verified: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)

    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    player: Mapped["User | None"] = relationship(
        back_populates="auth_user", uselist=False, viewonly=False,
    )
    roles: Mapped[list["Role"]] = relationship(secondary="auth.user_roles", back_populates="users", lazy="selectin")
    oauth_connections: Mapped[list["OAuthConnection"]] = relationship(
        back_populates="auth_user", cascade="all, delete-orphan", lazy="selectin"
    )

    def set_rbac_cache(
        self,
        role_names: list[str],
        permissions: list[dict[str, str]],
        workspaces: list[dict] | None = None,
        workspace_rbac: dict[int, dict] | None = None,
        denies: list[dict[str, str]] | None = None,
    ) -> None:
        """Attach RBAC data from auth-service /validate response.

        When set, has_role() and has_permission() use these cached
        values instead of traversing ORM relationships, avoiding an
        extra DB query and ensuring instant propagation of changes.

        ``denies`` is a per-user deny overlay (negative RBAC): an exact
        (resource, action) deny overrides any grant — including the
        superuser/admin bypass — for that action only.

        Stored as plain instance attributes (not Mapped) so SQLAlchemy
        ignores them.
        """
        object.__setattr__(self, "_cached_role_names", role_names)
        object.__setattr__(self, "_cached_permissions", permissions)
        object.__setattr__(self, "_cached_workspaces", workspaces or [])
        object.__setattr__(self, "_cached_workspace_rbac", workspace_rbac or {})
        object.__setattr__(self, "_cached_denies", denies or [])

    def is_denied(self, resource: str, action: str) -> bool:
        """Per-user deny overlay: True when this exact (resource, action) is
        explicitly denied for the user. Exact match only — never wildcard."""
        for deny in getattr(self, "_cached_denies", None) or []:
            if deny.get("resource") == resource and deny.get("action") == action:
                return True
        return False

    def can_capability(self, resource: str, action: str) -> bool:
        """Allow-by-default capability (e.g. ``account.avatar``): every
        authenticated user may do it unless an explicit deny removes it."""
        return not self.is_denied(resource, action)

    def get_workspace_ids(self) -> list[int]:
        """Return workspace IDs the user is a member of."""
        cached = getattr(self, "_cached_workspaces", None)
        if cached is not None:
            return [w["workspace_id"] for w in cached if "workspace_id" in w]
        return []

    def is_workspace_member(self, workspace_id: int) -> bool:
        """Check if user is a member of a specific workspace."""
        if self.is_superuser:
            return True
        return workspace_id in self.get_workspace_ids()

    def get_workspace_role(self, workspace_id: int) -> str | None:
        """Get user's role in a specific workspace."""
        if self.is_superuser:
            return "owner"
        cached = getattr(self, "_cached_workspaces", None)
        if cached is not None:
            for w in cached:
                if w.get("workspace_id") == workspace_id:
                    return w.get("role")
        return None

    def is_workspace_admin(self, workspace_id: int) -> bool:
        """Check if user has workspace-scoped wildcard access."""
        if self.is_superuser:
            return True
        return self.has_workspace_permission(workspace_id, "*", "*")

    def has_workspace_permission(self, workspace_id: int, resource: str, action: str) -> bool:
        """Check permission within a specific workspace context.

        Checks: superuser -> global admin role -> global permissions
        -> workspace-scoped permissions.
        """
        if self.is_denied(resource, action):
            return False
        if self.is_superuser or self._has_admin_equivalent_role():
            return True

        # Check global permissions first
        if self.has_permission(resource, action):
            return True

        # Check workspace-scoped permissions
        ws_rbac: dict = getattr(self, "_cached_workspace_rbac", None) or {}
        ws_data = ws_rbac.get(workspace_id)
        if ws_data:
            for p in ws_data.get("permissions", []):
                pr, pa = p.get("resource", ""), p.get("action", "")
                if (pr == resource or pr == "*") and (pa == action or pa == "*"):
                    return True

        for role in self.roles:
            if role.workspace_id != workspace_id:
                continue
            for permission in role.permissions:
                if (permission.resource == resource or permission.resource == "*") and (
                    permission.action == action or permission.action == "*"
                ):
                    return True

        return False

    def __repr__(self):
        return f"<AuthUser id={self.id} email={self.email}>"

    def _has_admin_equivalent_role(self) -> bool:
        cached_roles = getattr(self, "_cached_role_names", None)
        if cached_roles is not None:
            return any(role_name in ADMIN_EQUIVALENT_ROLE_NAMES for role_name in cached_roles)

        return any(
            role.name in ADMIN_EQUIVALENT_ROLE_NAMES and role.workspace_id is None
            for role in self.roles
        )

    def _has_admin_panel_role(self) -> bool:
        cached_roles = getattr(self, "_cached_role_names", None)
        if cached_roles is not None:
            return any(role_name in ADMIN_PANEL_ROLE_NAMES for role_name in cached_roles)

        return any(
            role.name in ADMIN_PANEL_ROLE_NAMES and role.workspace_id is None
            for role in self.roles
        )

    def _has_global_admin_panel_permission(self) -> bool:
        cached = getattr(self, "_cached_permissions", None)
        if cached is not None:
            return _permission_payload_grants_admin_panel_access(cached)

        for role in self.roles:
            if role.workspace_id is not None:
                continue
            for permission in role.permissions:
                if _permission_grants_admin_panel_access(permission.resource, permission.action):
                    return True
        return False

    def _has_workspace_admin_panel_permission(self, workspace_id: int | None = None) -> bool:
        ws_rbac: dict = getattr(self, "_cached_workspace_rbac", None) or {}
        if ws_rbac:
            workspace_payloads = (
                [ws_rbac.get(workspace_id)] if workspace_id is not None else ws_rbac.values()
            )
            for ws_data in workspace_payloads:
                if ws_data and _permission_payload_grants_admin_panel_access(ws_data.get("permissions", [])):
                    return True
            return False

        for role in self.roles:
            if role.workspace_id is None:
                continue
            if workspace_id is not None and role.workspace_id != workspace_id:
                continue
            for permission in role.permissions:
                if _permission_grants_admin_panel_access(permission.resource, permission.action):
                    return True
        return False

    def has_admin_panel_access(self, workspace_id: int | None = None) -> bool:
        if self.is_superuser or self._has_admin_panel_role():
            return True
        return self._has_global_admin_panel_permission() or self._has_workspace_admin_panel_permission(workspace_id)

    def has_permission(self, resource: str, action: str) -> bool:
        """Check if user has a specific permission"""
        # Negative RBAC: an explicit per-user deny overrides any grant,
        # including the superuser/admin bypass, for this exact action.
        if self.is_denied(resource, action):
            return False
        if self.is_superuser or self._has_admin_equivalent_role():
            return True

        cached = getattr(self, "_cached_permissions", None)
        if cached is not None:
            for p in cached:
                pr, pa = p.get("resource", ""), p.get("action", "")
                if (pr == resource or pr == "*") and (pa == action or pa == "*"):
                    return True
            return False

        for role in self.roles:
            if role.workspace_id is not None:
                continue
            for permission in role.permissions:
                if permission.resource == resource and permission.action == action:
                    return True
                if permission.resource == "*" and permission.action == action:
                    return True
                if permission.resource == resource and permission.action == "*":
                    return True
                if permission.resource == "*" and permission.action == "*":
                    return True

        return False

    def has_role(self, role_name: str) -> bool:
        """Check if user has a specific role"""
        if self.is_superuser:
            return True
        cached_roles = getattr(self, "_cached_role_names", None)
        if cached_roles is not None:
            return role_name in cached_roles
        return any(role.name == role_name and role.workspace_id is None for role in self.roles)


class RefreshToken(db.TimeStampIntegerMixin):
    """Refresh token model for JWT authentication"""

    __tablename__ = "refresh_token"
    __table_args__ = ({"schema": "auth"},)

    token: Mapped[str] = mapped_column(Text(), unique=True, index=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("auth.user.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[UUID] = mapped_column(Uuid(), index=True, nullable=False)
    session_started_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(db.DateTime(timezone=True), nullable=False)
    is_revoked: Mapped[bool] = mapped_column(Boolean(), default=False, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

    # User agent and IP for security
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # Relations
    user: Mapped["AuthUser"] = relationship(back_populates="refresh_tokens")

    def __repr__(self):
        return f"<RefreshToken id={self.id} user_id={self.user_id}>"
