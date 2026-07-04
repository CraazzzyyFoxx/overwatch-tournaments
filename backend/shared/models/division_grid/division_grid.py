from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.core import db

__all__ = (
    "DivisionGrid",
    "DivisionGridVersion",
    "DivisionGridTier",
    "DivisionGridMapping",
    "DivisionGridMappingRule",
)


class DivisionGrid(db.TimeStampIntegerMixin):
    __tablename__ = "division_grid"
    __table_args__ = (
        UniqueConstraint("workspace_id", "slug"),
    )

    workspace_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(), nullable=False)
    name: Mapped[str] = mapped_column(String(), nullable=False)
    description: Mapped[str | None] = mapped_column(String(), nullable=True)

    versions: Mapped[list["DivisionGridVersion"]] = relationship(
        back_populates="grid",
        passive_deletes=True,
        order_by="DivisionGridVersion.version",
        lazy="selectin",
    )


class DivisionGridVersion(db.TimeStampIntegerMixin):
    __tablename__ = "division_grid_version"
    __table_args__ = (
        UniqueConstraint("grid_id", "version"),
    )

    grid_id: Mapped[int] = mapped_column(
        ForeignKey("division_grid.id", ondelete="CASCADE"),
        index=True,
    )
    version: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    label: Mapped[str] = mapped_column(String(), nullable=False)
    status: Mapped[str] = mapped_column(String(), server_default="draft", nullable=False)
    created_from_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("division_grid_version.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    grid: Mapped["DivisionGrid"] = relationship(back_populates="versions", foreign_keys=[grid_id])
    created_from_version: Mapped["DivisionGridVersion | None"] = relationship(
        remote_side="DivisionGridVersion.id",
        foreign_keys=[created_from_version_id],
    )
    tiers: Mapped[list["DivisionGridTier"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        order_by="DivisionGridTier.sort_order",
        lazy="selectin",
    )


class DivisionGridTier(db.TimeStampIntegerMixin):
    __tablename__ = "division_grid_tier"
    __table_args__ = (
        UniqueConstraint("version_id", "slug"),
        UniqueConstraint("version_id", "sort_order"),
    )

    version_id: Mapped[int] = mapped_column(
        ForeignKey("division_grid_version.id", ondelete="CASCADE"),
        index=True,
    )
    slug: Mapped[str] = mapped_column(String(), nullable=False)
    number: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    name: Mapped[str] = mapped_column(String(), nullable=False)
    sort_order: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    rank_min: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    rank_max: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    icon_url: Mapped[str] = mapped_column(String(), nullable=False)
    ow_rank_min: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    ow_rank_max: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)

    version: Mapped["DivisionGridVersion"] = relationship(back_populates="tiers")


class DivisionGridMapping(db.TimeStampIntegerMixin):
    __tablename__ = "division_grid_mapping"
    __table_args__ = (
        UniqueConstraint("source_version_id", "target_version_id"),
    )

    source_version_id: Mapped[int] = mapped_column(
        ForeignKey("division_grid_version.id", ondelete="CASCADE"),
        index=True,
    )
    target_version_id: Mapped[int] = mapped_column(
        ForeignKey("division_grid_version.id", ondelete="CASCADE"),
        index=True,
    )
    name: Mapped[str] = mapped_column(String(), nullable=False)
    is_complete: Mapped[bool] = mapped_column(Boolean(), server_default="false", nullable=False)

    source_version: Mapped["DivisionGridVersion"] = relationship(foreign_keys=[source_version_id])
    target_version: Mapped["DivisionGridVersion"] = relationship(foreign_keys=[target_version_id])
    rules: Mapped[list["DivisionGridMappingRule"]] = relationship(
        back_populates="mapping",
        passive_deletes=True,
        lazy="selectin",
    )


class DivisionGridMappingRule(db.TimeStampIntegerMixin):
    __tablename__ = "division_grid_mapping_rule"

    mapping_id: Mapped[int] = mapped_column(
        ForeignKey("division_grid_mapping.id", ondelete="CASCADE"),
        index=True,
    )
    source_tier_id: Mapped[int] = mapped_column(
        ForeignKey("division_grid_tier.id", ondelete="CASCADE"),
        index=True,
    )
    target_tier_id: Mapped[int] = mapped_column(
        ForeignKey("division_grid_tier.id", ondelete="CASCADE"),
        index=True,
    )
    weight: Mapped[float] = mapped_column(Float(), nullable=False, server_default="1.0")
    is_primary: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false")

    mapping: Mapped["DivisionGridMapping"] = relationship(back_populates="rules")
    source_tier: Mapped["DivisionGridTier"] = relationship(foreign_keys=[source_tier_id])
    target_tier: Mapped["DivisionGridTier"] = relationship(foreign_keys=[target_tier_id])
