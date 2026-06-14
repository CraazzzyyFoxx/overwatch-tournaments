"""add_auth_session_families

Extend auth.refresh_token with logical session metadata so refresh-token
rotation can be grouped into a single browser session history.

Revision ID: b9w1x5y6z7a8
Revises: a7v1w5x6y7z8
Create Date: 2026-04-14
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "b9w1x5y6z7a8"
down_revision: Union[str, None] = "a7v1w5x6y7z8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))

    op.add_column(
        "refresh_token",
        sa.Column("session_id", sa.Uuid(), nullable=True),
        schema="auth",
    )
    op.add_column(
        "refresh_token",
        sa.Column("session_started_at", sa.DateTime(timezone=True), nullable=True),
        schema="auth",
    )
    op.add_column(
        "refresh_token",
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        schema="auth",
    )

    op.execute(
        sa.text(
            """
            UPDATE auth.refresh_token
            SET session_id = gen_random_uuid(),
                session_started_at = created_at,
                revoked_at = CASE
                    WHEN is_revoked THEN COALESCE(updated_at, created_at)
                    ELSE NULL
                END
            WHERE session_id IS NULL
            """
        )
    )

    op.alter_column("refresh_token", "session_id", nullable=False, schema="auth")
    op.alter_column("refresh_token", "session_started_at", nullable=False, schema="auth")

    op.create_index(
        "ix_auth_refresh_token_user_id",
        "refresh_token",
        ["user_id"],
        unique=False,
        schema="auth",
    )
    op.create_index(
        "ix_auth_refresh_token_session_id",
        "refresh_token",
        ["session_id"],
        unique=False,
        schema="auth",
    )


def downgrade() -> None:
    op.drop_index("ix_auth_refresh_token_session_id", table_name="refresh_token", schema="auth")
    op.drop_index("ix_auth_refresh_token_user_id", table_name="refresh_token", schema="auth")
    op.drop_column("refresh_token", "revoked_at", schema="auth")
    op.drop_column("refresh_token", "session_started_at", schema="auth")
    op.drop_column("refresh_token", "session_id", schema="auth")
