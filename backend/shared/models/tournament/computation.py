from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, BigInteger, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = (
    "TournamentComputationJob",
    "TournamentRecalculationState",
)


class TournamentComputationJob(db.TimeStampIntegerMixin):
    """Durable bracket/standings computation request."""

    __tablename__ = "computation_job"
    __table_args__ = (
        Index(
            "uq_tournament_computation_job_active_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("status IN ('pending', 'running')"),
        ),
        Index("ix_tournament_computation_job_status", "status"),
        Index("ix_tournament_computation_job_tournament_kind", "tournament_id", "kind"),
        {"schema": "tournament"},
    )

    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    operation: Mapped[str] = mapped_column(String(48), nullable=False)
    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.stage.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    stage_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("tournament.stage_item.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="pending",
        server_default="pending",
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        server_default=text("'{}'::json"),
    )
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text(), nullable=True)
    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("auth.user.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(db.DateTime(timezone=True), nullable=True)


class TournamentRecalculationState(db.Base):
    """Durable generation counter preventing lost standings invalidations."""

    __tablename__ = "recalculation_state"
    __table_args__ = ({"schema": "tournament"},)

    tournament_id: Mapped[int] = mapped_column(
        BigInteger(),
        ForeignKey("tournament.tournament.id", ondelete="CASCADE"),
        primary_key=True,
    )
    requested_generation: Mapped[int] = mapped_column(BigInteger(), nullable=False, default=0, server_default="0")
    completed_generation: Mapped[int] = mapped_column(BigInteger(), nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        db.DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        db.DateTime(timezone=True),
        nullable=True,
        onupdate=func.now(),
    )
