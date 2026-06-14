"""add_workspace_scoped_roles

Revision ID: f6a8b0c4d5e6
Revises: e5f7a9b3c4d5
Create Date: 2026-04-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f6a8b0c4d5e6"
down_revision: Union[str, None] = "e5f7a9b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add nullable workspace_id column to auth.roles
    op.add_column(
        "roles",
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            nullable=True,
        ),
        schema="auth",
    )
    op.create_index(
        "ix_auth_roles_workspace_id",
        "roles",
        ["workspace_id"],
        schema="auth",
    )

    # Drop old unique index on name (created as ix_roles_name in initial migration,
    # kept its name when table moved to auth schema)
    op.execute("DROP INDEX IF EXISTS auth.ix_roles_name")

    # Create partial unique indexes for name scoping
    # Global roles: name must be unique among roles with workspace_id IS NULL
    op.execute(
        "CREATE UNIQUE INDEX uq_roles_name_global "
        "ON auth.roles (name) WHERE workspace_id IS NULL"
    )
    # Workspace roles: (name, workspace_id) must be unique among non-NULL workspace_id
    op.execute(
        "CREATE UNIQUE INDEX uq_roles_name_workspace "
        "ON auth.roles (name, workspace_id) WHERE workspace_id IS NOT NULL"
    )

    # Re-create a non-unique index on name for general lookups
    op.create_index(
        "ix_roles_name",
        "roles",
        ["name"],
        schema="auth",
    )


def downgrade() -> None:
    # Drop partial unique indexes
    op.execute("DROP INDEX IF EXISTS auth.uq_roles_name_global")
    op.execute("DROP INDEX IF EXISTS auth.uq_roles_name_workspace")

    # Drop the regular name index
    op.execute("DROP INDEX IF EXISTS auth.ix_roles_name")

    # Restore unique index on name
    op.create_index(
        "ix_roles_name",
        "roles",
        ["name"],
        unique=True,
        schema="auth",
    )

    # Drop workspace_id column
    op.drop_index("ix_auth_roles_workspace_id", table_name="roles", schema="auth")
    op.drop_column("roles", "workspace_id", schema="auth")
