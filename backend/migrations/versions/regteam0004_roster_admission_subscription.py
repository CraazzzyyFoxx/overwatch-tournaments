"""Roster edits, organizer admission, lock, eligibility knobs, team subscription.

Revision ID: regteam0004
Revises: matchslim01
Create Date: 2026-09-10 00:00:00.000000

Pure expand. Every column is nullable or server-defaulted, so existing rows
mean "the old contract" without a backfill:

* ``subscription_scope='player'`` keeps the per-player admission gate;
* ``admission='pending'`` is the un-decided organizer axis, independent of
  occupancy ``status`` (forming/complete);
* ``is_team_manager=false`` is "captain only", the privilege that existed before
  this revision;
* team eligibility columns default off / NULL so live events do not grow new
  refusals on deploy day.

``down_revision`` is the current Alembic head, not ``regteam0003``. This repo
keeps one chain; pointing at the previous team-registration revision would
fork the graph.

Every lock this revision needs is taken in one go before the first ALTER (see
``_take_locks``). Acquiring them column by column deadlocked this migration
three deploys running: the transaction sat on ``registration_form`` while a
live request held ``registration`` and reached for the table the migration had
already locked, and Postgres shot the migration as the victim. Migrations run
against a serving fleet here on purpose -- the old containers keep answering
until the new ones are up -- so the fleet is not going to hold still, and the
migration has to stop giving it a window.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

revision: str = "regteam0004"
down_revision: str | Sequence[str] | None = "matchslim01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLSTATE 55P03 (``lock_not_available``): cancelled by ``lock_timeout``.
# SQLSTATE 40P01 (``deadlock_detected``): chosen as the victim of a lock cycle.
# Both mean "the fleet was in the way, try again"; anything else -- a bad type,
# a missing table -- must raise on the first attempt rather than be retried
# forty times and reported as a lock problem.
RETRYABLE_SQLSTATES = frozenset({"55P03", "40P01"})
# Grab the locks quickly or not at all: a queued ACCESS EXCLUSIVE request stalls
# every reader that arrives behind it, so a long wait would turn a metadata
# change into a fleet-wide stall (see ``streamvis01_user_stream_visible.py``).
LOCK_TIMEOUT = "3s"
# ~4 minutes of wall clock, bounded: a genuinely stuck session fails the deploy
# instead of hanging it.
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0

#: Every table the ``op`` calls below alter, so one statement takes the lot.
_EXCLUSIVE = "balancer.registration_form, balancer.registration, balancer.registration_team"
#: The FK targets. ``SHARE ROW EXCLUSIVE`` is what ``ADD CONSTRAINT ... REFERENCES``
#: takes on the referenced table, and it conflicts with ordinary writes -- so a
#: login updating ``auth.user`` is exactly the other half of a cycle.
_REFERENCED = 'auth."user"'


def _take_locks() -> None:
    """Take every lock this revision needs, before it changes anything.

    Each attempt is its own SAVEPOINT: a cancelled or deadlocked statement
    aborts the transaction alembic wraps the migration in, and rolling the
    savepoint back both restores that transaction and releases whatever locks
    the attempt did get -- which is what stops a retry from holding half the
    set and re-forming the same cycle. ``SET LOCAL`` is issued outside the
    savepoint so a rollback does not also roll back the timeout.
    """
    bind = op.get_bind()
    bind.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))

    for attempt in range(1, LOCK_ATTEMPTS + 1):
        savepoint = bind.begin_nested()
        try:
            bind.execute(sa.text(f"LOCK TABLE {_EXCLUSIVE} IN ACCESS EXCLUSIVE MODE"))
            bind.execute(sa.text(f"LOCK TABLE {_REFERENCED} IN SHARE ROW EXCLUSIVE MODE"))
        except OperationalError as exc:
            savepoint.rollback()
            if getattr(exc.orig, "sqlstate", None) not in RETRYABLE_SQLSTATES:
                raise
            if attempt == LOCK_ATTEMPTS:
                raise
            time.sleep(LOCK_BACKOFF_SECONDS)
        else:
            savepoint.commit()
            return


def upgrade() -> None:
    _take_locks()

    op.add_column(
        "registration_form",
        sa.Column("subscription_scope", sa.String(length=16), nullable=False, server_default="player"),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("team_rank_min", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("team_rank_max", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("team_max_rank_spread", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("team_unique_identity", sa.Boolean(), nullable=False, server_default="false"),
        schema="balancer",
    )
    op.add_column(
        "registration_form",
        sa.Column("team_require_discord_guild", sa.Boolean(), nullable=False, server_default="false"),
        schema="balancer",
    )

    op.add_column(
        "registration",
        sa.Column("is_team_manager", sa.Boolean(), nullable=False, server_default="false"),
        schema="balancer",
    )

    op.add_column(
        "registration_team",
        sa.Column("admission", sa.String(length=16), nullable=False, server_default="pending"),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("organizer_notes", sa.Text(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("roster_locked_at", sa.DateTime(timezone=True), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("roster_locked_by", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("subscription_covered_at", sa.DateTime(timezone=True), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("subscription_covered_by", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("subscription_provider", sa.String(length=32), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("subscription_tier_rank", sa.Integer(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "registration_team",
        sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True),
        schema="balancer",
    )
    op.create_foreign_key(
        "fk_registration_team_roster_locked_by",
        "registration_team",
        "user",
        ["roster_locked_by"],
        ["id"],
        source_schema="balancer",
        referent_schema="auth",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_registration_team_subscription_covered_by",
        "registration_team",
        "user",
        ["subscription_covered_by"],
        ["id"],
        source_schema="balancer",
        referent_schema="auth",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    _take_locks()

    op.drop_constraint(
        "fk_registration_team_subscription_covered_by",
        "registration_team",
        schema="balancer",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_registration_team_roster_locked_by",
        "registration_team",
        schema="balancer",
        type_="foreignkey",
    )
    op.drop_column("registration_team", "subscription_expires_at", schema="balancer")
    op.drop_column("registration_team", "subscription_tier_rank", schema="balancer")
    op.drop_column("registration_team", "subscription_provider", schema="balancer")
    op.drop_column("registration_team", "subscription_covered_by", schema="balancer")
    op.drop_column("registration_team", "subscription_covered_at", schema="balancer")
    op.drop_column("registration_team", "roster_locked_by", schema="balancer")
    op.drop_column("registration_team", "roster_locked_at", schema="balancer")
    op.drop_column("registration_team", "organizer_notes", schema="balancer")
    op.drop_column("registration_team", "rejection_reason", schema="balancer")
    op.drop_column("registration_team", "admission", schema="balancer")
    op.drop_column("registration", "is_team_manager", schema="balancer")
    op.drop_column("registration_form", "team_require_discord_guild", schema="balancer")
    op.drop_column("registration_form", "team_unique_identity", schema="balancer")
    op.drop_column("registration_form", "team_max_rank_spread", schema="balancer")
    op.drop_column("registration_form", "team_rank_max", schema="balancer")
    op.drop_column("registration_form", "team_rank_min", schema="balancer")
    op.drop_column("registration_form", "subscription_scope", schema="balancer")
