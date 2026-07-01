"""identity refactor: players.user.auth_user_id (collapse auth.user_player)"""
import sqlalchemy as sa
from alembic import op

revision = "iwrefac01"
down_revision = "oauthmulti0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("auth_user_id", sa.Integer(), nullable=True),
        schema="players",
    )
    op.create_foreign_key(
        "fk_players_user_auth_user", "user", "user",
        ["auth_user_id"], ["id"],
        source_schema="players", referent_schema="auth", ondelete="SET NULL",
    )
    # Backfill from the PRIMARY link only (one auth_user -> at most one player).
    op.execute(
        """
        UPDATE players."user" pu
        SET auth_user_id = up.auth_user_id
        FROM auth.user_player up
        WHERE up.player_id = pu.id AND up.is_primary = true
        """
    )
    op.create_index(
        "uq_players_user_auth_user_id", "user", ["auth_user_id"],
        unique=True, schema="players",
        postgresql_where=sa.text("auth_user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_players_user_auth_user_id", table_name="user", schema="players")
    op.drop_constraint("fk_players_user_auth_user", "user", schema="players", type_="foreignkey")
    op.drop_column("user", "auth_user_id", schema="players")
