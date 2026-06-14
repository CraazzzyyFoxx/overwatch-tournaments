import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

if TYPE_CHECKING:
    from shared.models.encounter import Encounter
    from shared.models.tournament import Tournament
    from shared.models.user import User

__all__ = ("LogProcessingRecord", "LogProcessingStatus", "LogProcessingSource")


class LogProcessingStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


class LogProcessingSource(str, enum.Enum):
    upload = "upload"
    discord = "discord"
    manual = "manual"


class LogProcessingRecord(db.TimeStampIntegerMixin):
    """Tracks the processing state and uploader info for each match log file."""

    __tablename__ = "record"
    __table_args__ = ({"schema": "log_processing"},)

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[LogProcessingStatus] = mapped_column(
        Enum(LogProcessingStatus, name="log_processing_status"),
        nullable=False,
        default=LogProcessingStatus.pending,
    )
    source: Mapped[LogProcessingSource] = mapped_column(
        Enum(LogProcessingSource, name="log_processing_source"),
        nullable=False,
        default=LogProcessingSource.manual,
    )
    uploader_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.user.id", ondelete="SET NULL"),
        nullable=True,
    )
    attached_encounter_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.encounter.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Relations
    tournament: Mapped["Tournament"] = relationship(lazy="selectin")
    uploader: Mapped["User | None"] = relationship(lazy="selectin", foreign_keys=[uploader_id])
    attached_encounter: Mapped["Encounter | None"] = relationship(lazy="selectin", foreign_keys=[attached_encounter_id])

    def __repr__(self) -> str:
        return f"<LogProcessingRecord tournament_id={self.tournament_id} filename={self.filename} status={self.status}>"
