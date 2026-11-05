"""``registration.registration_entry``: participation moves from the profile to the registration node (spec §4.5).

Revision ID: flowP3_04
Revises: flowP3_03
Create Date: 2026-11-05 00:00:00.000000

Every registration gets one entry in the tournament's registration node (``flowP3_01`` left every tournament exactly
one, which the upgrade asserts), carrying the review decision, check-in, balancer state and reserve / substitute flags
the profile held. ``reviewed_at`` / ``reviewed_by`` move too: approval is per intake (spec issue 5). The sheet feed and
the registering teams name their node. Downgrade copies the lowest-id node's entry back onto the profile.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "flowP3_04"
down_revision: str | Sequence[str] | None = "flowP3_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NODE = "tournament.flow_node.id"
_MOVED = (
    "status",
    "balancer_status",
    "exclude_reason",
    "is_reserve",
    "is_substitute",
    "checked_in",
    "checked_in_at",
    "checked_in_by",
    "reviewed_at",
    "reviewed_by",
)


def upgrade() -> None:
    bind = op.get_bind()
    count = "SELECT tournament_id FROM tournament.flow_node WHERE kind = 'registration' GROUP BY 1 HAVING count(*) {}"
    many = bind.execute(sa.text(count.format("> 1"))).all()
    if many:
        raise RuntimeError(f"tournaments with several registration nodes: {[row[0] for row in many]}")

    op.create_table(
        "registration_entry",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registration_node_id", sa.BigInteger(), sa.ForeignKey(_NODE, ondelete="RESTRICT"), nullable=False),
        sa.Column(
            "registration_id",
            sa.BigInteger(),
            sa.ForeignKey("registration.registration.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        sa.Column("checked_in", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checked_in_by", sa.BigInteger(), sa.ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("balancer_status", sa.String(32), server_default="not_in_balancer", nullable=False),
        sa.Column("exclude_reason", sa.String(64), nullable=True),
        sa.Column("is_reserve", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_substitute", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.BigInteger(), sa.ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.BigInteger(), sa.ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True),
        schema="registration",
    )
    op.create_index(
        "ix_registration_entry_registration_node_id", "registration_entry", ["registration_node_id"],
        schema="registration",
    )  # fmt: skip
    op.create_index(
        "ix_registration_entry_registration_id", "registration_entry", ["registration_id"], schema="registration"
    )
    op.create_index(
        "uq_registration_entry_node_registration", "registration_entry", ["registration_node_id", "registration_id"],
        unique=True, schema="registration", postgresql_where=sa.text("deleted_at IS NULL"),
    )  # fmt: skip
    op.create_index(
        "ix_registration_entry_node_balancer_status", "registration_entry",
        ["registration_node_id", "status", "balancer_status"],
        schema="registration", postgresql_where=sa.text("deleted_at IS NULL"),
    )  # fmt: skip

    # One entry per registration, soft-deleted profiles included: the entry carries the profile's deletion.
    op.execute(
        """
        INSERT INTO registration.registration_entry (
            registration_node_id, registration_id, status, checked_in, checked_in_at, checked_in_by, balancer_status,
            exclude_reason, is_reserve, is_substitute, reviewed_at, reviewed_by, created_at, updated_at, deleted_at,
            deleted_by
        )
        SELECT n.id, r.id, r.status, r.checked_in, r.checked_in_at, r.checked_in_by, r.balancer_status,
               r.exclude_reason, r.is_reserve, r.is_substitute, r.reviewed_at, r.reviewed_by, r.submitted_at,
               r.updated_at, r.deleted_at, r.deleted_by
        FROM registration.registration r
        JOIN tournament.flow_node n ON n.tournament_id = r.tournament_id AND n.kind = 'registration'
        """
    )
    entries, registrations = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM registration.registration_entry),"
            " (SELECT count(*) FROM registration.registration)"
        )
    ).one()
    if entries != registrations:
        raise RuntimeError(
            f"{registrations} registrations but {entries} entries: a tournament has no registration node"
        )

    for table in ("google_sheet_feed", "team"):
        column = sa.Column("registration_node_id", sa.BigInteger(), sa.ForeignKey(_NODE, ondelete="RESTRICT"))
        op.add_column(table, column, schema="registration")
        op.execute(
            f"""
            UPDATE registration.{table} t SET registration_node_id = n.id
            FROM tournament.flow_node n
            WHERE n.tournament_id = t.tournament_id AND n.kind = 'registration'
            """
        )
        orphans = bind.execute(sa.text(f"SELECT id FROM registration.{table} WHERE registration_node_id IS NULL")).all()
        if orphans:
            raise RuntimeError(f"registration.{table} rows without a registration node: {[row[0] for row in orphans]}")
        op.alter_column(table, "registration_node_id", nullable=False, schema="registration")
        op.create_index(
            f"ix_{table}_registration_node_id", table, ["registration_node_id"], schema="registration",
        )  # fmt: skip

    op.drop_index("ix_registration_tournament_balancer_status", table_name="registration", schema="registration")
    for column in _MOVED:
        op.drop_column("registration", column, schema="registration")


def downgrade() -> None:
    op.add_column(
        "registration",
        sa.Column("status", sa.String(32), server_default="pending", nullable=False),
        schema="registration",
    )
    op.add_column(
        "registration",
        sa.Column("balancer_status", sa.String(32), server_default="not_in_balancer", nullable=False),
        schema="registration",
    )
    op.add_column("registration", sa.Column("exclude_reason", sa.String(64), nullable=True), schema="registration")
    for column in ("is_reserve", "is_substitute", "checked_in"):
        op.add_column(
            "registration",
            sa.Column(column, sa.Boolean(), server_default="false", nullable=False),
            schema="registration",
        )
    op.add_column(
        "registration", sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True), schema="registration"
    )
    op.add_column(
        "registration", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True), schema="registration"
    )
    for column in ("checked_in_by", "reviewed_by"):
        op.add_column(
            "registration",
            sa.Column(column, sa.BigInteger(), sa.ForeignKey("auth.user.id", ondelete="SET NULL"), nullable=True),
            schema="registration",
        )
    op.execute(
        """
        UPDATE registration.registration r SET
            status = e.status, balancer_status = e.balancer_status, exclude_reason = e.exclude_reason,
            is_reserve = e.is_reserve, is_substitute = e.is_substitute, checked_in = e.checked_in,
            checked_in_at = e.checked_in_at, checked_in_by = e.checked_in_by, reviewed_at = e.reviewed_at,
            reviewed_by = e.reviewed_by
        FROM registration.registration_entry e
        WHERE e.registration_id = r.id AND e.registration_node_id = (
            SELECT min(n.id) FROM tournament.flow_node n
            WHERE n.tournament_id = r.tournament_id AND n.kind = 'registration'
        )
        """
    )
    op.create_index(
        "ix_registration_tournament_balancer_status", "registration", ["tournament_id", "status", "balancer_status"],
        schema="registration", postgresql_where=sa.text("deleted_at IS NULL"),
    )  # fmt: skip

    op.drop_index("ix_team_registration_node_id", table_name="team", schema="registration")
    op.drop_column("team", "registration_node_id", schema="registration")
    op.drop_index("ix_google_sheet_feed_registration_node_id", table_name="google_sheet_feed", schema="registration")
    op.drop_column("google_sheet_feed", "registration_node_id", schema="registration")
    op.drop_table("registration_entry", schema="registration")
