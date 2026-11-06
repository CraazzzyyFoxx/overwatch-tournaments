"""Drop ``tournament.is_league`` and strip the league params from stored achievement condition trees.

Revision ID: flowP6_02_drop_is_league
Revises: flowP4_02_drop_advance
Create Date: 2026-11-06 14:00:00.000000

The league concept goes away (spec 11.5, 15.6): historical league days were merged into one tournament per season by
``python -m scripts.league_merge`` (plan, apply, grant), which reads ``is_league`` and therefore has to finish first.
The upgrade refuses to run while any ``is_league`` row remains, so a deploy started before the merge stops here and
changes nothing past ``flowP6_01_deferrable_fks``. On a database without leagues (CI, fresh installs) it runs alone.

Stored ``is_league`` / ``include_league`` params of ``achievements.rule.condition_tree`` are removed at any depth;
``tournament_type`` keeps working as a parameterless leaf.

The downgrade only re-adds the column (all false): the merge and the stripped params are not reversible.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "flowP6_02_drop_is_league"
down_revision: str | Sequence[str] | None = "flowP4_02_drop_advance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEAGUE_PARAMS = ("is_league", "include_league")


def strip_league_params(tree: Any) -> tuple[Any, bool]:
    """``tree`` without the league params of any leaf, and whether anything was removed."""
    if isinstance(tree, list):
        results = [strip_league_params(item) for item in tree]
        return [t for t, _ in results], any(changed for _, changed in results)
    if not isinstance(tree, dict):
        return tree, False
    stripped: dict[str, Any] = {}
    changed = False
    for key, value in tree.items():
        if key == "params" and isinstance(value, dict):
            kept = {k: v for k, v in value.items() if k not in _LEAGUE_PARAMS}
            changed |= len(kept) != len(value)
            stripped[key] = kept
        else:
            stripped[key], inner = strip_league_params(value)
            changed |= inner
    return stripped, changed


def upgrade() -> None:
    bind = op.get_bind()
    remaining = bind.execute(sa.text("SELECT count(*) FROM tournament.tournament WHERE is_league")).scalar_one()
    if remaining:
        raise RuntimeError(
            f"{remaining} league tournaments remain: run `python -m scripts.league_merge` (plan, apply, grant) "
            "at revision flowP6_01_deferrable_fks first"
        )
    for rule_id, tree in bind.execute(sa.text("SELECT id, condition_tree FROM achievements.rule")).all():
        stripped, changed = strip_league_params(tree)
        if changed:
            bind.execute(
                sa.text("UPDATE achievements.rule SET condition_tree = CAST(:tree AS json) WHERE id = :id"),
                {"tree": json.dumps(stripped), "id": rule_id},
            )
    op.drop_column("tournament", "is_league", schema="tournament")


def downgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column("is_league", sa.Boolean(), nullable=False, server_default=sa.false()),
        schema="tournament",
    )
