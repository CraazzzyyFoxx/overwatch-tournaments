from sqlalchemy import Boolean, ForeignKey, String, BigInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

__all__ = ("TournamentDiscordChannel",)


class TournamentDiscordChannel(db.TimeStampIntegerMixin):
    """Configuration for Discord log collection channels per tournament"""
    __tablename__ = "discord_channel"
    __table_args__ = ({"schema": "log_processing"},)

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"),
        nullable=False,
        unique=True
    )
    guild_id: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    channel_id: Mapped[int] = mapped_column(BigInteger(), nullable=False, unique=True, index=True)
    channel_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), default=True, nullable=False)
    
    # Relations
    tournament: Mapped["Tournament"] = relationship()

    def __repr__(self):
        return f"<TournamentDiscordChannel tournament_id={self.tournament_id} channel_id={self.channel_id}>"
