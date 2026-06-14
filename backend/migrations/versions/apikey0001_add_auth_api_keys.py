"""add_auth_api_keys

Revision ID: apikey0001
Revises: outbox0001
Create Date: 2026-04-29 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "apikey0001"
down_revision: str | Sequence[str] | None = "outbox0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_key",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auth_user_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("secret_hash", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("scopes_json", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("limits_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("config_policy_json", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["auth_user_id"], ["auth.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id"),
        schema="auth",
    )
    op.create_index("ix_api_key_auth_user_id", "api_key", ["auth_user_id"], schema="auth")
    op.create_index("ix_api_key_workspace_id", "api_key", ["workspace_id"], schema="auth")
    op.create_index("ix_api_key_public_id", "api_key", ["public_id"], schema="auth")
    op.create_index("ix_api_key_owner_workspace", "api_key", ["auth_user_id", "workspace_id"], schema="auth")
    op.create_index("ix_api_key_public_id_active", "api_key", ["public_id", "revoked_at"], schema="auth")


def downgrade() -> None:
    op.drop_index("ix_api_key_public_id_active", table_name="api_key", schema="auth")
    op.drop_index("ix_api_key_owner_workspace", table_name="api_key", schema="auth")
    op.drop_index("ix_api_key_public_id", table_name="api_key", schema="auth")
    op.drop_index("ix_api_key_workspace_id", table_name="api_key", schema="auth")
    op.drop_index("ix_api_key_auth_user_id", table_name="api_key", schema="auth")
    op.drop_table("api_key", schema="auth")
