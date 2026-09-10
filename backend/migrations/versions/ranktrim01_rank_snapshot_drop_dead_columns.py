"""Drop ``raw_payload``, ``created_at`` and ``updated_at`` from ``overwatch_rank.rank_snapshot``.

Revision ID: ranktrim01
Revises: ranklatest01
Create Date: 2026-09-10 00:00:00.000000

The collector appends one row per role per platform on every poll of every
tracked battle tag (``interval_seconds``, 15 min by default) -- a few million
rows a month that are never pruned. Three columns on each of them are read by
nothing:

- ``raw_payload`` -- the OverFast ``competitive.<platform>.<role>`` object
  (division, tier and three icon URLs). Written by ``RankStateService.record_result``
  and read by no query in the backend; at ~300 bytes of JSONB it was more than
  half of the heap.
- ``created_at`` -- always equal to ``captured_at``, which every reader orders
  and filters on.
- ``updated_at`` -- NULL on every row; the series is append-only and nothing
  updates a snapshot in place (``owemerald01`` rewrote ``rank_value`` via raw
  SQL, which bypasses the ORM ``onupdate``).

The same shape as ``statslim01`` for ``matches.statistics``: the model moves
from ``TimeStampIntegerMixin`` to ``db.Base`` with an explicit ``id``.

``DROP COLUMN`` takes ``ACCESS EXCLUSIVE`` on a table the collector writes to
every few seconds, so the statement runs under the same ``lock_timeout`` retry
loop as ``statdrop01``/``statslim01`` instead of queueing every writer behind a
lock wait. Space is returned to the table's free map lazily by vacuum; a
``VACUUM FULL overwatch_rank.rank_snapshot`` (exclusive lock, off-hours) or
``pg_repack`` compacts it immediately.
"""

import time
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision: str = "ranktrim01"
down_revision: str | Sequence[str] | None = "ranklatest01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCK_NOT_AVAILABLE = "55P03"
LOCK_TIMEOUT = "3s"
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0


def _with_lock_retry(operation: Callable[[], None]) -> None:
    """Run a DDL statement, retrying while Postgres refuses it the lock.

    See ``streamvis01_user_stream_visible.py`` for the full rationale; same
    technique as ``statdrop01``/``statslim01``.
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
    # One statement, one lock acquisition: all three columns leave together.
    _with_lock_retry(
        lambda: bind.execute(
            sa.text(
                "ALTER TABLE overwatch_rank.rank_snapshot "
                "DROP COLUMN raw_payload, DROP COLUMN created_at, DROP COLUMN updated_at"
            )
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    # Lossy: the raw OverFast objects are gone. ``created_at`` is restored from
    # ``captured_at``, which is what it always equalled; ``updated_at`` was NULL.
    _with_lock_retry(
        lambda: bind.execute(
            sa.text(
                "ALTER TABLE overwatch_rank.rank_snapshot "
                "ADD COLUMN raw_payload JSONB, "
                "ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                "ADD COLUMN updated_at TIMESTAMPTZ"
            )
        )
    )
    bind.execute(sa.text("UPDATE overwatch_rank.rank_snapshot SET created_at = captured_at"))
