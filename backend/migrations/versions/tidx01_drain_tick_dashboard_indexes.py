"""Indexes for the outbox drain, the pick-ban room tick and the dashboard's latest run; drop three that do not pay.

Revision ID: tidx01
Revises: rtexp01
Create Date: 2026-10-26 23:00:00.000000

Created:

* ``public.ix_event_outbox_pending_created (created_at, id) WHERE status IN ('pending', 'failed')`` -- the drain
  (``shared.messaging.outbox``: ``WHERE status IN ('pending', 'failed') AND next_attempt_at <= now ORDER BY
  created_at, id LIMIT n FOR UPDATE SKIP LOCKED``) walks it in order and stops after ``n`` rows. It replaces
  ``ix_event_outbox_status_next_attempt (status, next_attempt_at)``, which found the due rows but could not give their
  order, so every drain sorted all of them before the ``LIMIT``; published rows, the bulk of the table, are not in the
  new index at all.
* ``encounter.ix_pick_ban_session_active_unpaused (encounter_id) WHERE status = 'active' AND paused_at IS NULL`` --
  ``room_reconcile.reconcile_due_rooms``'s per-second scan of the live, timed rooms, joined to ``encounter`` on
  ``encounter_id``.
* ``achievements.ix_achievements_evaluation_run_tournament_created (tournament_id, created_at DESC)`` -- the
  organizer dashboard's newest run per tournament (``latest_evaluation_run_status``); it also serves the FK's
  ``ON DELETE SET NULL`` from ``tournament.tournament``.

Dropped:

* ``tournament.ix_tournament_computation_job_status (status)``: a handful of values and no query filters on status
  alone (``list_jobs`` narrows by tournament or stage first; the active-key lookup has its partial unique index).
* ``tournament.ix_tournament_computation_job_tournament_id (tournament_id)``: the leading column of
  ``ix_tournament_computation_job_tournament_kind (tournament_id, kind)``, which serves the same lookups and the FK.

The daily purges get no index: their scans stop at the first batch of old rows.

Locking, per table:

* ``event_outbox`` is written inside nearly every service transaction and was never purged before the drain-side purge
  landed, so it holds every event ever written. A plain build would block all of those writes for a full-table scan.
  It is built and its old index dropped ``CONCURRENTLY`` (SHARE UPDATE EXCLUSIVE: reads and writes go on) inside
  ``autocommit_block`` -- ``migrations/env.py`` runs the upgrade in one transaction, where ``CONCURRENTLY`` is
  unavailable; precedent ``enclayer01b``. The old index goes only after the new one is valid, so the drain is never
  left without one. An interrupted build leaves an INVALID index that ``IF NOT EXISTS`` would keep; it is dropped
  first, so re-running the upgrade repairs it.
* ``pick_ban_session`` (one row per room), ``evaluation_run`` (one row per evaluation run) and the two
  ``computation_job`` drops (no scan: a drop only unlinks the index) are plain DDL in the migration transaction, with
  ``drift01``'s ``lock_timeout`` so a busy deploy fails fast instead of queueing readers behind the lock. They run
  before the autocommit boundary, which commits them, so their locks are not held across the outbox build.

``autocommit_block`` commits everything before it, earlier revisions of the same upgrade included; a failure in the
concurrent part leaves the transactional part applied and this revision to be re-run. Every statement is idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tidx01"
down_revision: str | Sequence[str] | None = "rtexp01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_IS_INVALID = "SELECT NOT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)"


def _create_outbox_index_concurrently(name: str, definition: str) -> None:
    """``CREATE INDEX CONCURRENTLY`` on ``public.event_outbox``; drops an interrupted run's INVALID leftover first."""
    if op.get_bind().execute(sa.text(_IS_INVALID), {"name": f"public.{name}"}).scalar():
        op.execute(f"DROP INDEX CONCURRENTLY public.{name}")
    op.execute(f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON public.event_outbox {definition}")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_pick_ban_session_active_unpaused ON encounter.pick_ban_session (encounter_id) "
        "WHERE status = 'active' AND paused_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_achievements_evaluation_run_tournament_created "
        "ON achievements.evaluation_run (tournament_id, created_at DESC)"
    )
    op.execute("DROP INDEX IF EXISTS tournament.ix_tournament_computation_job_status")
    op.execute("DROP INDEX IF EXISTS tournament.ix_tournament_computation_job_tournament_id")
    with op.get_context().autocommit_block():
        _create_outbox_index_concurrently(
            "ix_event_outbox_pending_created", "(created_at, id) WHERE status IN ('pending', 'failed')"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.ix_event_outbox_status_next_attempt")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        _create_outbox_index_concurrently("ix_event_outbox_status_next_attempt", "(status, next_attempt_at)")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS public.ix_event_outbox_pending_created")
    op.execute("SET LOCAL lock_timeout = '10s'")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tournament_computation_job_tournament_id "
        "ON tournament.computation_job (tournament_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_tournament_computation_job_status ON tournament.computation_job (status)")
    op.execute("DROP INDEX IF EXISTS achievements.ix_achievements_evaluation_run_tournament_created")
    op.execute("DROP INDEX IF EXISTS encounter.ix_pick_ban_session_active_unpaused")
