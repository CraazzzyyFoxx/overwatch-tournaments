"""identity refactor: workspace-scope auth.user_permission_deny

Adds a nullable ``workspace_id`` FK to ``auth.user_permission_deny`` and swaps
the plain unique constraint ``uq_user_permission_deny`` over
``(user_id, permission_id)`` for a COALESCE-based unique expression index
``uq_user_permission_deny_user_perm_workspace`` over
``(user_id, permission_id, COALESCE(workspace_id, 0))``. ``workspace_id IS
NULL`` means a global deny; a concrete ``workspace_id`` scopes the deny to
that workspace only. The CHECK logic that consumes this column is Task 8 —
not part of this migration.
"""

import sqlalchemy as sa
from alembic import op

revision = "iwrefac03"
down_revision = "iwrefac02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user_permission_deny",
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        schema="auth",
    )
    op.create_foreign_key(
        "fk_user_permission_deny_workspace",
        "user_permission_deny",
        "workspace",
        ["workspace_id"],
        ["id"],
        source_schema="auth",
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_user_permission_deny_workspace_id",
        "user_permission_deny",
        ["workspace_id"],
        schema="auth",
    )
    op.drop_constraint(
        "uq_user_permission_deny",
        "user_permission_deny",
        schema="auth",
        type_="unique",
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_user_permission_deny_user_perm_workspace "
        "ON auth.user_permission_deny (user_id, permission_id, COALESCE(workspace_id, 0))"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS auth.uq_user_permission_deny_user_perm_workspace")
    op.create_unique_constraint(
        "uq_user_permission_deny",
        "user_permission_deny",
        ["user_id", "permission_id"],
        schema="auth",
    )
    op.drop_index(
        "ix_user_permission_deny_workspace_id",
        table_name="user_permission_deny",
        schema="auth",
    )
    op.drop_constraint(
        "fk_user_permission_deny_workspace",
        "user_permission_deny",
        schema="auth",
        type_="foreignkey",
    )
    op.drop_column("user_permission_deny", "workspace_id", schema="auth")
