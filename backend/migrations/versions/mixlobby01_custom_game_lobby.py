"""Move everything about one played match onto ``balancer.custom_game_lobby``.

Revision ID: mixlobby01
Revises: mixself01
Create Date: 2026-09-26 00:00:00.000000

A mix runs up to two lobbies at once, each with its own matchup, pager, map and
pace. The four columns that described "the" match therefore stop being the
mix's: every existing mix becomes a mix with exactly one lobby, row
``lobby_index = 0``, carrying what it already had. ``balanced_at`` is seeded
from ``updated_at`` where a balance exists, so "the lineup on screen was never
recorded" answers sensibly from the first day rather than after the next
balance.

``casual.match`` gains the lobby that played it (0 for every historical row) and
``casual.match_busy_player`` records who was in the OTHER lobby at that moment,
which rotation must count as neither played nor sat out. Empty for every mix
that ran before this, which is exactly today's behaviour -- no backfill.

``downgrade()`` copies lobby 0 back and drops the rest; a second lobby's balance
is lost, because there is nowhere on ``custom_game`` to put it.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "mixlobby01"
down_revision: str | Sequence[str] | None = "mixself01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. The lobby table, and a row per existing mix holding its four columns.
    op.create_table(
        "custom_game_lobby",
        sa.Column("custom_game_id", sa.BigInteger(), nullable=False),
        sa.Column("lobby_index", sa.Integer(), nullable=False),
        sa.Column("selected_variant_index", sa.Integer(), server_default="0", nullable=False),
        sa.Column("balance_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("balance_result_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("next_map_id", sa.Integer(), nullable=True),
        sa.Column("balanced_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("lobby_index BETWEEN 0 AND 1", name="ck_custom_game_lobby_index"),
        sa.ForeignKeyConstraint(["custom_game_id"], ["balancer.custom_game.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["next_map_id"], ["overwatch.map.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("custom_game_id", "lobby_index"),
        schema="balancer",
    )
    op.execute(
        """
        INSERT INTO balancer.custom_game_lobby (
            custom_game_id, lobby_index, selected_variant_index,
            balance_result_json, balance_result_version, next_map_id, balanced_at
        )
        SELECT
            id, 0, selected_variant_index,
            balance_result_json, balance_result_version, next_map_id,
            CASE WHEN balance_result_json IS NULL THEN NULL ELSE COALESCE(updated_at, created_at) END
        FROM balancer.custom_game
        """
    )

    # 2. The mix keeps none of them.
    op.drop_column("custom_game", "balance_result_version", schema="balancer")
    op.drop_column("custom_game", "balance_result_json", schema="balancer")
    op.drop_column("custom_game", "selected_variant_index", schema="balancer")
    op.drop_column("custom_game", "next_map_id", schema="balancer")

    # 3. How many lobbies the mix runs.
    op.add_column(
        "custom_game",
        sa.Column("lobby_count", sa.Integer(), server_default="1", nullable=False),
        schema="balancer",
    )
    op.create_check_constraint(
        "ck_custom_game_lobby_count", "custom_game", "lobby_count BETWEEN 1 AND 2", schema="balancer"
    )

    # 4. The host's "this one plays in A".
    op.add_column("custom_game_player", sa.Column("lobby_pin", sa.Integer(), nullable=True), schema="balancer")
    op.create_check_constraint(
        "ck_custom_game_player_lobby_pin", "custom_game_player", "lobby_pin BETWEEN 0 AND 1", schema="balancer"
    )

    # 5. Which lobby played a recorded match.
    op.add_column(
        "match",
        sa.Column("lobby_index", sa.Integer(), server_default="0", nullable=False),
        schema="casual",
    )
    op.create_check_constraint("ck_casual_match_lobby_index", "match", "lobby_index BETWEEN 0 AND 1", schema="casual")

    # 6. Who was in the other lobby when it was recorded.
    op.create_table(
        "match_busy_player",
        sa.Column("match_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["casual.match.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_member_id"], ["workspace_member.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("match_id", "workspace_member_id"),
        schema="casual",
    )


def downgrade() -> None:
    op.drop_table("match_busy_player", schema="casual")
    op.drop_constraint("ck_casual_match_lobby_index", "match", schema="casual", type_="check")
    op.drop_column("match", "lobby_index", schema="casual")

    op.drop_constraint("ck_custom_game_player_lobby_pin", "custom_game_player", schema="balancer", type_="check")
    op.drop_column("custom_game_player", "lobby_pin", schema="balancer")

    op.drop_constraint("ck_custom_game_lobby_count", "custom_game", schema="balancer", type_="check")
    op.drop_column("custom_game", "lobby_count", schema="balancer")

    op.add_column(
        "custom_game",
        sa.Column("next_map_id", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.create_foreign_key(
        "fk_custom_game_next_map",
        "custom_game",
        "map",
        ["next_map_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="overwatch",
        ondelete="SET NULL",
    )
    op.add_column(
        "custom_game",
        sa.Column("selected_variant_index", sa.Integer(), server_default="0", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "custom_game",
        sa.Column("balance_result_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "custom_game",
        sa.Column("balance_result_version", sa.Integer(), server_default="1", nullable=False),
        schema="balancer",
    )
    # Lobby 0 is the one a single-lobby mix always was; a second lobby's balance
    # has nowhere to go back to.
    op.execute(
        """
        UPDATE balancer.custom_game AS game
        SET selected_variant_index = lobby.selected_variant_index,
            balance_result_json = lobby.balance_result_json,
            balance_result_version = lobby.balance_result_version,
            next_map_id = lobby.next_map_id
        FROM balancer.custom_game_lobby AS lobby
        WHERE lobby.custom_game_id = game.id AND lobby.lobby_index = 0
        """
    )
    op.drop_table("custom_game_lobby", schema="balancer")
