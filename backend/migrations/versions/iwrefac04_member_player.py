"""identity refactor: workspace_member on player_id (drop auth_user_id + role)

Re-bases ``workspace.workspace_member`` onto ``player_id`` (FK
``players.user.id`` CASCADE) instead of ``auth_user_id``. Backfills
``player_id`` from ``players.user.auth_user_id`` (Phase A). Any member whose
auth_user has no linked player yet gets a shadow player created so the
column can go NOT NULL (should be none after Phase A signup provisioning,
but this is a safety net, not the expected path).

Adds the two unique constraints the ORM model now declares
(``uq_workspace_member_workspace_player`` on (workspace_id, player_id) and
``uq_workspace_member_id_workspace`` on (id, workspace_id)), and drops the
old ``role`` column and the old unique on (workspace_id, auth_user_id).

``role`` is NOT recoverable on downgrade — RBAC now lives on
auth.roles/auth.user_role, and the denormalized ``workspace_member.role``
column was superseded before this migration. Downgrade restores the column
with its original server_default ("member") for structural compatibility
only.
"""
import sqlalchemy as sa
from alembic import op

revision = "iwrefac04"
down_revision = "iwrefac03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workspace_member",
        sa.Column("player_id", sa.Integer(), nullable=True),
        schema="workspace",
    )
    op.execute(
        """
        UPDATE workspace.workspace_member wm
        SET player_id = pu.id
        FROM players."user" pu
        WHERE pu.auth_user_id = wm.auth_user_id
        """
    )
    # Safety: any member whose auth_user has no player yet (should be none after Phase A
    # signup provisioning) — create a shadow player so the column can go NOT NULL.
    op.execute(
        """
        INSERT INTO players."user" (name, auth_user_id, created_at)
        SELECT au.username, au.id, now()
        FROM workspace.workspace_member wm
        JOIN auth."user" au ON au.id = wm.auth_user_id
        WHERE wm.player_id IS NULL
          AND NOT EXISTS (SELECT 1 FROM players."user" p WHERE p.auth_user_id = au.id)
        """
    )
    op.execute(
        """
        UPDATE workspace.workspace_member wm
        SET player_id = pu.id
        FROM players."user" pu
        WHERE pu.auth_user_id = wm.auth_user_id AND wm.player_id IS NULL
        """
    )
    op.alter_column("workspace_member", "player_id", nullable=False, schema="workspace")
    op.create_foreign_key(
        "fk_workspace_member_player",
        "workspace_member",
        "user",
        ["player_id"],
        ["id"],
        source_schema="workspace",
        referent_schema="players",
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "uq_workspace_member_workspace_player",
        "workspace_member",
        ["workspace_id", "player_id"],
        schema="workspace",
    )
    op.create_unique_constraint(
        "uq_workspace_member_id_workspace",
        "workspace_member",
        ["id", "workspace_id"],
        schema="workspace",
    )
    op.drop_constraint(
        "workspace_member_workspace_id_auth_user_id_key",
        "workspace_member",
        schema="workspace",
        type_="unique",
    )
    op.drop_column("workspace_member", "auth_user_id", schema="workspace")
    op.drop_column("workspace_member", "role", schema="workspace")


def downgrade() -> None:
    # NOTE: `role` cannot be recovered — it was superseded by auth.roles/auth.user_role
    # before this migration ran. Restored here with its original default only so the
    # table shape matches pre-migration structure; values are not meaningful.
    op.add_column(
        "workspace_member",
        sa.Column("role", sa.String(), server_default="member", nullable=False),
        schema="workspace",
    )
    op.add_column(
        "workspace_member",
        sa.Column("auth_user_id", sa.Integer(), nullable=True),
        schema="workspace",
    )
    op.execute(
        """
        UPDATE workspace.workspace_member wm
        SET auth_user_id = pu.auth_user_id
        FROM players."user" pu
        WHERE pu.id = wm.player_id
        """
    )
    op.alter_column("workspace_member", "auth_user_id", nullable=False, schema="workspace")
    op.create_foreign_key(
        "workspace_member_auth_user_id_fkey",
        "workspace_member",
        "user",
        ["auth_user_id"],
        ["id"],
        source_schema="workspace",
        referent_schema="auth",
        ondelete="CASCADE",
    )
    op.create_unique_constraint(
        "workspace_member_workspace_id_auth_user_id_key",
        "workspace_member",
        ["workspace_id", "auth_user_id"],
        schema="workspace",
    )
    op.drop_constraint(
        "uq_workspace_member_id_workspace",
        "workspace_member",
        schema="workspace",
        type_="unique",
    )
    op.drop_constraint(
        "uq_workspace_member_workspace_player",
        "workspace_member",
        schema="workspace",
        type_="unique",
    )
    op.drop_constraint(
        "fk_workspace_member_player",
        "workspace_member",
        schema="workspace",
        type_="foreignkey",
    )
    op.drop_column("workspace_member", "player_id", schema="workspace")
