"""Add the ANNOUNCEMENT phase to ``tournament.tournamentstatus``.

Revision ID: annstat01
Revises: notif003
Create Date: 2026-09-09 00:00:00.000000

A freshly created tournament used to land in REGISTRATION while registration was
in fact closed — the gate is the REGISTRATION row of ``tournament_phase_schedule``
(``shared.services.registration_window``), and a brand-new tournament has none.
The public page therefore announced "Registration" over a form nobody could
submit. ANNOUNCEMENT is that state, named: public and readable, nothing to do
yet, ends when the REGISTRATION row comes due.

``ADD VALUE ... BEFORE`` keeps the enum's sort order aligned with the lifecycle
order, so ``ORDER BY status`` stays meaningful.

Why the column default is dropped rather than moved
---------------------------------------------------
PostgreSQL refuses to *use* an enum label added in the same transaction, and
``migrations/env.py`` wraps the whole ``upgrade`` run in one — so
``SET DEFAULT 'announcement'::tournamentstatus`` cannot live here, in a follow-up
revision, or anywhere in the same run, short of an ``op.execute("COMMIT")``
sleight of hand that leaves Alembic's own transaction dangling.

Dropping the default is the better answer anyway. Every insert the application
makes goes through SQLAlchemy, which supplies the model's Python-side default;
there is no raw ``INSERT INTO tournament.tournament`` anywhere in the codebase.
The default therefore only ever answered for an insert that should not exist,
and answering it with 'registration' is precisely the "registration is open when
it isn't" lie this revision removes. Without it such an insert fails loudly on
NOT NULL instead.

No backfill: every existing tournament keeps the status it has. Rewriting live
rows to a status the running code has never seen is what the phase-schedule
rework refused to do for the same deploy-safety reason, and a tournament sitting
in REGISTRATION today behaves identically afterwards, because openness never
consulted the status in the first place.

No new schedule row either: ANNOUNCEMENT is not in ``SCHEDULABLE_STATUSES`` and
never will be. It has no start of its own (creation is its start) and its end is
already expressed by ``REGISTRATION.starts_at``, which the worker tick reads.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "annstat01"
down_revision: str | Sequence[str] | None = "notif003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE tournament.tournamentstatus ADD VALUE IF NOT EXISTS 'announcement' BEFORE 'registration'"
    )
    op.execute("ALTER TABLE tournament.tournament ALTER COLUMN status DROP DEFAULT")


def downgrade() -> None:
    """Restore the old column default. The enum label stays — PostgreSQL cannot
    drop one, and rebuilding the type would need an exclusive lock on every
    table and index referencing it, for a downgrade nobody runs."""
    op.execute(
        "ALTER TABLE tournament.tournament "
        "ALTER COLUMN status SET DEFAULT 'registration'::tournament.tournamentstatus"
    )
