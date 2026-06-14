"""fix balancer.workspace_config updated_at: drop NOT NULL and server_default

Revision ID: wsbcfg0002
Revises: wsbcfg0001
Create Date: 2026-06-10

The original wsbcfg0001 migration created updated_at as NOT NULL with server_default=now().
TimeStampIntegerMixin defines updated_at as nullable=True with onupdate=func.now() (no default).
SQLAlchemy explicitly sends updated_at=None on INSERT (because of onupdate), which violates
the NOT NULL constraint even though the server_default exists.
This migration aligns the column definition with the ORM mixin.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wsbcfg0002"
down_revision: str | None = "wsbcfg0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "workspace_config",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
        existing_server_default=sa.text("now()"),
        server_default=None,
        schema="balancer",
    )


def downgrade() -> None:
    op.alter_column(
        "workspace_config",
        "updated_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
        schema="balancer",
    )
