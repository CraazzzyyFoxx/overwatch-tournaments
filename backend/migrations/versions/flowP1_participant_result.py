"""``tournament.participant_result``: one row per member per finished tournament, backfilled by rule 2.

The member's final team, final placement (NULL when the team has no positive place) and the field size. Backfilled for
every finished tournament with the last-formed team the member played for (the latest non-substitute ``player`` row)
and that team's ``overall_position`` in its last stage by ``stage."order"``; ``source_node_id`` stays NULL until the
formation node table exists.

Stored Overwatch rules whose tree names a leaf that now reads the table gain ``tournament.participant_result`` in
``depends_on``, and ``standing_position`` loses its ``include_groups`` param (a member's placement is the final one,
not a group one); ``rule_version`` is bumped only for a tree that changed, as ``AchievementRuleService`` does.

Downgrade drops the table; the rule rewrite is not restored (which rules were rewritten is not recorded), as
``impactv202`` does.

Revision ID: flowP1_participant_result
Revises: botlobby01
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "flowP1_participant_result"
down_revision: str | Sequence[str] | None = "botlobby01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PR_LEAVES = frozenset(
    {
        "standing_position",
        "standing_record",
        "standing_count",
        "reached_playoffs",
        "tournament_winrate",
        "consecutive",
        "stable_streak",
        "div_change",
    }
)

_BACKFILL = """
INSERT INTO tournament.participant_result
    (tournament_id, workspace_member_id, final_team_id, placement, field_size, source_node_id)
SELECT DISTINCT ON (p.tournament_id, p.workspace_member_id)
       p.tournament_id, p.workspace_member_id, p.team_id,
       (SELECT s.overall_position
          FROM tournament.standing s LEFT JOIN tournament.stage st ON st.id = s.stage_id
         WHERE s.team_id = p.team_id AND s.overall_position > 0
         ORDER BY st."order" DESC NULLS LAST, s.stage_id DESC NULLS LAST, s.id DESC
         LIMIT 1),
       (SELECT count(*) FROM tournament.team tm WHERE tm.tournament_id = p.tournament_id),
       NULL
  FROM tournament.player p
  JOIN tournament.tournament t ON t.id = p.tournament_id
 WHERE t.is_finished AND NOT p.is_substitution
 ORDER BY p.tournament_id, p.workspace_member_id, p.id DESC
"""


def _strip_include_groups(node: Any) -> tuple[Any, bool]:
    """``(tree without any standing_position include_groups param, anything dropped)``."""
    if isinstance(node, list):
        parts = [_strip_include_groups(child) for child in node]
        return [p[0] for p in parts], any(p[1] for p in parts)
    if not isinstance(node, dict):
        return node, False
    out: dict[str, Any] = {}
    changed = False
    for key, value in node.items():
        if key == "params" and node.get("type") == "standing_position" and isinstance(value, dict):
            changed = changed or "include_groups" in value
            out[key] = {k: v for k, v in value.items() if k != "include_groups"}
        else:
            child, child_changed = _strip_include_groups(value)
            out[key] = child
            changed = changed or child_changed
    return out, changed


def _reads_participant_result(node: Any) -> bool:
    if isinstance(node, list):
        return any(_reads_participant_result(child) for child in node)
    if not isinstance(node, dict):
        return False
    return node.get("type") in _PR_LEAVES or any(_reads_participant_result(value) for value in node.values())


def upgrade() -> None:
    op.create_table(
        "participant_result",
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=False),
        sa.Column("final_team_id", sa.BigInteger(), nullable=True),
        sa.Column("placement", sa.Integer(), nullable=True),
        sa.Column("field_size", sa.Integer(), nullable=False),
        sa.Column("source_node_id", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("tournament_id", "workspace_member_id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_member_id"], ["workspace_member.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["final_team_id"], ["tournament.team.id"], ondelete="SET NULL"),
        schema="tournament",
    )
    op.create_index(
        "ix_participant_result_workspace_member_id", "participant_result", ["workspace_member_id"], schema="tournament"
    )
    op.execute(_BACKFILL)

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, condition_tree, depends_on FROM achievements.rule WHERE discipline = 'overwatch'")
    ).all()
    for rule_id, tree, deps in rows:
        if not _reads_participant_result(tree):
            continue
        rewritten, changed = _strip_include_groups(tree)
        bind.execute(
            sa.text(
                "UPDATE achievements.rule SET condition_tree = CAST(:tree AS json), "
                "depends_on = CAST(:deps AS json), rule_version = rule_version + :bump WHERE id = :id"
            ),
            {
                "id": rule_id,
                "tree": json.dumps(rewritten),
                "deps": json.dumps(sorted({*(deps or []), "tournament.participant_result"})),
                "bump": int(changed),
            },
        )


def downgrade() -> None:
    op.drop_index("ix_participant_result_workspace_member_id", table_name="participant_result", schema="tournament")
    op.drop_table("participant_result", schema="tournament")
