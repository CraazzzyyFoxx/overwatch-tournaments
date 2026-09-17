from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db

__all__ = (
    "QuotaApiKeyLimit",
    "QuotaOperation",
    "QuotaPlan",
    "QuotaPlanLimit",
    "QuotaWorkspaceLimit",
)


class QuotaPlan(db.TimeStampIntegerMixin):
    """Named set of ceilings a workspace runs on.

    A workspace resolves its plan through ``Workspace.quota_plan_id``, falling
    back to the plan whose ``slug`` equals its ``verification_status``, so the
    seeded ``unverified``/``verified``/``trusted`` slugs are load-bearing.
    """

    __tablename__ = "plan"
    __table_args__ = ({"schema": "quota"},)

    slug: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)


class QuotaPlanLimit(db.Base):
    """One plan's ceilings for one enforcement scope.

    ``NULL`` in a dimension means *unlimited* here: a plan is the bottom of the
    resolution chain, so there is nothing left to inherit from. ``scope`` is a
    plain string (``workspace``/``key``/``session``) with no CHECK, so a fourth
    scope is a data change rather than a migration; the write layer validates
    it against the pydantic literal.
    """

    __tablename__ = "plan_limit"
    __table_args__ = (
        # Passes on NULL, which is the point: the constraint rejects a negative
        # ceiling without forbidding the "unset" value the chain is built on.
        CheckConstraint(
            "COALESCE(requests_per_minute, 0) >= 0 AND COALESCE(heavy_per_day, 0) >= 0 AND "
            "COALESCE(concurrent_heavy, 0) >= 0 AND COALESCE(max_upload_bytes, 0) >= 0 AND "
            "COALESCE(max_items_per_request, 0) >= 0",
            name="ck_quota_plan_limit_nonneg",
        ),
        {"schema": "quota"},
    )

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("quota.plan.id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(String(16), primary_key=True)
    requests_per_minute: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    heavy_per_day: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    concurrent_heavy: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    max_upload_bytes: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    max_items_per_request: Mapped[int | None] = mapped_column(Integer(), nullable=True)


class QuotaOperation(db.TimeStampIntegerMixin):
    """Catalogue entry for one metered operation slug.

    No FK: the slug is whatever a call site passes. A slug with no row costs
    nothing, and ``enabled = false`` is the per-operation kill switch.
    """

    __tablename__ = "operation"
    __table_args__ = (
        CheckConstraint("cost >= 0", name="ck_quota_operation_cost"),
        {"schema": "quota"},
    )

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    cost: Mapped[int] = mapped_column(Integer(), nullable=False, default=1, server_default="1")
    enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, default=True, server_default="true")
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)


class QuotaWorkspaceLimit(db.Base):
    """One workspace's override of its plan, for one enforcement scope.

    ``NULL`` in a dimension means *inherit* -- the plan's value stands. Only a
    row that names a value overrides anything, so deleting a row restores the
    plan rather than dropping the quota to zero.
    """

    __tablename__ = "workspace_limit"
    __table_args__ = ({"schema": "quota"},)

    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspace.id", ondelete="CASCADE"),
        primary_key=True,
    )
    scope: Mapped[str] = mapped_column(String(16), primary_key=True)
    requests_per_minute: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    heavy_per_day: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    concurrent_heavy: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    max_upload_bytes: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    max_items_per_request: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
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


class QuotaApiKeyLimit(db.Base):
    """One API key's override of its workspace's ceilings.

    ``NULL`` in a dimension means *inherit*. There is no ``scope`` column: a
    key is a single principal, so its only scope is ``key``.
    """

    __tablename__ = "api_key_limit"
    __table_args__ = ({"schema": "quota"},)

    api_key_id: Mapped[int] = mapped_column(
        ForeignKey("auth.api_key.id", ondelete="CASCADE"),
        primary_key=True,
    )
    requests_per_minute: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    heavy_per_day: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    concurrent_heavy: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    max_upload_bytes: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    max_items_per_request: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True)
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
