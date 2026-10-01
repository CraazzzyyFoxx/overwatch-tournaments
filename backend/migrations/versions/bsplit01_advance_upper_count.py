"""Per-group upper/lower split: ``advance_upper_count`` replaces ``split_lower_bracket``.

Revision ID: bsplit01
Revises: owmapfix01
Create Date: 2026-10-01 00:00:00.000000

Spec §3.7. How many of a group's advancing teams start in the Upper bracket stops
being a boolean on the playoff ("split it in half") and becomes a number on the
group stage that feeds it -- ``tournament.stage.advance_upper_count``, overridable
per group on ``tournament.stage_item``. NULL on both means every advancing team
starts Upper, which is what a non-split playoff did.

Existing split stages are carried over: a split stage that held both halves in ONE
bracket item always gets a real ``bracket_lower`` item with the inputs that used to
be cut off the end of the seed list, and when the group stage that fed it can be
identified that stage gets ``a - a // 2`` (exactly what ``advance_split`` computed).
Matches are not touched.

``tournament.stage.split_lower_bracket`` is NOT dropped here (CONTRIBUTING.md,
"Destructive migrations are gated"): this revision runs from the new image while
the old containers still serve, and they select the column on every stage read.
It stays on the table and on the ORM model with no reader or writer; a later,
flag-gated contract migration drops both in one deploy.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "bsplit01"
down_revision: str | Sequence[str] | None = "owmapfix01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETRYABLE_SQLSTATES = frozenset({"55P03", "40P01"})
LOCK_TIMEOUT = "3s"
LOCK_ATTEMPTS = 40
LOCK_BACKOFF_SECONDS = 6.0
_EXCLUSIVE = "tournament.stage, tournament.stage_item, tournament.stage_item_input"

_QUALIFYING = "('round_robin','swiss','ffa_league')"


def _take_locks() -> None:
    """Take every lock this revision needs, before it changes anything.

    Each attempt is its own SAVEPOINT: a cancelled or deadlocked statement
    aborts the transaction alembic wraps the migration in, and rolling the
    savepoint back both restores that transaction and releases whatever locks
    the attempt did get. ``SET LOCAL`` is issued outside the savepoint so a
    rollback does not also roll back the timeout.
    """
    bind = op.get_bind()
    bind.execute(sa.text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    for attempt in range(1, LOCK_ATTEMPTS + 1):
        savepoint = bind.begin_nested()
        try:
            bind.execute(sa.text(f"LOCK TABLE {_EXCLUSIVE} IN ACCESS EXCLUSIVE MODE"))
        except OperationalError as exc:
            savepoint.rollback()
            if getattr(exc.orig, "sqlstate", None) not in RETRYABLE_SQLSTATES or attempt == LOCK_ATTEMPTS:
                raise
            time.sleep(LOCK_BACKOFF_SECONDS)
        else:
            savepoint.commit()
            return


def _source_stage_id(bind, stage_id: int, tournament_id: int, stage_order: int) -> int | None:
    """The group stage feeding ``stage_id``, or None when it is not unique.

    First choice is what the stage is actually wired to. A playoff wired to
    nothing yet falls back to the single qualifying stage of the latest earlier
    phase -- the same rule ``_preceding_group_stage`` uses at runtime.
    """
    wired = bind.execute(
        sa.text(
            "SELECT DISTINCT si.stage_id FROM tournament.stage_item_input i "
            "JOIN tournament.stage_item si ON si.id = i.source_stage_item_id "
            "JOIN tournament.stage_item t ON t.id = i.stage_item_id "
            "WHERE t.stage_id = :stage_id"
        ),
        {"stage_id": stage_id},
    ).all()
    if len(wired) == 1:
        return wired[0][0]
    if wired:
        return None

    preceding = bind.execute(
        sa.text(
            "SELECT id FROM tournament.stage "
            f"WHERE tournament_id = :tournament_id AND stage_type::text IN {_QUALIFYING} "
            'AND "order" = ('
            '  SELECT max("order") FROM tournament.stage '
            f"  WHERE tournament_id = :tournament_id AND stage_type::text IN {_QUALIFYING} "
            '  AND "order" < :stage_order'
            ")"
        ),
        {"tournament_id": tournament_id, "stage_order": stage_order},
    ).all()
    return preceding[0][0] if len(preceding) == 1 else None


def _split_single_item(bind, stage_id: int) -> None:
    """Give a one-item split stage the ``bracket_lower`` item it never had.

    The old ``bracket_seeds`` cut the single item's seed list in half on every
    read; now the lower half has to be a real item. The cut is the same one:
    non-EMPTY inputs by slot, everything past ``(n + 1) // 2`` moves over and is
    renumbered from slot 1. Matches stay on the original item.
    """
    if bind.execute(
        sa.text("SELECT 1 FROM tournament.stage_item WHERE stage_id = :id AND type::text = 'bracket_lower'"),
        {"id": stage_id},
    ).first():
        return

    row = bind.execute(
        sa.text('SELECT id FROM tournament.stage_item WHERE stage_id = :id ORDER BY "order", id LIMIT 1'),
        {"id": stage_id},
    ).first()
    if row is None:
        return
    main_item_id = row[0]

    inputs = bind.execute(
        sa.text(
            "SELECT id FROM tournament.stage_item_input "
            "WHERE stage_item_id = :id AND input_type::text <> 'empty' ORDER BY slot"
        ),
        {"id": main_item_id},
    ).all()
    moved = inputs[(len(inputs) + 1) // 2 :]
    if not moved:
        return

    next_order = bind.execute(
        sa.text('SELECT coalesce(max("order"), -1) + 1 FROM tournament.stage_item WHERE stage_id = :id'),
        {"id": stage_id},
    ).scalar_one()
    new_item_id = bind.execute(
        sa.text(
            'INSERT INTO tournament.stage_item (stage_id, name, type, "order", created_at) '
            "VALUES (:stage_id, 'Lower bracket', 'bracket_lower', :next_order, now()) RETURNING id"
        ),
        {"stage_id": stage_id, "next_order": next_order},
    ).scalar_one()

    for slot, (input_id,) in enumerate(moved, start=1):
        bind.execute(
            sa.text("UPDATE tournament.stage_item_input SET stage_item_id = :new, slot = :slot WHERE id = :id"),
            {"new": new_item_id, "slot": slot, "id": input_id},
        )


def upgrade() -> None:
    _take_locks()
    op.add_column("stage", sa.Column("advance_upper_count", sa.Integer(), nullable=True), schema="tournament")
    op.add_column("stage_item", sa.Column("advance_upper_count", sa.Integer(), nullable=True), schema="tournament")
    bind = op.get_bind()
    split_stages = bind.execute(
        sa.text(
            'SELECT id, tournament_id, "order" FROM tournament.stage '
            "WHERE stage_type::text = 'double_elimination' AND split_lower_bracket"
        )
    ).all()
    for stage_id, tournament_id, stage_order in split_stages:
        # The item split is what the stage reads today; it has to happen even when
        # the backfill below cannot find the group stage that fed the split.
        _split_single_item(bind, stage_id)
        source_id = _source_stage_id(bind, stage_id, tournament_id, stage_order)
        if source_id is None:
            print(f"bsplit01: stage {stage_id}: no single source group stage, upper count not backfilled")
            continue
        # advance - advance // 2: the old advance_split's upper share.
        bind.execute(
            sa.text(
                "UPDATE tournament.stage SET advance_upper_count = advance_count - advance_count / 2 "
                "WHERE id = :id AND advance_count IS NOT NULL"
            ),
            {"id": source_id},
        )
        bind.execute(
            sa.text(
                "UPDATE tournament.stage_item SET advance_upper_count = advance_count - advance_count / 2 "
                "WHERE stage_id = :id AND advance_count IS NOT NULL"
            ),
            {"id": source_id},
        )


def downgrade() -> None:
    """Restores what the old code reads, not the inputs: the flag is set again for
    every double elimination that has a ``bracket_lower`` item (a stage split after
    this revision never wrote it), while a stage that got its lower item here keeps
    it and the inputs moved into it -- the same bracket, wired explicitly instead of
    cut in half on every read."""
    _take_locks()
    op.get_bind().execute(
        sa.text(
            "UPDATE tournament.stage s SET split_lower_bracket = true "
            "WHERE s.stage_type::text = 'double_elimination' AND EXISTS ("
            "  SELECT 1 FROM tournament.stage_item i WHERE i.stage_id = s.id AND i.type::text = 'bracket_lower'"
            ")"
        )
    )
    op.drop_column("stage_item", "advance_upper_count", schema="tournament")
    op.drop_column("stage", "advance_upper_count", schema="tournament")
