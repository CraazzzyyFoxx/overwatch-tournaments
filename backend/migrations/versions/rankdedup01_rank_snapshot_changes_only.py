"""Collapse ``overwatch_rank.rank_snapshot`` to a series of changes.

Revision ID: rankdedup01
Revises: ranktrim01
Create Date: 2026-09-10 00:00:00.000000

The collector wrote one row per role per platform on every poll, whether or not
anything had moved. On a production restore 2,539,909 of 2,554,038 rows
(99.4%) repeated the row before them in their ``(social_account_id, role,
platform)`` series -- 1.1 GB of heap and index that said "still the same". The
collector now writes only when the observation differs from the series' last
row (``parser-service`` ``changed_ranks``); this migration brings the existing
data to the same shape, keeping the FIRST row of each run of identical
observations -- the moment something changed, which is what a new row means
from now on.

"Identical" is ``division``, ``tier``, ``is_ranked`` AND ``rank_value``. The
mapped value is derived from the first two, but not by one table: ``owemerald01``
rebased the stored rows onto the v2 ladder while the collector kept stamping new
rows from the admin-authored ``parser.rank_mapping`` (platinum 3 is 2200 in one
and 2700 in the other), so the same native rank appears with two values along a
series. Comparing on native rank alone would keep the OLDER value as the
series' last word; with ``rank_value`` in the key the mapping switch starts a
new run and the newest row keeps the number every reader sees today. Measured:
the latest ranked row per (account, role) is unchanged for every series.

Rebuild, not DELETE: deleting 2.5M rows across five indexes ran 486 s on the
restore, holding every earlier revision's lock in this one transaction for that
long. Copying the ~16k survivors aside, truncating and re-inserting them takes
seconds, and ``TRUNCATE`` returns the heap to the filesystem, so no
``VACUUM FULL`` afterwards. The table is locked ACCESS EXCLUSIVE for the copy so
a poll cannot land between the snapshot and the truncate; the collector's
inserts wait those seconds.

``battle_tag_state.last_snapshot_id`` goes first: nothing ever read it, and a
table referenced by a foreign key cannot be truncated.
"""

import time
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision: str = "rankdedup01"
down_revision: str | Sequence[str] | None = "ranktrim01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCK_NOT_AVAILABLE = "55P03"
LOCK_TIMEOUT = "3s"
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0

# The first row of every run of identical observations. ``lag`` over the series
# in capture order; ``IS NOT DISTINCT FROM`` so two NULLs (unranked) compare
# equal, which plain ``=`` would not. The ``lag(id)`` guard is what keeps the
# first row of a series that STARTS unranked: without it every comparison but
# ``is_ranked`` would be NULL-vs-NULL true and the row would fall out.
KEEP_CHANGES = """
CREATE TEMPORARY TABLE rank_snapshot_changes ON COMMIT DROP AS
SELECT s.*
FROM overwatch_rank.rank_snapshot AS s
JOIN (
    SELECT id,
           lag(id) OVER w IS NOT NULL
           AND division IS NOT DISTINCT FROM lag(division) OVER w
           AND tier IS NOT DISTINCT FROM lag(tier) OVER w
           AND is_ranked IS NOT DISTINCT FROM lag(is_ranked) OVER w
           AND rank_value IS NOT DISTINCT FROM lag(rank_value) OVER w AS repeats_previous
    FROM overwatch_rank.rank_snapshot
    WINDOW w AS (PARTITION BY social_account_id, role, platform ORDER BY captured_at, id)
) AS runs ON runs.id = s.id
WHERE NOT runs.repeats_previous
"""


def _with_lock_retry(operation: Callable[[], None]) -> None:
    """Run a lock-taking statement, retrying while Postgres refuses it the lock.

    See ``streamvis01_user_stream_visible.py`` for the full rationale; same
    technique as ``statdrop01``/``ranktrim01``.
    """
    bind = op.get_bind()
    bind.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))

    for attempt in range(1, LOCK_ATTEMPTS + 1):
        savepoint = bind.begin_nested()
        try:
            operation()
        except OperationalError as exc:
            savepoint.rollback()
            if getattr(exc.orig, "sqlstate", None) != LOCK_NOT_AVAILABLE:
                raise
            if attempt == LOCK_ATTEMPTS:
                raise
            time.sleep(LOCK_BACKOFF_SECONDS)
        else:
            savepoint.commit()
            return


def upgrade() -> None:
    bind = op.get_bind()
    _with_lock_retry(
        lambda: bind.execute(sa.text("ALTER TABLE overwatch_rank.battle_tag_state DROP COLUMN last_snapshot_id"))
    )
    _with_lock_retry(lambda: bind.execute(sa.text("LOCK TABLE overwatch_rank.rank_snapshot IN ACCESS EXCLUSIVE MODE")))
    bind.execute(sa.text(KEEP_CHANGES))
    bind.execute(sa.text("TRUNCATE overwatch_rank.rank_snapshot"))
    bind.execute(sa.text("INSERT INTO overwatch_rank.rank_snapshot SELECT * FROM rank_snapshot_changes"))


def downgrade() -> None:
    # The removed rows are not recoverable and were not information: each one
    # repeated its predecessor. Only the column comes back, unpopulated.
    bind = op.get_bind()
    _with_lock_retry(
        lambda: bind.execute(
            sa.text(
                "ALTER TABLE overwatch_rank.battle_tag_state "
                "ADD COLUMN last_snapshot_id BIGINT "
                "REFERENCES overwatch_rank.rank_snapshot (id) ON DELETE SET NULL"
            )
        )
    )
