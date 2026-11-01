"""Matches stats core pulls from a discipline's producer by external id, before any bytes exist.

A row is one request "fetch ``external_id`` from ``source_kind`` for this game" -- a tournament game, or a pickup mix
round's (``hint_tournament_id`` NULL). The stats worker retries a ``pending`` row (``next_attempt_at``) until the
producer serves it - then the bytes are stored like an upload and ``ingest_job_id`` names the normal ingest job - or
until it gives up (``failed``, ``last_error``).
"""

from datetime import datetime
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = ("MatchFetch", "MatchFetchStatus")


class MatchFetchStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"


class MatchFetch(db.TimeStampIntegerMixin):
    __tablename__ = "match_fetch"
    __table_args__ = (
        sa.UniqueConstraint("source_kind", "external_id", "hint_encounter_game_id", name="uq_match_fetch_game"),
        sa.Index("ix_match_fetch_due", "status", "next_attempt_at"),
        sa.Index("ix_match_fetch_workspace_external", "workspace_id", "source_kind", "external_id"),
        sa.Index("ix_match_fetch_encounter", "hint_encounter_id"),
        {"schema": "stats"},
    )

    workspace_id: Mapped[int] = mapped_column(
        sa.ForeignKey("workspace.id", name="fk_match_fetch_workspace", ondelete="CASCADE")
    )
    discipline: Mapped[str] = mapped_column(
        sa.String(32), sa.ForeignKey("catalog.discipline.code", name="fk_match_fetch_discipline")
    )
    source_kind: Mapped[str] = mapped_column(sa.String(32))
    external_id: Mapped[str] = mapped_column(sa.String(128))
    #: ``None``: a mix round (the encounter's ``custom_game_id`` names the mix).
    hint_tournament_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("tournament.tournament.id", name="fk_match_fetch_tournament", ondelete="CASCADE"),
        nullable=True,
    )
    hint_encounter_id: Mapped[int] = mapped_column(
        sa.ForeignKey("encounter.encounter.id", name="fk_match_fetch_encounter", ondelete="CASCADE")
    )
    hint_encounter_game_id: Mapped[int] = mapped_column(
        sa.ForeignKey("encounter.game.id", name="fk_match_fetch_game", ondelete="CASCADE")
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("auth.user.id", name="fk_match_fetch_requested_by", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[MatchFetchStatus] = mapped_column(
        sa.Enum(
            MatchFetchStatus,
            values_callable=lambda enum: [item.value for item in enum],
            native_enum=False,
            create_constraint=True,
            name="ck_match_fetch_status",
            length=16,
        ),
        default=MatchFetchStatus.PENDING,
        server_default="pending",
    )
    attempts: Mapped[int] = mapped_column(sa.Integer(), default=0, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    last_error: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    ingest_job_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey("stats.ingest_job.id", name="fk_match_fetch_ingest_job", ondelete="SET NULL"), nullable=True
    )
