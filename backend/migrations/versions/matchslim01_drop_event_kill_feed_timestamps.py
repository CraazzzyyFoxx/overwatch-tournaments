"""Drop ``created_at``/``updated_at`` from ``matches.event`` and ``matches.kill_feed``.

Revision ID: matchslim01
Revises: rankdedup01
Create Date: 2026-09-10 00:00:00.000000

Same case as ``statslim01`` for ``matches.statistics``, two tables over: the
parser deletes and re-inserts a match's rows wholesale on every (re)parse, so
``created_at`` records when the log was last processed -- the match's fact, not
the event's -- and ``updated_at`` is NULL on 99% of rows (the rest is the
user-merge repointing ``user_id``). Every reader (the kill-feed timeline, the
admin match counters) filters on ``match_id`` and reads the event columns;
none names a timestamp. 16 bytes on 1.2M rows, ~19 MB on a production restore.

Order-free: reads never touched the columns, the bulk insert never named them
(``server_default``/``onupdate`` render nothing into an INSERT), and the one
``UPDATE`` -- the user merge -- targets ``user_id``/``killer_id``/``victim_id``
with an ``onupdate`` on the old model, so old code against the new schema
fails only there and only until the container restarts, exactly as with
``statslim01``.

Space comes back through the parser's own delete-and-reinsert as matches are
re-parsed; ``VACUUM FULL`` on either table is optional and small.
"""

import time
from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision: str = "matchslim01"
down_revision: str | Sequence[str] | None = "rankdedup01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCK_NOT_AVAILABLE = "55P03"
LOCK_TIMEOUT = "3s"
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0

TABLES = ("matches.event", "matches.kill_feed")


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
    for table in TABLES:
        _with_lock_retry(
            lambda table=table: bind.execute(
                sa.text(f"ALTER TABLE {table} DROP COLUMN created_at, DROP COLUMN updated_at")
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    # Lossy: the parse timestamps are gone. Existing rows get ``now()`` -- honest,
    # since nothing ever read the column. A constant default adds the column
    # without rewriting the table.
    for table in TABLES:
        _with_lock_retry(
            lambda table=table: bind.execute(
                sa.text(
                    f"ALTER TABLE {table} "
                    "ADD COLUMN created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                    "ADD COLUMN updated_at TIMESTAMPTZ"
                )
            )
        )
