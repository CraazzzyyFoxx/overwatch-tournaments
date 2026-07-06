from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.identity.user import User

__all__ = (
    "SocialAccount",
    "SocialAccountVisibility",
)


class SocialAccount(db.TimeStampIntegerMixin):
    """Unified player social identity (battlenet/discord/twitch/boosty/vk/…).

    Consolidates the former ``battle_tag``/``discord``/``twitch``/``external_account``
    tables. ``provider_user_id`` + ``is_verified`` are set when the account is
    proven via OAuth; visibility is layered through ``SocialAccountVisibility``.
    """

    __tablename__ = "social_account"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "username_normalized",
            name="uq_social_account_user_provider_handle",
        ),
        # One verified external subject maps to a single account (mirrors
        # auth.oauth_connections.uq_provider_user).
        Index(
            "uq_social_account_provider_subject",
            "provider",
            "provider_user_id",
            unique=True,
            postgresql_where=text("provider_user_id IS NOT NULL"),
        ),
        Index("ix_social_account_user_id", "user_id"),
        Index("ix_social_account_provider", "provider"),
        Index("ix_social_account_username_normalized", "username_normalized"),
        Index("ix_social_account_provider_user_id", "provider_user_id"),
        # dbarch01: uq_social_account_user_provider_handle does not dedupe rows
        # with NULL username_normalized (every NULL is distinct), so this
        # partial unique index closes the bypass, keyed on the raw handle.
        # NB: dbarch01 only creates it after verifying no duplicate NULL-case
        # rows exist (otherwise it warns and defers to manual cleanup).
        Index(
            "uq_social_account_user_provider_handle_nullnorm",
            "user_id",
            "provider",
            text("lower(btrim(username))"),
            unique=True,
            postgresql_where=text("username_normalized IS NULL"),
        ),
        {"schema": "players"},
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("players.user.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(64))
    username: Mapped[str] = mapped_column(String(255))
    username_normalized: Mapped[str | None] = mapped_column(String(255), nullable=True)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    provider_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean(), server_default="false")
    is_primary: Mapped[bool] = mapped_column(Boolean(), server_default="false")

    user: Mapped["User"] = relationship(back_populates="social_accounts")
    visibilities: Mapped[list["SocialAccountVisibility"]] = relationship(
        back_populates="account",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SocialAccountVisibility(db.TimeStampIntegerMixin):
    """Scope in which a ``SocialAccount`` is shown.

    Presence of a row means visible in that scope. ``workspace_id IS NULL`` is
    the global scope (player profile / site-wide); a non-null ``workspace_id``
    means visible within that workspace's surfaces.
    """

    __tablename__ = "social_account_visibility"
    __table_args__ = (
        Index(
            "uq_social_visibility_global",
            "account_id",
            unique=True,
            postgresql_where=text("workspace_id IS NULL"),
        ),
        Index(
            "uq_social_visibility_workspace",
            "account_id",
            "workspace_id",
            unique=True,
            postgresql_where=text("workspace_id IS NOT NULL"),
        ),
        Index("ix_social_account_visibility_account_id", "account_id"),
        Index("ix_social_account_visibility_workspace_id", "workspace_id"),
        {"schema": "players"},
    )

    account_id: Mapped[int] = mapped_column(ForeignKey("players.social_account.id", ondelete="CASCADE"))
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspace.id", ondelete="CASCADE"), nullable=True)

    account: Mapped["SocialAccount"] = relationship(back_populates="visibilities")
