from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Index, SmallInteger, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("WorkspaceEvent",)


class WorkspaceEvent(db.Base):
    __tablename__ = "workspace_event"
    __table_args__ = (
        Index("ix_realtime_workspace_event_topic_id", "topic", "id"),
        Index("ix_realtime_workspace_event_occurred_at", "occurred_at"),
        {"schema": "realtime"},
    )

    id: Mapped[int] = mapped_column(BigInteger(), primary_key=True)
    topic: Mapped[str] = mapped_column(Text(), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    workspace_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True, index=True)
    tournament_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True, index=True)
    schema_version: Mapped[int] = mapped_column(SmallInteger(), nullable=False, server_default="1")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB(), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
