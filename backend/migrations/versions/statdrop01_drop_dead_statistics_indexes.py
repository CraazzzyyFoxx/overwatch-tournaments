"""Drop four unused indexes on ``matches.statistics``.

Revision ID: statdrop01
Revises: annstat01
Create Date: 2026-09-09 00:00:00.000000

``matches.statistics`` is the largest relation in the database by a wide margin
-- measured on a production restore (27,319,154 rows): 2764 MB heap plus
1996 MB of indexes, 74% of the whole database. Four of its eleven indexes earn
none of the 1131 MB they occupy:

``match_statistics_pkey`` (585 MB)
    A primary key over the surrogate ``id``. Nothing reads it: there is no
    ``MatchStatistics.id`` reference anywhere in the codebase, no foreign key
    points at ``matches.statistics.id`` (the table's own constraints are all
    outbound -- ``match_id``, ``team_id``, ``user_id``, ``hero_id``), no API
    schema exposes it, and the writer inserts with a plain executemany without
    ``RETURNING`` (``parser-service`` ``MatchLogFlow.start``). Uniqueness is not
    load-bearing either: the writer deletes a match's rows before re-inserting
    them (``MatchStatisticsRepository.delete_for_match``), so duplicates cannot
    arise by construction. ``BaseRepository.get``/``bulk_get``/``list`` -- the
    only generic code that would touch ``self.model.id`` -- is never called for
    this model.

``ix_match_statistics_match_id`` (184 MB) and ``ix_match_statistics_user_id`` (181 MB)
    Strict prefixes of ``ix_match_statistics_match_user_round`` /
    ``ix_match_statistics_match_name_round`` and
    ``ix_match_statistics_user_round_name`` respectively. Verified on the
    restore: the match-page read (``match_id = ? AND hero_id IS NULL``) runs in
    1.86 ms on the composite prefix versus 2.44 ms on the standalone index, and
    the profile hero-stats read in 34.8 ms versus 39.4 ms.

``ix_match_statistics_name`` (181 MB)
    A lone index on a 48-label enum, selectivity 1/48. Its only consumer was
    ``HeroQueries.get_heroes_stats``, which had no callers at all and is deleted
    in the same change.

``ix_match_statistics_team_id`` is deliberately kept: ``team_id`` is a join key
in ``services.user.queries.compare`` and a prefix of nothing here.

Both name spellings are dropped. The long-lived production database names its
single-column indexes ``ix_match_statistics_*``, while ``initial_v6`` creates
them under SQLAlchemy's own convention as ``ix_matches_statistics_*``; a single
spelling would fail on one of the two. Same for the primary key, named
``match_statistics_pkey`` in production and ``statistics_pkey`` by default.

The model keeps ``id``/``primary_key=True`` (it inherits
``TimeStampIntegerMixin``) while the database no longer carries the constraint.
That divergence is intentional and invisible to Alembic, which does not
autogenerate primary-key changes; the ORM needs the primary key only at
metadata level, and nothing loads this table as an ORM entity (every one of the
37 read sites selects columns, never the mapped class). Dropping the column
itself is a separate, lossy step and is not done here.

``DROP INDEX`` needs ACCESS EXCLUSIVE for the instant it unlinks the relation.
``migrations/env.py`` runs the whole upgrade inside one transaction, so
``DROP INDEX CONCURRENTLY`` is unavailable; instead the same
``lock_timeout`` + retry loop as ``enclogsrm1``/``streamvis01`` takes the lock
in a gap between reader transactions rather than queueing every reader behind
it.
"""

import time
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision: str = "statdrop01"
down_revision: str | Sequence[str] | None = "annstat01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCK_NOT_AVAILABLE = "55P03"
LOCK_TIMEOUT = "3s"
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0

# Both spellings of each dead index: production's hand-named ones and the
# ``op.f()``-generated names ``initial_v6`` would have created.
DEAD_INDEXES = (
    "ix_match_statistics_match_id",
    "ix_matches_statistics_match_id",
    "ix_match_statistics_name",
    "ix_matches_statistics_name",
    "ix_match_statistics_user_id",
    "ix_matches_statistics_user_id",
)


def _with_lock_retry(operation: Callable[[], None]) -> None:
    """Run a DDL statement, retrying while Postgres refuses it the lock.

    See ``streamvis01_user_stream_visible.py`` for the full rationale; same
    technique, applied to ``matches.statistics`` -- read by every match page,
    profile and leaderboard.
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

    for index_name in DEAD_INDEXES:
        _with_lock_retry(lambda name=index_name: bind.execute(sa.text(f"DROP INDEX IF EXISTS matches.{name}")))

    _with_lock_retry(
        lambda: bind.execute(
            sa.text(
                "ALTER TABLE matches.statistics "
                "DROP CONSTRAINT IF EXISTS match_statistics_pkey, "
                "DROP CONSTRAINT IF EXISTS statistics_pkey"
            )
        )
    )


def downgrade() -> None:
    # Recreated under the model's own naming, not production's legacy spelling:
    # a downgrade lands the schema where the current metadata says it should be.
    # ``id`` still exists and is still sequence-backed, so the primary key can
    # be rebuilt as-is.
    _with_lock_retry(
        lambda: op.create_primary_key("statistics_pkey", "statistics", ["id"], schema="matches"),
    )
    op.create_index(op.f("ix_matches_statistics_match_id"), "statistics", ["match_id"], unique=False, schema="matches")
    op.create_index(op.f("ix_matches_statistics_name"), "statistics", ["name"], unique=False, schema="matches")
    op.create_index(op.f("ix_matches_statistics_user_id"), "statistics", ["user_id"], unique=False, schema="matches")
