"""``mix.bot_lobby``: the bot-created in-game party of a pickup mix's live match, and the host's remembered region.

One row per live match (its encounter), written by balancer-service when a host has the game's bot open the lobby: the
party's join code, the SHA-256 of the one-time callback token, the source's callback secret and, once the match
started, its id -- which the stats worker files as the round's import instead of searching by players. Cancel, Undo
and a mix delete drop the row with the encounter. ``balancer.user_config.bot_lobby_regions`` is ``{discipline: region}``.

Pure expand: a new table and a column with a default. Downgrade drops both.

Revision ID: botlobby01
Revises: stagepts02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "botlobby01"
down_revision: str | Sequence[str] | None = "stagepts02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bot_lobby",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("workspace_id", sa.BigInteger(), nullable=False),
        sa.Column("custom_game_id", sa.BigInteger(), nullable=False),
        sa.Column("lobby_index", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.BigInteger(), nullable=False),
        sa.Column("discipline", sa.String(32), nullable=False),
        sa.Column("party_id", sa.String(128), nullable=False),
        sa.Column("party_code", sa.String(64), nullable=False),
        sa.Column("callback_token_sha256", sa.String(64), nullable=False),
        sa.Column("callback_secret", sa.String(256), nullable=True),
        sa.Column("match_id", sa.String(128), nullable=True),
        sa.Column("created_by_user_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("lobby_index BETWEEN 0 AND 5", name="ck_custom_game_bot_lobby_index"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["custom_game_id"], ["mix.custom_game.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["encounter_id"], ["encounter.encounter.id"], name="fk_custom_game_bot_lobby_encounter", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["discipline"], ["catalog.discipline.code"], name="fk_custom_game_bot_lobby_discipline"
        ),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["auth.user.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("encounter_id", name="uq_custom_game_bot_lobby_encounter"),
        sa.UniqueConstraint("callback_token_sha256", name="uq_custom_game_bot_lobby_token"),
        schema="mix",
    )
    op.create_index("ix_custom_game_bot_lobby_custom_game_id", "bot_lobby", ["custom_game_id"], schema="mix")
    op.add_column(
        "user_config",
        sa.Column("bot_lobby_regions", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("user_config", "bot_lobby_regions", schema="balancer")
    op.drop_table("bot_lobby", schema="mix")
