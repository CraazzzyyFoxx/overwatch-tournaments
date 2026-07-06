"""Negative RBAC: per-user permission deny table + self-service capability perms.

Adds ``auth.user_permission_deny`` (an explicit per-user deny of a single
permission that overrides any grant, incl. superuser, for that exact action)
and seeds the allow-by-default self-service capabilities ``account.avatar`` /
``account.social`` so they can be denied.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "acctdeny0001"
down_revision: str | Sequence[str] | None = "social0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACCOUNT_PERMISSIONS = (
    ("account.avatar", "account", "avatar", "Change one's own avatar"),
    ("account.social", "account", "social", "Manage one's own social accounts"),
)


def upgrade() -> None:
    op.create_table(
        "user_permission_deny",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("permission_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["auth.user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["auth.permissions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "permission_id", name="uq_user_permission_deny"),
        schema="auth",
    )
    op.create_index("ix_user_permission_deny_user_id", "user_permission_deny", ["user_id"], schema="auth")

    for name, resource, action, description in _ACCOUNT_PERMISSIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO auth.permissions (name, resource, action, description, created_at)
                VALUES (CAST(:name AS varchar), CAST(:resource AS varchar),
                        CAST(:action AS varchar), CAST(:description AS varchar), now())
                ON CONFLICT (name) DO UPDATE
                SET resource = EXCLUDED.resource, action = EXCLUDED.action, description = EXCLUDED.description
                """
            ).bindparams(name=name, resource=resource, action=action, description=description)
        )


def downgrade() -> None:
    op.drop_index("ix_user_permission_deny_user_id", table_name="user_permission_deny", schema="auth")
    op.drop_table("user_permission_deny", schema="auth")
    op.execute(sa.text("DELETE FROM auth.permissions WHERE name IN ('account.avatar', 'account.social')"))
