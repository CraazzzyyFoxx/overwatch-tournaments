from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.identity.auth_user import AuthUser
    from shared.models.tenancy.workspace import Workspace

__all__ = ("ApiKey", "ApiKeyScope")


class ApiKey(db.TimeStampIntegerMixin):
    """Workspace-scoped API key owned by an auth user."""

    __tablename__ = "api_key"
    __table_args__ = (
        Index("ix_api_key_owner_workspace", "auth_user_id", "workspace_id"),
        Index("ix_api_key_public_id_active", "public_id", "revoked_at"),
        {"schema": "auth"},
    )

    auth_user_id: Mapped[int] = mapped_column(ForeignKey("auth.user.id", ondelete="CASCADE"), index=True)
    workspace_id: Mapped[int] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), index=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    limits_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    expires_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[AuthUser] = relationship()
    workspace: Mapped[Workspace] = relationship()
    scopes: Mapped[list[ApiKeyScope]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ApiKeyScope.scope",
    )


class ApiKeyScope(db.Base):
    """One RBAC permission name granted to an API key."""

    __tablename__ = "api_key_scope"
    __table_args__ = ({"schema": "auth"},)

    api_key_id: Mapped[int] = mapped_column(
        ForeignKey("auth.api_key.id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)
