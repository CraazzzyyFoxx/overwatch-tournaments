"""Four-value tournament status; the phase schedule is dropped.

Revision ID: flowP3_06
Revises: flowP3_05
Create Date: 2026-11-05 00:00:00.000000

The status is derived from the flow nodes (spec §9), so ``tournament.tournamentstatus`` shrinks to ``announcement``,
``live``, ``completed``, ``archived``: ``registration``, ``draft``, ``check_in`` and ``playoffs`` all become ``live``.
The enum cannot shrink while ``tournament.tournament_phase_schedule`` (whose ``status`` column has the type) lives, so
the table is dropped with it, after a check that every row it holds already has its node schedule copy (P2 copied
``registration`` / ``check_in`` to the registration node, ``flowP3_01`` copied ``draft`` / ``live`` to the draft-mode
formation / first stage node). Downgrade recreates the 8-value type, maps ``live`` to itself and recreates the table
empty: phase rows are not restored.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "flowP3_06"
down_revision: str | Sequence[str] | None = "flowP3_05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Phase rows whose target node exists but holds no schedule row of the mapped phase.
_UNCOPIED = """
SELECT count(*)
FROM tournament.tournament_phase_schedule ps
JOIN (VALUES ('registration', 'registration', 'open'), ('check_in', 'registration', 'check_in'),
             ('draft', 'formation', 'start'), ('live', 'stage', 'start')) AS m(status, kind, phase)
  ON m.status = ps.status::text
WHERE EXISTS (SELECT 1 FROM tournament.flow_node n
              WHERE n.tournament_id = ps.tournament_id AND n.kind = m.kind
                AND (m.kind <> 'formation' OR n.config->>'mode' = 'draft'))
  AND NOT EXISTS (SELECT 1 FROM tournament.flow_node n
                  JOIN tournament.flow_node_schedule fs ON fs.node_id = n.id
                  WHERE n.tournament_id = ps.tournament_id AND n.kind = m.kind AND fs.phase = m.phase)
"""

_OLD_VALUES = ("announcement", "registration", "draft", "check_in", "live", "playoffs", "completed", "archived")
_NEW_VALUES = ("announcement", "live", "completed", "archived")


def _enum_sql(values: Sequence[str]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def _swap_status_type(new_values: Sequence[str], mapping: str) -> None:
    op.execute("ALTER TYPE tournament.tournamentstatus RENAME TO tournamentstatus_old")
    op.execute(f"CREATE TYPE tournament.tournamentstatus AS ENUM ({_enum_sql(new_values)})")
    op.execute(
        "ALTER TABLE tournament.tournament ALTER COLUMN status TYPE tournament.tournamentstatus "
        f"USING ({mapping})::tournament.tournamentstatus"
    )
    op.execute("DROP TYPE tournament.tournamentstatus_old")


def upgrade() -> None:
    missing = op.get_bind().scalar(sa.text(_UNCOPIED))
    if missing:
        raise RuntimeError(f"{missing} tournament_phase_schedule row(s) have no flow_node_schedule copy")
    op.drop_table("tournament_phase_schedule", schema="tournament")
    _swap_status_type(
        _NEW_VALUES,
        "CASE status::text WHEN 'announcement' THEN 'announcement' WHEN 'completed' THEN 'completed' "
        "WHEN 'archived' THEN 'archived' ELSE 'live' END",
    )


def downgrade() -> None:
    _swap_status_type(_OLD_VALUES, "status::text")
    op.create_table(
        "tournament_phase_schedule",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(*_OLD_VALUES, name="tournamentstatus", schema="tournament", create_type=False),
            nullable=False,
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_tournament_phase_schedule_window"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tournament_id", "status", name="uq_tournament_phase_schedule_phase"),
        schema="tournament",
    )
    op.create_index(
        op.f("ix_tournament_tournament_phase_schedule_starts_at"),
        "tournament_phase_schedule",
        ["starts_at"],
        unique=False,
        schema="tournament",
    )
    op.create_index(
        op.f("ix_tournament_tournament_phase_schedule_tournament_id"),
        "tournament_phase_schedule",
        ["tournament_id"],
        unique=False,
        schema="tournament",
    )
