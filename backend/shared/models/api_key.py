from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.auth_user import AuthUser
    from shared.models.workspace import Workspace

__all__ = ("ApiKey",)


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
    scopes_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    limits_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    config_policy_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")
    expires_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[db.DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[AuthUser] = relationship()
    workspace: Mapped[Workspace] = relationship()
