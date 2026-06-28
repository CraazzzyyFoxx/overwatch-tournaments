"""Re-FK the OverFast rank subsystem from players.battle_tag to players.social_account.

A1 (``social0001``) consolidated ``players.battle_tag`` into ``players.social_account``
(battlenet rows). This migration repoints the rank telemetry tables —
``overwatch_rank.{rank_snapshot,battle_tag_state,fetch_log}`` — from the legacy
``battle_tag_id`` FK to ``social_account_id`` so OW rank collection keys on the
unified identity table. The denormalized ``battle_tag`` string is kept on each row.

Mapping (battlenet was a lossless 1:1 backfill in social0001):
    players.battle_tag bt  ->  players.social_account sa
    ON sa.user_id = bt.user_id
   AND sa.provider = 'battlenet'
   AND sa.username_normalized = <normalized bt.battle_tag>

``DROP COLUMN battle_tag_id`` auto-drops its FK / unique / composite index, so we
don't depend on auto-generated constraint names.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "owrank0002"
down_revision: str | Sequence[str] | None = "social0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RANK_SCHEMA = "overwatch_rank"

# Matches shared.core.social.normalize_social_handle for battlenet (== social0001).
_NORMALIZE = r"lower(replace(regexp_replace(btrim(bt.battle_tag), '\s*#\s*', '#', 'g'), ' ', ''))"

# battle_tag.id -> social_account.id (battlenet). ``lower(username_normalized)`` so
# the mapping holds whether social0001 stored battlenet case-folded or case-preserved.
_FWD_MAP = f"""
    SELECT bt.id AS battle_tag_id, sa.id AS social_account_id
    FROM players.battle_tag bt
    JOIN players.social_account sa
      ON sa.user_id = bt.user_id
     AND sa.provider = 'battlenet'
     AND lower(sa.username_normalized) = {_NORMALIZE}
"""

# social_account.id (battlenet) -> battle_tag.id (lowest id when several map back).
_REV_MAP = f"""
    SELECT sa.id AS social_account_id, min(bt.id) AS battle_tag_id
    FROM players.social_account sa
    JOIN players.battle_tag bt
      ON bt.user_id = sa.user_id
     AND {_NORMALIZE} = lower(sa.username_normalized)
    WHERE sa.provider = 'battlenet'
    GROUP BY sa.id
