"""Index the "newest ranked snapshot per (account, role)" probe.

Revision ID: ranklatest01
Revises: statslim01
Create Date: 2026-09-10 00:00:00.000000

``overwatch_rank.rank_snapshot`` is an append-only time series: the collector
writes one row per role per poll, every ``interval_seconds`` (15 min by
default). Both registrations lists (admin ``reg_list`` and the public
participants page, via the roster engine's ``ow`` rank layer) asked it for the
latest rank of every registrant with ``DISTINCT ON (user_id, social_account_id,
role) ... ORDER BY captured_at DESC`` over ``user_id IN (...)`` -- a fetch and
sort of every snapshot those players ever had, growing without bound through a
season, on every render.

``fetch_latest_ow_ranks_by_account`` now enumerates the (account x role) pairs
and takes ``ORDER BY captured_at DESC LIMIT 1`` per pair in a LATERAL join. This
index is what makes each of those a single descent: the existing
``ix_rank_snapshot_series_captured`` has ``platform`` between ``role`` and
``captured_at``, so it cannot serve a newest-first walk across platforms.
Partial on the same predicate the query applies, so an account that is
unranked in a role (``is_ranked = false`` on every poll) has no entries to walk.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ranklatest01"
down_revision: str | Sequence[str] | None = "statslim01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_rank_snapshot_latest_ranked",
        "rank_snapshot",
        ["social_account_id", "role", sa.literal_column("captured_at DESC")],
        schema="overwatch_rank",
        postgresql_where=sa.text("rank_value IS NOT NULL AND is_ranked IS TRUE"),
    )


def downgrade() -> None:
    op.drop_index("ix_rank_snapshot_latest_ranked", table_name="rank_snapshot", schema="overwatch_rank")
