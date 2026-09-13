"""Move the mix solver knobs from the mix onto the host's account.

Revision ID: mixpref1
Revises: reghide01
Create Date: 2026-09-13 00:00:00.000000

``custom_game.balancer_config_json`` made every pickup session re-enter the same
three preferences. They describe how a person likes *their* mixes balanced, not
what happened in one lobby, so they become one row per account
(``balancer.user_config``) that every mix this user hosts balances with.

The backfill drains the mixes into their hosts, then the two per-mix columns go.
``downgrade()`` puts the columns back empty: the per-mix blobs are not recoverable
once dropped, and the preferences they were rebuilt into are lost with the table.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "mixpref1"
down_revision: str | Sequence[str] | None = "reghide01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Only these three of the full ``ConfigOverrides`` vocabulary ever reached the
# mix engine; the rest tune the tournament GA and were dead weight on a mix.
_KEPT_KEYS = ("mix_comfort_tilt", "mix_role_weights", "max_result_variants")

# One row per host, from that host's most recently touched non-empty mix config:
# a host with ten mixes had one opinion, expressed last. Plain SQL because this
# is a set-shaped drain, not an ORM walk -- the model it targets is the one being
# created two statements above.
_BACKFILL = sa.text(
    """
    INSERT INTO balancer.user_config (user_id, config_json)
    SELECT latest.host_user_id, latest.kept
    FROM (
        SELECT DISTINCT ON (game.host_user_id)
            game.host_user_id,
            (
                SELECT COALESCE(jsonb_object_agg(entry.key, entry.value), '{}'::jsonb)
                FROM jsonb_each(game.balancer_config_json) AS entry
                WHERE entry.key = ANY(:kept_keys)
            ) AS kept
        FROM balancer.custom_game AS game
        WHERE game.host_user_id IS NOT NULL
          -- `jsonb_each` errors out on a non-object, and the column is a bare
          -- JSONB: rows holding `null`, a scalar or an array (older writers, a
          -- hand-edited row) would fail the whole migration, not just skip.
          AND jsonb_typeof(game.balancer_config_json) = 'object'
          AND game.balancer_config_json <> '{}'::jsonb
        ORDER BY game.host_user_id, COALESCE(game.updated_at, game.created_at) DESC, game.id DESC
    ) AS latest
    WHERE latest.kept <> '{}'::jsonb
    """
)


def upgrade() -> None:
    op.create_table(
        "user_config",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["auth.user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_balancer_user_config_user"),
        schema="balancer",
    )
    op.create_index("ix_balancer_user_config_user_id", "user_config", ["user_id"], schema="balancer")

    op.execute(_BACKFILL.bindparams(kept_keys=list(_KEPT_KEYS)))

    op.drop_column("custom_game", "balancer_config_json", schema="balancer")
    op.drop_column("custom_game", "balancer_config_version", schema="balancer")


def downgrade() -> None:
    op.add_column(
        "custom_game",
        sa.Column("balancer_config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "custom_game",
        sa.Column("balancer_config_version", sa.Integer(), server_default="1", nullable=False),
        schema="balancer",
    )
    op.drop_index("ix_balancer_user_config_user_id", "user_config", schema="balancer")
    op.drop_table("user_config", schema="balancer")