"""


def upgrade() -> None:
    for table in ("rank_snapshot", "battle_tag_state", "fetch_log"):
        op.execute(
            f'ALTER TABLE {RANK_SCHEMA}.{table} ADD COLUMN social_account_id INTEGER'
        )
        op.execute(
            f"""
            UPDATE {RANK_SCHEMA}.{table} t
            SET social_account_id = m.social_account_id
            FROM ({_FWD_MAP}) m
            WHERE t.battle_tag_id = m.battle_tag_id
            """
        )

    # battle_tag_state.social_account_id must be unique: drop any duplicates that
    # collapsed onto one social account (keep the highest id / most-recent row).
    op.execute(
        f"""
        DELETE FROM {RANK_SCHEMA}.battle_tag_state a
        USING {RANK_SCHEMA}.battle_tag_state b
        WHERE a.social_account_id IS NOT NULL
          AND a.social_account_id = b.social_account_id
          AND a.id < b.id
        """
    )

    # Drop rows that could not be mapped (defensive — none expected for the
    # lossless battlenet backfill). fetch_log keeps NULLs (its FK is SET NULL).
    op.execute(f"DELETE FROM {RANK_SCHEMA}.rank_snapshot WHERE social_account_id IS NULL")
    op.execute(f"DELETE FROM {RANK_SCHEMA}.battle_tag_state WHERE social_account_id IS NULL")

    # Drop the legacy column (auto-drops its FK / unique / composite index).
    for table in ("rank_snapshot", "battle_tag_state", "fetch_log"):
        op.execute(f"ALTER TABLE {RANK_SCHEMA}.{table} DROP COLUMN battle_tag_id")

    # rank_snapshot: NOT NULL + FK (CASCADE) + composite series index.
    op.execute(
        f"ALTER TABLE {RANK_SCHEMA}.rank_snapshot ALTER COLUMN social_account_id SET NOT NULL"
    )
    op.create_foreign_key(
        "rank_snapshot_social_account_id_fkey",
        "rank_snapshot",
        "social_account",
        ["social_account_id"],
        ["id"],
        source_schema=RANK_SCHEMA,
        referent_schema="players",
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_rank_snapshot_series_captured",
        "rank_snapshot",
        ["social_account_id", "role", "platform", "captured_at"],
        schema=RANK_SCHEMA,
    )

    # battle_tag_state: NOT NULL + UNIQUE + FK (CASCADE).
    op.execute(
        f"ALTER TABLE {RANK_SCHEMA}.battle_tag_state ALTER COLUMN social_account_id SET NOT NULL"
    )
    op.create_unique_constraint(
        "battle_tag_state_social_account_id_key",
        "battle_tag_state",
        ["social_account_id"],
        schema=RANK_SCHEMA,
    )
    op.create_foreign_key(
        "battle_tag_state_social_account_id_fkey",
        "battle_tag_state",
        "social_account",
        ["social_account_id"],
        ["id"],
        source_schema=RANK_SCHEMA,
        referent_schema="players",
        ondelete="CASCADE",
    )

    # fetch_log: nullable FK (SET NULL).
    op.create_foreign_key(
        "fetch_log_social_account_id_fkey",
        "fetch_log",
        "social_account",
        ["social_account_id"],
        ["id"],
        source_schema=RANK_SCHEMA,
        referent_schema="players",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    for table in ("rank_snapshot", "battle_tag_state", "fetch_log"):
        op.execute(
            f'ALTER TABLE {RANK_SCHEMA}.{table} ADD COLUMN battle_tag_id INTEGER'
        )
        op.execute(
            f"""
            UPDATE {RANK_SCHEMA}.{table} t
            SET battle_tag_id = m.battle_tag_id
            FROM ({_REV_MAP}) m
            WHERE t.social_account_id = m.social_account_id
            """
        )

    op.execute(
        f"""
        DELETE FROM {RANK_SCHEMA}.battle_tag_state a
        USING {RANK_SCHEMA}.battle_tag_state b
        WHERE a.battle_tag_id IS NOT NULL
          AND a.battle_tag_id = b.battle_tag_id
          AND a.id < b.id
        """
    )
    op.execute(f"DELETE FROM {RANK_SCHEMA}.rank_snapshot WHERE battle_tag_id IS NULL")
    op.execute(f"DELETE FROM {RANK_SCHEMA}.battle_tag_state WHERE battle_tag_id IS NULL")

    for table in ("rank_snapshot", "battle_tag_state", "fetch_log"):
        op.execute(f"ALTER TABLE {RANK_SCHEMA}.{table} DROP COLUMN social_account_id")

    op.execute(
        f"ALTER TABLE {RANK_SCHEMA}.rank_snapshot ALTER COLUMN battle_tag_id SET NOT NULL"
    )
    op.create_foreign_key(
        "rank_snapshot_battle_tag_id_fkey",
        "rank_snapshot",
        "battle_tag",
        ["battle_tag_id"],
        ["id"],
        source_schema=RANK_SCHEMA,
        referent_schema="players",
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_rank_snapshot_series_captured",
        "rank_snapshot",
        ["battle_tag_id", "role", "platform", "captured_at"],
        schema=RANK_SCHEMA,
    )

    op.execute(
        f"ALTER TABLE {RANK_SCHEMA}.battle_tag_state ALTER COLUMN battle_tag_id SET NOT NULL"
    )
    op.create_unique_constraint(
        "battle_tag_state_battle_tag_id_key",
        "battle_tag_state",
        ["battle_tag_id"],
        schema=RANK_SCHEMA,
    )
    op.create_foreign_key(
        "battle_tag_state_battle_tag_id_fkey",
        "battle_tag_state",
        "battle_tag",
        ["battle_tag_id"],
        ["id"],
        source_schema=RANK_SCHEMA,
        referent_schema="players",
        ondelete="CASCADE",
    )

    op.create_foreign_key(
        "fetch_log_battle_tag_id_fkey",
        "fetch_log",
        "battle_tag",
        ["battle_tag_id"],
        ["id"],
        source_schema=RANK_SCHEMA,
        referent_schema="players",
        ondelete="SET NULL",
    )
