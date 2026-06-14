"""
Generic OAuth models for multiple providers
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.auth_user import AuthUser

__all__ = ("OAuthConnection",)


class OAuthConnection(db.TimeStampIntegerMixin):
    """Generic OAuth connection for any provider"""

    __tablename__ = "oauth_connections"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_provider_user"),
        UniqueConstraint("auth_user_id", "provider", name="uq_user_provider"),
        {"schema": "auth"},
    )

    auth_user_id: Mapped[int] = mapped_column(ForeignKey("auth.user.id", ondelete="CASCADE"), nullable=False)

    # Provider information
    provider: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # 'discord', 'google', 'github', etc.
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)  # ID from the provider

    # User information from provider
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # OAuth tokens
    access_token: Mapped[str | None] = mapped_column(Text(), nullable=True)
    refresh_token: Mapped[str | None] = mapped_column(Text(), nullable=True)
    token_expires_at: Mapped[db.DateTime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)

    # Additional provider-specific data (JSON)
    provider_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Relations
    auth_user: Mapped["AuthUser"] = relationship(back_populates="oauth_connections")

    def __repr__(self):
        return f"<OAuthConnection id={self.id} provider={self.provider} user_id={self.auth_user_id}>"
