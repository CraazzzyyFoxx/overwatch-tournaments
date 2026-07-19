# backend/shared/models/matches/stat_baseline.py
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, Float, Index, SmallInteger, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db, enums

__all__ = ("StatBaseline",)


class StatBaseline(db.TimeStampIntegerMixin):
    """League baseline (mean/std of a per-10-minute stat rate) for impact scoring.

    ``rank_bucket = -1`` is the role-wide baseline (ImpactPoints); ``0..N-1``
    are rank terciles (OverperformanceScore). Bucket bounds are frozen in
    ``meta`` at compute time — scoring reads them from the rows, never
    recomputes. Versioned by ``formula_version``; recompute replaces the
    version's rows atomically.
    """

    __tablename__ = "stat_baselines"
    __table_args__ = (
        UniqueConstraint(
            "formula_version",
            "role",
            "rank_bucket",
            "stat",
            name="uq_stat_baselines_key",
        ),
        Index("ix_stat_baselines_version", "formula_version"),
        {"schema": "matches"},
    )

    formula_version: Mapped[str] = mapped_column(String(64))
    role: Mapped[enums.HeroClass] = mapped_column(Enum(enums.HeroClass))
    rank_bucket: Mapped[int] = mapped_column(SmallInteger(), server_default="-1")
    stat: Mapped[enums.LogStatsName] = mapped_column(Enum(enums.LogStatsName))
    mean: Mapped[float] = mapped_column(Float())
    std: Mapped[float] = mapped_column(Float())
    meta: Mapped[dict[str, Any] | None] = mapped_column(JSONB(), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=db.func.now())
