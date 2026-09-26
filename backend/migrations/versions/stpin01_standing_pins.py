"""Standing pins: an organizer's fixed place, replacing the ``manual_override`` tiebreaker.

Revision ID: stpin01
Revises: varcap01

``tournament.standing_pin`` holds one row per pinned team per standings table
(stage + stage item). The engine seats pinned teams at their place and fills the
rest in computed order, so a pin survives any later result -- unlike the old
``stage.settings_json['manual_positions']``, which only ordered teams that were
still tied on every metric and silently stopped mattering once results split
them.

Data: every ``manual_positions`` entry that is actually holding a place right
now -- the team sits at exactly that position AND is inside a tie cluster, so
the manual order is what decides it -- becomes a pin. Entries that no longer
decide anything (the team is not tied, or sits elsewhere) are dropped: turning
them into pins would freeze teams the organizer never froze. The stored rows
are updated to the state the next recalculation writes (``is_pinned``, no
``tie_group`` on a pinned row or on a lone leftover), so a finished tournament
that is never recalculated again still reads right. Then ``manual_positions``
and the ``manual_override`` step are removed from every stage's settings.

``downgrade()`` writes the pins back as ``manual_positions``; the old code
re-appends ``manual_override`` to every order on its own.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "stpin01"
down_revision: str | Sequence[str] | None = "varcap01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "standing_pin",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("stage_id", sa.BigInteger(), nullable=False),
        sa.Column("stage_item_id", sa.BigInteger(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 1", name="ck_standing_pin_position"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_item_id"], ["tournament.stage_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["tournament.team.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        schema="tournament",
    )
    op.create_index("ix_tournament_standing_pin_tournament_id", "standing_pin", ["tournament_id"], schema="tournament")
    op.create_index("ix_tournament_standing_pin_team_id", "standing_pin", ["team_id"], schema="tournament")
    op.create_index(
        "uq_standing_pin_team",
        "standing_pin",
        ["stage_id", "stage_item_id", "team_id"],
        unique=True,
        schema="tournament",
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "uq_standing_pin_position",
        "standing_pin",
        ["stage_id", "stage_item_id", "position"],
        unique=True,
        schema="tournament",
        postgresql_nulls_not_distinct=True,
    )
    op.add_column(
        "standing",
        sa.Column("is_pinned", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="tournament",
    )

    op.execute(
        r"""
        INSERT INTO tournament.standing_pin (tournament_id, stage_id, stage_item_id, team_id, position)
        SELECT st.tournament_id, st.stage_id, st.stage_item_id, st.team_id, st.position
        FROM tournament.stage s
        CROSS JOIN LATERAL json_each_text(s.settings_json -> 'manual_positions') AS mp(team_key, place)
        JOIN tournament.standing st ON st.stage_id = s.id AND st.team_id::text = mp.team_key
        WHERE json_typeof(s.settings_json -> 'manual_positions') = 'object'
          AND mp.place ~ '^[0-9]+$'
          AND st.position = mp.place::int
          AND st.position >= 1
          AND st.tie_group IS NOT NULL
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE tournament.standing st
        SET is_pinned = true, tie_group = NULL
        FROM tournament.standing_pin p
        WHERE p.stage_id = st.stage_id
          AND p.stage_item_id IS NOT DISTINCT FROM st.stage_item_id
          AND p.team_id = st.team_id
        """
    )
    # A cluster its pins emptied down to one team: nobody is left to be tied with.
    op.execute(
        """
        UPDATE tournament.standing st
        SET tie_group = NULL
        FROM (
            SELECT stage_id, stage_item_id, tie_group
            FROM tournament.standing
            WHERE tie_group IS NOT NULL
            GROUP BY stage_id, stage_item_id, tie_group
            HAVING count(*) = 1
        ) lone
        WHERE st.stage_id = lone.stage_id
          AND st.stage_item_id IS NOT DISTINCT FROM lone.stage_item_id
          AND st.tie_group = lone.tie_group
        """
    )

    op.execute(
        """
        UPDATE tournament.stage
        SET settings_json = (settings_json::jsonb - 'manual_positions')::json
        WHERE settings_json IS NOT NULL AND settings_json::jsonb ? 'manual_positions'
        """
    )
    op.execute(
        """
        UPDATE tournament.stage
        SET settings_json = jsonb_set(
            settings_json::jsonb,
            '{tiebreak_order}',
            COALESCE(
                (
                    SELECT jsonb_agg(e.metric ORDER BY e.ord)
                    FROM jsonb_array_elements(settings_json::jsonb -> 'tiebreak_order') WITH ORDINALITY AS e(metric, ord)
                    WHERE e.metric <> '"manual_override"'::jsonb
                ),
                '[]'::jsonb
            )
        )::json
        WHERE settings_json IS NOT NULL
          AND jsonb_typeof(settings_json::jsonb -> 'tiebreak_order') = 'array'
          AND settings_json::jsonb -> 'tiebreak_order' @> '["manual_override"]'::jsonb
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE tournament.stage s
        SET settings_json = jsonb_set(COALESCE(s.settings_json::jsonb, '{}'::jsonb), '{manual_positions}', p.positions)::json
        FROM (
            SELECT stage_id, jsonb_object_agg(team_id::text, position) AS positions
            FROM tournament.standing_pin
            GROUP BY stage_id
        ) p
        WHERE p.stage_id = s.id
        """
    )
    op.drop_column("standing", "is_pinned", schema="tournament")
    op.drop_index("uq_standing_pin_position", table_name="standing_pin", schema="tournament")
    op.drop_index("uq_standing_pin_team", table_name="standing_pin", schema="tournament")
    op.drop_index("ix_tournament_standing_pin_team_id", table_name="standing_pin", schema="tournament")
    op.drop_index("ix_tournament_standing_pin_tournament_id", table_name="standing_pin", schema="tournament")
    op.drop_table("standing_pin", schema="tournament")
