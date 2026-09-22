"""Top-hero uniqueness is checked at COMMIT, not per statement.

Revision ID: reghero01
Revises: regres01
Create Date: 2026-09-22 00:00:00.000000

``registration_role_hero`` is written by replacing a role's whole pick list --
the public form, the admin editor and the sheet sync all hand the role a freshly
built collection, because the list is an ORDER and not a set of independent rows.
SQLAlchemy's unit of work emits every INSERT for a table before the DELETEs on
it, so replacing a list with one that shares a hero (a registrant resaving picks
they never touched) hit ``uq_reg_role_hero_role_hero`` mid-flush, and reordering
two picks hits ``uq_reg_role_hero_role_priority`` the same way. Both refused the
write with a 500 for an edit that ends in a perfectly valid state.

Deferring both to commit is the fix at the level the problem lives on: the
constraints still hold over every state the database is ever observed in, and a
transaction is free to pass through an intermediate state that violates them.
The alternative -- an extra flush between the delete and the insert -- would have
to be threaded through every writer and would still leave reordering broken.

Nothing upserts into this table, so losing ``ON CONFLICT`` eligibility (a
deferrable constraint cannot be an arbiter) costs nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "reghero01"
down_revision: str | Sequence[str] | None = "regres01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("uq_reg_role_hero_role_hero", ("role_id", "hero_id")),
    ("uq_reg_role_hero_role_priority", ("role_id", "priority")),
)


def _recreate(*, deferrable: bool) -> None:
    for name, columns in _CONSTRAINTS:
        op.drop_constraint(name, "registration_role_hero", schema="balancer", type_="unique")
        op.create_unique_constraint(
            name,
            "registration_role_hero",
            list(columns),
            schema="balancer",
            deferrable=deferrable,
            initially="DEFERRED" if deferrable else None,
        )


def upgrade() -> None:
    _recreate(deferrable=True)


def downgrade() -> None:
    _recreate(deferrable=False)
