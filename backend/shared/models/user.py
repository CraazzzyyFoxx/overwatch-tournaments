from sqlalchemy import ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

__all__ = (
    "User",
    "UserBattleTag",
    "UserDiscord",
    "UserExternalAccount",
    "UserTwitch",
)


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

    discord: Mapped[list["UserDiscord"]] = relationship(
        back_populates="user", uselist=True
    )
    battle_tag: Mapped[list["UserBattleTag"]] = relationship(
        back_populates="user", uselist=True
    )
    twitch: Mapped[list["UserTwitch"]] = relationship(
        back_populates="user", uselist=True
    )

    def __repr__(self):
        return f"<User id={self.id} name={self.name}>"


class UserDiscord(db.TimeStampIntegerMixin):
    __tablename__ = "discord"
    __table_args__ = ({"schema": "players"},)

    user_id: Mapped[int] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"))
    user: Mapped[User] = relationship()
    name: Mapped[str] = mapped_column(String(), unique=True, index=True)


class UserBattleTag(db.TimeStampIntegerMixin):
    __tablename__ = "battle_tag"
    __table_args__ = (
        # Trigram GIN index backing `search_by_name` (battle_tag ILIKE '%q%' and
        # the pg_trgm `%` operator) — turns its Seq Scan into an index scan.
        Index(
            "ix_battle_tag_battle_tag_trgm",
            "battle_tag",
            postgresql_using="gin",
            postgresql_ops={"battle_tag": "gin_trgm_ops"},
        ),
        {"schema": "players"},
    )

    user_id: Mapped[int] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"))
    user: Mapped[User] = relationship()
    name: Mapped[str] = mapped_column(String(), index=True)
    tag: Mapped[str] = mapped_column(String())
    battle_tag: Mapped[str] = mapped_column(String(), unique=True, index=True)


class UserTwitch(db.TimeStampIntegerMixin):
    __tablename__ = "twitch"
    __table_args__ = ({"schema": "players"},)

    user_id: Mapped[int] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"))
    user: Mapped[User] = relationship()
    name: Mapped[str] = mapped_column(String(), unique=True, index=True)


class UserExternalAccount(db.TimeStampIntegerMixin):
    """Generic external account link (boosty, vk, youtube, etc.)."""

    __tablename__ = "external_account"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "username", name="uq_external_account"),
        {"schema": "players"},
    )

    user_id: Mapped[int] = mapped_column(ForeignKey(User.id, ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    user: Mapped[User] = relationship()
