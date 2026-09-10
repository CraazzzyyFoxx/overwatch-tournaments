"""Drop ``created_at``/``updated_at`` from ``matches.statistics``.

Revision ID: statslim01
Revises: statdrop01
Create Date: 2026-09-10 00:00:00.000000

Two 8-byte timestamps on the largest table in the database, read by nothing.
``grep -rn "MatchStatistics.created_at\\|MatchStatistics.updated_at"`` over the
whole backend returns no hits: there is no retention job, no audit trail and no
sort keyed on them. Nor could there be a meaningful one -- a statistics row's
lifetime is its match's, because ``parser-service`` deletes every row of a match
and re-inserts them wholesale on each log (re-)parse
(``MatchStatisticsRepository.delete_for_match`` + the bulk insert in
``MatchLogFlow.start``), so ``created_at`` records when the log was last
processed, not when anything happened. ``updated_at`` is non-NULL on 92,339 of
27.3M rows (0.34%) on the production restore -- the single in-place writer is
the user-merge repointing ``user_id`` (``services.admin.user_merge``), whose
``sa.update`` fires the column's ``onupdate``. So it records "this player was
merged into another", a fact the merge itself already owns.

Measured on a production restore (27,319,154 rows): a fully rewritten copy of
the table is 2339 MB against the 2764 MB it occupied before, i.e. **425 MB** --
8 bytes per row for ``created_at`` plus the free space a compaction returns
(``updated_at`` is NULL on 99.66% of rows and NULLs cost nothing but a bitmap
that nullable ``hero_id`` already forced). See the reclaim section below for
which half arrives when. The surrogate ``id`` is deliberately kept -- another
216 MB, but 8 bytes is cheap insurance for row addressing this table has not
needed yet, and its expensive part (the 585 MB primary-key index) is already
gone in ``statdrop01``. Keeping it also means the model can stay on a plain
``id`` mapper key instead of a synthetic composite one.

``matches.statistics`` therefore stops inheriting ``TimeStampIntegerMixin`` and
declares ``id`` itself (``shared/models/matches/match.py``).

DEPLOY THE CODE FIRST
---------------------
Unlike ``statdrop01``, this revision is not order-free. Reads are unaffected
either way (every one of the 37 read sites selects columns, never the mapped
entity, and none of them names a timestamp), and so is the bulk insert
(``created_at`` carried a ``server_default`` and ``updated_at`` an ``onupdate``,
so neither ever appeared in the compiled INSERT). But the old model's
``onupdate`` DOES render into ``sa.update`` statements, so a user merge
(``services.admin.user_merge``, the table's only in-place writer) executed by
pre-migration code against a post-migration database would fail on a column
that no longer exists. New code against the old schema is safe -- it simply
stops writing two columns that still have their defaults.

DISK COMES BACK IN TWO HALVES, NEITHER FROM THIS MIGRATION
----------------------------------------------------------
``ALTER TABLE ... DROP COLUMN`` only sets ``attisdropped`` in ``pg_attribute``;
the bytes stay in every existing tuple. Crucially, ``VACUUM FULL`` does NOT
strip them either -- it rewrites tuples through ``rewrite_heap_tuple``, which
preserves the dropped attributes so pre-migration tuples stay readable.
Measured on the dev restore, in this order:

    ALTER TABLE ... DROP COLUMN            2764 MB -> 2764 MB  (metadata only)
    VACUUM FULL matches.statistics         2764 MB -> 2552 MB  (57 s; free-space
                                                                compaction, not
                                                                the columns)
    CREATE TABLE ... AS SELECT * (probe)             2339 MB   (what a real
                                                                rewrite yields)

So ~212 MB is bloat this table had accumulated from its delete-and-reinsert
write pattern, returnable by ``VACUUM FULL`` (ACCESS EXCLUSIVE, ~1 min, needs
~2.4 GB free) whether or not these columns go. The other ~213 MB is
``created_at`` still sitting in old tuples; it drains on its own as matches are
re-parsed, because a re-parse deletes a match's rows and inserts fresh, narrow
ones. Forcing it would mean recreating the table (INSERT .. SELECT + rename),
which also means dropping and rebuilding ``mv_hero_global_stats`` -- a
materialized view binds its source by OID and would silently keep reading the
renamed-away table. Not worth 213 MB.

Neither step can run inside Alembic's single transaction, so both are manual and
optional: the schema is correct without them.

Same lock discipline as ``statdrop01``: ACCESS EXCLUSIVE taken in a gap between
reader transactions via ``lock_timeout`` + retry, rather than queueing every
match page, profile and leaderboard behind it.
"""

import time
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision: str = "statslim01"
down_revision: str | Sequence[str] | None = "statdrop01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCK_NOT_AVAILABLE = "55P03"
LOCK_TIMEOUT = "3s"
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0


def _with_lock_retry(operation: Callable[[], None]) -> None:
    """Run a DDL statement, retrying while Postgres refuses it the lock.

    See ``streamvis01_user_stream_visible.py`` for the full rationale; same
    technique as ``statdrop01``, applied to the column drop.
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
    # One statement, one lock acquisition: both columns leave together.
    _with_lock_retry(
        lambda: bind.execute(sa.text("ALTER TABLE matches.statistics DROP COLUMN created_at, DROP COLUMN updated_at"))
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Lossy, and unavoidably so: the original insertion timestamps are gone.
    # Existing rows get ``now()`` -- honest, since nothing ever read the column
    # and no consumer can be misled by the substitution. A constant default
    # means Postgres adds both columns without rewriting the table.
    _with_lock_retry(
        lambda: bind.execute(
            sa.text(
                "ALTER TABLE matches.statistics "
                "ADD COLUMN created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), "
                "ADD COLUMN updated_at TIMESTAMP WITH TIME ZONE"
            )
        )
    )
