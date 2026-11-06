"""Intake settings move from the registration form (and ``tournament.allow_late_registration``) to the node config.

Revision ID: flowP3_05
Revises: flowP3_04
Create Date: 2026-11-05 00:00:00.000000

Who may take part in a given intake and when is node configuration (spec §4.5); what the person is stays on the
profile / form. Every registration node of a tournament gets the settings of its form; registration nodes of a
tournament without a form get only ``allow_late_registration``. ``registration.form.is_open`` is dropped, not moved:
nothing reads it, a node's status *is* "open" (plan spec issue 7). Downgrade copies the lowest-id registration node's
settings back and leaves ``is_open`` at its server default.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "flowP3_05"
down_revision: str | Sequence[str] | None = "flowP3_04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (name, column type, server default) of every ``registration.form`` column that becomes node config.
_FORM_COLUMNS = (
    ("auto_approve", sa.Boolean(), "false"),
    ("max_participants", sa.Integer(), None),
    ("max_substitutes", sa.Integer(), "0"),
    ("require_subscription", sa.Boolean(), "false"),
    ("subscription_stage", sa.String(16), "check_in"),
    ("subscription_scope", sa.String(16), "player"),
    ("team_rank_min", sa.Integer(), None),
    ("team_rank_max", sa.Integer(), None),
    ("team_max_rank_spread", sa.Integer(), None),
    ("team_unique_identity", sa.Boolean(), "false"),
    ("team_require_discord_guild", sa.Boolean(), "false"),
)


def upgrade() -> None:
    pairs = ", ".join(f"'{name}', f.{name}" for name, _type, _default in _FORM_COLUMNS)
    op.execute(
        f"""
        UPDATE tournament.flow_node n SET config = n.config || jsonb_build_object({pairs})
        FROM registration.form f
        WHERE n.kind = 'registration' AND f.tournament_id = n.tournament_id
        """
    )
    op.execute(
        """
        UPDATE tournament.flow_node n
        SET config = n.config || jsonb_build_object('allow_late_registration', t.allow_late_registration)
        FROM tournament.tournament t
        WHERE n.kind = 'registration' AND t.id = n.tournament_id
        """
    )
    op.drop_column("tournament", "allow_late_registration", schema="tournament")
    op.drop_column("form", "is_open", schema="registration")
    for name, _type, _default in _FORM_COLUMNS:
        op.drop_column("form", name, schema="registration")


def downgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column("allow_late_registration", sa.Boolean(), server_default="false", nullable=False),
        schema="tournament",
    )
    op.add_column(
        "form", sa.Column("is_open", sa.Boolean(), server_default="false", nullable=False), schema="registration"
    )
    for name, column_type, default in _FORM_COLUMNS:
        nullable = default is None
        op.add_column(
            "form",
            sa.Column(name, column_type, server_default=default, nullable=nullable),
            schema="registration",
        )
    first_node = (
        "(SELECT n.config FROM tournament.flow_node n WHERE n.kind = 'registration' AND n.tournament_id = {table}"
        ".tournament_id ORDER BY n.id LIMIT 1)"
    )
    assignments = ", ".join(
        f"{name} = COALESCE(({first_node.format(table='f')} ->> '{name}')::{_cast(column_type)}, f.{name})"
        for name, column_type, _default in _FORM_COLUMNS
    )
    op.execute(f"UPDATE registration.form f SET {assignments}")
    op.execute(
        """
        UPDATE tournament.tournament t SET allow_late_registration = COALESCE((
            SELECT (n.config ->> 'allow_late_registration')::boolean FROM tournament.flow_node n
            WHERE n.kind = 'registration' AND n.tournament_id = t.id ORDER BY n.id LIMIT 1
        ), false)
        """
    )


def _cast(column_type: sa.types.TypeEngine) -> str:
    return {"Boolean": "boolean", "Integer": "integer", "String": "text"}[type(column_type).__name__]
