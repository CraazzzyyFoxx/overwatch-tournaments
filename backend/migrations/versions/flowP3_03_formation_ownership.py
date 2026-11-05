"""Formation nodes own teams, players, balances, balancer configs and draft sessions (spec §4.6).

Revision ID: flowP3_03
Revises: flowP3_02
Create Date: 2026-11-05 00:00:00.000000

``team.formation_node_id`` / ``player.formation_node_id`` are nullable and stay NULL for existing rows (NULL is a
tournament-wide team, R2.Q5). ``balance``, ``tournament_config`` and the tournament-owned ``draft.session`` rows move to
the tournament's formation node: ``flowP3_01`` left every tournament exactly one, which the upgrade asserts before it
writes anything. Mix drafts (``tournament_id IS NULL``) keep a NULL node.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "flowP3_03"
down_revision: str | Sequence[str] | None = "flowP3_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NODE = "tournament.flow_node.id"
_OWNED = (("balancer", "balance"), ("balancer", "tournament_config"), ("draft", "session"))
_ACTIVE = "status IN ('setup','ready','live','paused')"


def upgrade() -> None:
    bind = op.get_bind()
    many = bind.execute(
        sa.text(
            "SELECT tournament_id FROM tournament.flow_node WHERE kind = 'formation' GROUP BY 1 HAVING count(*) > 1"
        )
    ).all()
    if many:
        raise RuntimeError(f"tournaments with several formation nodes: {[row[0] for row in many]}")

    for schema, table in _OWNED:
        op.add_column(table, sa.Column("formation_node_id", sa.BigInteger(), nullable=True), schema=schema)
        op.create_foreign_key(
            f"fk_{table}_formation_node_id", table, "flow_node", ["formation_node_id"], ["id"],
            source_schema=schema, referent_schema="tournament", ondelete="CASCADE",
        )  # fmt: skip
        op.execute(
            f"""
            UPDATE {schema}.{table} t SET formation_node_id = n.id
            FROM tournament.flow_node n
            WHERE n.tournament_id = t.tournament_id AND n.kind = 'formation'
            """
        )
        if table != "session":
            orphans = bind.execute(sa.text(f"SELECT id FROM {schema}.{table} WHERE formation_node_id IS NULL")).all()
            if orphans:
                raise RuntimeError(f"{schema}.{table} rows without a formation node: {[row[0] for row in orphans]}")
            op.alter_column(table, "formation_node_id", nullable=False, schema=schema)

    op.drop_constraint("uq_balancer_balance_tournament", "balance", schema="balancer")
    op.create_unique_constraint(
        "uq_balancer_balance_formation_node", "balance", ["formation_node_id"], schema="balancer"
    )
    op.drop_constraint("uq_balancer_tournament_config_tournament", "tournament_config", schema="balancer")
    op.create_unique_constraint(
        "uq_balancer_tournament_config_formation_node", "tournament_config", ["formation_node_id"], schema="balancer"
    )
    op.drop_index("uq_draft_session_active_tournament", table_name="session", schema="draft")
    op.create_index(
        "uq_draft_session_active_formation_node", "session", ["formation_node_id"],
        unique=True, schema="draft", postgresql_where=sa.text(_ACTIVE),
    )  # fmt: skip
    op.create_check_constraint(
        "ck_draft_session_formation_node",
        "session",
        "(tournament_id IS NULL) = (formation_node_id IS NULL)",
        schema="draft",
    )

    for table in ("team", "player"):
        op.add_column(
            table,
            sa.Column("formation_node_id", sa.BigInteger(), sa.ForeignKey(_NODE, ondelete="RESTRICT"), nullable=True),
            schema="tournament",
        )
        op.create_index(f"ix_{table}_formation_node_id", table, ["formation_node_id"], schema="tournament")


def downgrade() -> None:
    for table in ("team", "player"):
        op.drop_index(f"ix_{table}_formation_node_id", table_name=table, schema="tournament")
        op.drop_column(table, "formation_node_id", schema="tournament")

    op.drop_constraint("ck_draft_session_formation_node", "session", schema="draft")
    op.drop_index("uq_draft_session_active_formation_node", table_name="session", schema="draft")
    op.create_index(
        "uq_draft_session_active_tournament", "session", ["tournament_id"],
        unique=True, schema="draft", postgresql_where=sa.text(_ACTIVE),
    )  # fmt: skip
    op.drop_constraint("uq_balancer_tournament_config_formation_node", "tournament_config", schema="balancer")
    op.create_unique_constraint(
        "uq_balancer_tournament_config_tournament", "tournament_config", ["tournament_id"], schema="balancer"
    )
    op.drop_constraint("uq_balancer_balance_formation_node", "balance", schema="balancer")
    op.create_unique_constraint("uq_balancer_balance_tournament", "balance", ["tournament_id"], schema="balancer")
    for schema, table in _OWNED:
        op.drop_column(table, "formation_node_id", schema=schema)
