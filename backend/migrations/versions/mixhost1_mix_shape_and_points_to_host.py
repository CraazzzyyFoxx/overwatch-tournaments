"""Move the mix roster shape and points-per-win onto the host; drop the per-mix Discord override.

Revision ID: mixhost1
Revises: mixpref1
Create Date: 2026-09-13 00:00:00.000000

Second half of ``mixpref1``. The solver knobs already live on the account; the
roster shape (``balancer.custom_game_role_slot``) and the rank-adjustment knob
(``custom_game.points_per_win``) follow them for the same reason -- they say how
this *person* runs their pickup sessions, not what happened in one lobby -- and
join ``balancer.user_config`` as two columns beside ``config_json`` rather than
keys inside it, since that blob is handed to the solver verbatim as overrides
and neither of these is one.

``custom_game.discord_channel_id`` is dropped outright with no home to go to: it
was an admin-only per-lobby override of the workspace's Discord channel, which
already has its own workspace-level setting and admin UI
(``balancer.workspace_config.config_json.mix_discord_channel_id``). The override
was invisible from the settings screen that nominally owned it, so a mix now
posts to the workspace channel, full stop.

The backfill drains the mixes into their hosts, then the columns and the table
go. ``downgrade()`` recreates all three empty: the per-mix values are not
recoverable once dropped, and the host preferences they were folded into stay on
the account (where the ``mixpref1`` downgrade would drop them with the table).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "mixhost1"
down_revision: str | Sequence[str] | None = "mixpref1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Two separate drains, not one join: a host may well have set a shape on one mix
# and a points knob on another, and the "latest wins" tie-break has to be applied
# per setting or the older of the two would silently win the whole row.
#
# Both order the same way as ``mixpref1``: newest touch first
# (``updated_at``, falling back to ``created_at`` for a row never edited), ``id``
# breaking a same-timestamp tie deterministically. A host with ten mixes had one
# opinion, expressed last. Hosts are ``NULL`` on mixes whose owner deleted their
# account -- nobody to drain into, so those rows are skipped.
#
# ``ON CONFLICT`` because ``mixpref1``'s own backfill may already have created
# this host's row for the solver knobs; the two settings are independent columns
# and neither drain may clobber the other's work.
_BACKFILL_ROLE_SLOTS = sa.text(
    """
    INSERT INTO balancer.user_config (user_id, role_slots_json)
    SELECT latest.host_user_id, latest.slots
    FROM (
        SELECT DISTINCT ON (game.host_user_id)
            game.host_user_id,
            (
                SELECT jsonb_object_agg(slot.role, slot.slot_count)
                FROM balancer.custom_game_role_slot AS slot
                WHERE slot.custom_game_id = game.id
            ) AS slots
        FROM balancer.custom_game AS game
        WHERE game.host_user_id IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM balancer.custom_game_role_slot AS slot WHERE slot.custom_game_id = game.id
          )
        ORDER BY game.host_user_id, COALESCE(game.updated_at, game.created_at) DESC, game.id DESC
    ) AS latest
    ON CONFLICT (user_id) DO UPDATE SET role_slots_json = EXCLUDED.role_slots_json
    """
)

_BACKFILL_POINTS = sa.text(
    """
    INSERT INTO balancer.user_config (user_id, points_per_win)
    SELECT DISTINCT ON (game.host_user_id) game.host_user_id, game.points_per_win
    FROM balancer.custom_game AS game
    WHERE game.host_user_id IS NOT NULL
      AND game.points_per_win IS NOT NULL
    ORDER BY game.host_user_id, COALESCE(game.updated_at, game.created_at) DESC, game.id DESC
    ON CONFLICT (user_id) DO UPDATE SET points_per_win = EXCLUDED.points_per_win
    """
)


def upgrade() -> None:
    op.add_column(
        "user_config",
        sa.Column("role_slots_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        schema="balancer",
    )
    op.add_column("user_config", sa.Column("points_per_win", sa.Integer(), nullable=True), schema="balancer")

    op.execute(_BACKFILL_ROLE_SLOTS)
    op.execute(_BACKFILL_POINTS)

    op.drop_table("custom_game_role_slot", schema="balancer")
    # The CHECK on ``points_per_win`` names only that column, so Postgres drops
    # it along with the column -- no separate ``drop_constraint``.
    op.drop_column("custom_game", "points_per_win", schema="balancer")
    op.drop_column("custom_game", "discord_channel_id", schema="balancer")


def downgrade() -> None:
    op.add_column("custom_game", sa.Column("discord_channel_id", sa.BigInteger(), nullable=True), schema="balancer")
    op.add_column("custom_game", sa.Column("points_per_win", sa.Integer(), nullable=True), schema="balancer")
    op.create_check_constraint(
        "ck_custom_game_points_per_win",
        "custom_game",
        "points_per_win IS NULL OR points_per_win BETWEEN 1 AND 1000",
        schema="balancer",
    )
    op.create_table(
        "custom_game_role_slot",
        sa.Column("custom_game_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("slot_count", sa.Integer(), nullable=False),
        sa.CheckConstraint("slot_count > 0", name="ck_custom_game_role_slot_count"),
        sa.ForeignKeyConstraint(["custom_game_id"], ["balancer.custom_game.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("custom_game_id", "role"),
        schema="balancer",
    )
    # Data loss, stated plainly: the three per-mix settings come back EMPTY. The
    # values live on the hosts now, and a host's single shape/points pair cannot
    # be un-merged back into the several mixes it was drained from -- there is no
    # record of which mixes contributed. The per-mix Discord overrides are gone
    # for good; they were never copied anywhere.
    op.drop_column("user_config", "points_per_win", schema="balancer")
    op.drop_column("user_config", "role_slots_json", schema="balancer")
