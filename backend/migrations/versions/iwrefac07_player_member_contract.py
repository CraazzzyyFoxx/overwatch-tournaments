"""identity refactor: Player.workspace_member_id NOT NULL, drop Player.user_id (contract)

CONTRACT half of the expand-contract pair started by ``iwrefac06``. All
``Player.user_id``/``Player.user`` readers have been migrated to
``workspace_member``/``workspace_member.player`` (P5.1-P5.2), and the model's
last writers now set ``workspace_member_id`` without ``user_id`` (P5.3). This
migration:

- sets ``tournament.player.workspace_member_id`` NOT NULL (every roster row
  has one after ``iwrefac06``'s backfill + safety-net insert, verified on
  anak_dev before this migration was written);
- drops the old ``user_id``-keyed indexes (``ix_player_user_tournament``,
  ``ix_player_team_user``, partial ``ix_player_user_not_sub``) and the expand
  step's single-column ``ix_player_workspace_member_id``, replacing them with
  the composite indexes the ORM model now declares
  (``ix_player_workspace_member_tournament``, ``ix_player_team_workspace_member``,
  partial ``ix_player_member_not_sub``);
- drops ``tournament.player.user_id`` (its FK is dropped automatically by
  Postgres along with the column).

Downgrade re-adds ``user_id`` (nullable Integer, FK ``players.user.id``
CASCADE), backfills it from each row's ``workspace_member.player_id``, sets
it NOT NULL, recreates the old indexes, drops the new composite indexes, and
makes ``workspace_member_id`` nullable again.

Revision ID: iwrefac07
Revises: iwrefac06
Create Date: 2026-07-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "iwrefac07"
down_revision: str | None = "iwrefac06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "player",
        "workspace_member_id",
        nullable=False,
        schema="tournament",
    )

    op.drop_index("ix_player_user_tournament", table_name="player", schema="tournament")
    op.drop_index("ix_player_team_user", table_name="player", schema="tournament")
    op.drop_index("ix_player_user_not_sub", table_name="player", schema="tournament")
    op.drop_index("ix_tournament_player_workspace_member_id", table_name="player", schema="tournament")

    op.create_index(
        "ix_player_workspace_member_tournament",
        "player",
        ["workspace_member_id", "tournament_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_player_team_workspace_member",
        "player",
        ["team_id", "workspace_member_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_player_member_not_sub",
        "player",
        ["workspace_member_id", "tournament_id"],
        schema="tournament",
        postgresql_where=sa.text("is_substitution = false"),
    )

    # Drops fk_player_workspace_member's sibling user_id FK automatically along with
    # the column.
    op.drop_column("player", "user_id", schema="tournament")


def downgrade() -> None:
    op.add_column(
        "player",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        schema="tournament",
    )
    op.execute(
        """
        UPDATE tournament.player p
        SET user_id = wm.player_id
        FROM workspace_member wm
        WHERE wm.id = p.workspace_member_id
        """
    )
    op.alter_column(
        "player",
        "user_id",
        nullable=False,
        schema="tournament",
    )
    op.create_foreign_key(
        "player_user_id_fkey",
        "player",
        "user",
        ["user_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="players",
        ondelete="CASCADE",
    )

    op.drop_index("ix_player_workspace_member_tournament", table_name="player", schema="tournament")
    op.drop_index("ix_player_team_workspace_member", table_name="player", schema="tournament")
    op.drop_index("ix_player_member_not_sub", table_name="player", schema="tournament")

    op.create_index(
        "ix_player_user_tournament",
        "player",
        ["user_id", "tournament_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_player_team_user",
        "player",
        ["team_id", "user_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_player_user_not_sub",
        "player",
        ["user_id", "tournament_id"],
        schema="tournament",
        postgresql_where=sa.text("is_substitution = false"),
    )
    op.create_index(
        "ix_tournament_player_workspace_member_id",
        "player",
        ["workspace_member_id"],
        schema="tournament",
    )

    op.alter_column(
        "player",
        "workspace_member_id",
        nullable=True,
        schema="tournament",
    )
