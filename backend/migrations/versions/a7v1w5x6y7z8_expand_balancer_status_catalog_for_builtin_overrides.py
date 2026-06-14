"""expand_balancer_status_catalog_for_builtin_overrides

Revision ID: a7v1w5x6y7z8
Revises: z6u0v4w5x6y7
Create Date: 2026-04-14 23:40:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "a7v1w5x6y7z8"
down_revision = "z6u0v4w5x6y7"
branch_labels = None
depends_on = None


CANONICAL_BUILTINS = [
    ("registration", "pending", "Clock", "#f59e0b", "Pending", "Waiting for moderator review."),
    ("registration", "approved", "CheckCircle2", "#10b981", "Approved", "Registration approved."),
    ("registration", "rejected", "XCircle", "#ef4444", "Rejected", "Registration rejected."),
    ("registration", "withdrawn", "Undo2", "#94a3b8", "Withdrawn", "Registration withdrawn by participant or admin."),
    ("registration", "banned", "ShieldBan", "#ef4444", "Banned", "Registration blocked."),
    ("registration", "insufficient_data", "AlertTriangle", "#f97316", "Incomplete", "Registration data is incomplete."),
    ("balancer", "not_in_balancer", "MinusCircle", "#94a3b8", "Not Added", "Registration is excluded from the balancer pool."),
    ("balancer", "incomplete", "AlertTriangle", "#f97316", "Incomplete", "Registration needs role or rank fixes before balancing."),
    ("balancer", "ready", "CheckCircle2", "#10b981", "Ready", "Registration is ready for the balancer pool."),
]


def upgrade() -> None:
    op.add_column(
        "registration_status",
        sa.Column("kind", sa.String(length=16), nullable=False, server_default="custom"),
        schema="balancer",
    )
    op.drop_constraint(
        "uq_balancer_registration_status_workspace_scope_slug",
        "registration_status",
        schema="balancer",
        type_="unique",
    )
    op.alter_column(
        "registration_status",
        "workspace_id",
        existing_type=sa.Integer(),
        nullable=True,
        schema="balancer",
    )
    op.create_unique_constraint(
        "uq_balancer_registration_status_workspace_scope_slug",
        "registration_status",
        ["workspace_id", "scope", "slug", "kind"],
        schema="balancer",
    )

    bind = op.get_bind()
    insert_stmt = sa.text(
        """
        INSERT INTO balancer.registration_status
            (workspace_id, scope, slug, kind, icon_slug, icon_color, name, description)
        VALUES
            (:workspace_id, :scope, :slug, :kind, :icon_slug, :icon_color, :name, :description)
        """
    )
    bind.execute(
        insert_stmt,
        [
            {
                "workspace_id": None,
                "scope": scope,
                "slug": slug,
                "kind": "builtin",
                "icon_slug": icon_slug,
                "icon_color": icon_color,
                "name": name,
                "description": description,
            }
            for scope, slug, icon_slug, icon_color, name, description in CANONICAL_BUILTINS
        ],
    )
    op.alter_column(
        "registration_status",
        "kind",
        server_default=None,
        schema="balancer",
    )


def downgrade() -> None:
    op.execute("DELETE FROM balancer.registration_status WHERE workspace_id IS NULL AND kind = 'builtin'")
    op.drop_constraint(
        "uq_balancer_registration_status_workspace_scope_slug",
        "registration_status",
        schema="balancer",
        type_="unique",
    )
    op.alter_column(
        "registration_status",
        "workspace_id",
        existing_type=sa.Integer(),
        nullable=False,
        schema="balancer",
    )
    op.create_unique_constraint(
        "uq_balancer_registration_status_workspace_scope_slug",
        "registration_status",
        ["workspace_id", "scope", "slug"],
        schema="balancer",
    )
    op.drop_column("registration_status", "kind", schema="balancer")
