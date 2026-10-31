"""Achievement rules: the legacy ``Performance`` MVP stat becomes ``ImpactRank`` (``impact_v2``).

Revision ID: impactv202
Revises: impactv201
Create Date: 2026-10-31 12:00:00.000000

``impactv201`` deletes the legacy ``performance`` / ``performance_points`` facts and the stat vocabulary no longer
knows them, so a stored rule naming either would fail validation and read nothing.

* ``Performance`` / ``performance`` (the map placement, 1 = best, ascending) -> ``ImpactRank`` / ``impact_rank`` (same
  placement and direction, now the one MVP source). The new spelling keeps the old one's case style. Every
  ``params.stat`` in an Overwatch rule's ``condition_tree`` is rewritten and ``rule_version`` is bumped, as
  ``AchievementRuleService`` does on any tree change. ``depends_on`` is derived from the leaf types, not from the stat,
  so it stays valid.
* ``PerformancePoints`` / ``performance_points`` (a hand-weighted score) has no comparable target: any rule whose tree
  names it is disabled and its tree left as authored, for an admin to rewrite.

Downgrade restores nothing: the legacy facts and stat names are gone, and which rules were rewritten is not recorded.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "impactv202"
down_revision: str | Sequence[str] | None = "impactv201"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RENAMED = {"Performance": "ImpactRank", "performance": "impact_rank"}
_RETIRED = frozenset({"PerformancePoints", "performance_points"})


def _rewrite(node: Any) -> tuple[Any, bool, bool]:
    """``(tree with every renamed stat, any stat renamed, any retired stat named)``."""
    if isinstance(node, list):
        parts = [_rewrite(child) for child in node]
        return [p[0] for p in parts], any(p[1] for p in parts), any(p[2] for p in parts)
    if not isinstance(node, dict):
        return node, False, False
    out: dict[str, Any] = {}
    renamed = retired = False
    for key, value in node.items():
        if key == "stat" and isinstance(value, str):
            retired = retired or value in _RETIRED
            renamed = renamed or value in _RENAMED
            out[key] = _RENAMED.get(value, value)
        else:
            child, child_renamed, child_retired = _rewrite(value)
            out[key] = child
            renamed, retired = renamed or child_renamed, retired or child_retired
    return out, renamed, retired


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, condition_tree FROM achievements.rule "
            "WHERE discipline = 'overwatch' AND condition_tree::text ILIKE '%performance%'"
        )
    ).all()
    for rule_id, tree in rows:
        rewritten, renamed, retired = _rewrite(tree)
        if retired:
            bind.execute(sa.text("UPDATE achievements.rule SET enabled = false WHERE id = :id"), {"id": rule_id})
        elif renamed:
            bind.execute(
                sa.text(
                    "UPDATE achievements.rule SET condition_tree = CAST(:tree AS json), "
                    "rule_version = rule_version + 1 WHERE id = :id"
                ),
                {"id": rule_id, "tree": json.dumps(rewritten)},
            )


def downgrade() -> None:
    """Data-only upgrade: nothing to restore (see the module docstring)."""
