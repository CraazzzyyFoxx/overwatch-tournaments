from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.identity.auth_user import AuthUser
    from shared.models.identity.social import SocialAccount

__all__ = ("User",)


class User(db.TimeStampIntegerMixin):
    __tablename__ = "user"
    __table_args__ = (
        # Trigram GIN index so user-name search (`name ILIKE '%q%'` and the
        # pg_trgm `%` operator) uses a Bitmap Index Scan instead of a Seq Scan.
        Index(
            "ix_user_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        {"schema": "players"},
    )

    name: Mapped[str] = mapped_column(String(), unique=True)
    avatar_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # 1:0..1 link to the auth identity (auth.user). Nullable + unique so a
    # player may exist without an auth account, and an auth account links to
    # at most one player.
    auth_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
        index=True,
    )
    auth_user: Mapped["AuthUser | None"] = relationship(back_populates="player")

    # Unified player identities (battlenet / discord / twitch / boosty / …).
    # Replaced the former battle_tag / discord / twitch / external_account tables.
    social_accounts: Mapped[list["SocialAccount"]] = relationship(
        back_populates="user", uselist=True, passive_deletes=True
    )

    def __repr__(self):
        return f"<User id={self.id} name={self.name}>"
