"""Drop ``tournament.stage.split_lower_bracket`` -- the contract step of ``bsplit01``.

Revision ID: bsplit02
Revises: btmpl01
Create Date: 2026-10-02 00:00:00.000000

GATED -- fail-closed (CONTRIBUTING.md, "Destructive migrations are gated"; the
same pattern as the 2026-07 Challonge / predictions drops). Expand happened in
two releases: ``bsplit01`` moved every reader and writer to ``advance_upper_count``
and kept the column, and the release after it removed the ORM field. The drop is
safe only once THAT release is the one serving, because migrations run from the
new image while the previous release still handles traffic -- and the release
before it still selects the column on every stage read.

So this runs only with ``OWT_APPLY_SPLIT_LOWER_BRACKET_DROP=1`` in the migration
environment (``backend/env/app.env`` on the host: ``app-svc`` runs ``alembic``).
Without the flag ``upgrade()`` is a no-op stamp, and alembic never re-runs a
stamped revision: deploying this file without the flag means the drop needs a
fresh migration. Set the flag BEFORE the deploy that carries this file, remove it
after.
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "bsplit02"
down_revision: str | Sequence[str] | None = "btmpl01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETRYABLE_SQLSTATES = frozenset({"55P03", "40P01"})
LOCK_TIMEOUT = "3s"
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0


def _take_locks() -> None:
    """Lock ``tournament.stage`` before changing it, retrying past busy readers.

    Each attempt is its own SAVEPOINT so a cancelled statement does not abort the
    transaction alembic wraps the migration in (see ``bsplit01``).
    """
    bind = op.get_bind()
    bind.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    for attempt in range(1, LOCK_ATTEMPTS + 1):
        savepoint = bind.begin_nested()
        try:
            bind.execute(sa.text("LOCK TABLE tournament.stage IN ACCESS EXCLUSIVE MODE"))
        except OperationalError as exc:
            savepoint.rollback()
            if getattr(exc.orig, "sqlstate", None) not in RETRYABLE_SQLSTATES or attempt == LOCK_ATTEMPTS:
                raise
            time.sleep(LOCK_BACKOFF_SECONDS)
        else:
            savepoint.commit()
            return


def upgrade() -> None:
    if os.environ.get("OWT_APPLY_SPLIT_LOWER_BRACKET_DROP") != "1":
        return
    _take_locks()
    op.execute("ALTER TABLE tournament.stage DROP COLUMN IF EXISTS split_lower_bracket")


def downgrade() -> None:
    """Puts the column back with what the pre-``bsplit01`` code reads from it: true
    for every double elimination that has a ``bracket_lower`` item. ``IF NOT
    EXISTS`` because an ungated run of ``upgrade()`` never dropped it."""
    _take_locks()
    op.execute(
        "ALTER TABLE tournament.stage ADD COLUMN IF NOT EXISTS split_lower_bracket boolean NOT NULL DEFAULT false"
    )
    op.execute(
        "UPDATE tournament.stage s SET split_lower_bracket = true "
        "WHERE s.stage_type::text = 'double_elimination' AND EXISTS ("
        "  SELECT 1 FROM tournament.stage_item i WHERE i.stage_id = s.id AND i.type::text = 'bracket_lower'"
        ")"
    )
