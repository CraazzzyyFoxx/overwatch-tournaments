"""Fold the workspace ``member`` system role into ``player``.

Revision ID: plrole01
Revises: discordmsg02
Create Date: 2026-10-06 00:00:00.000000

``player`` used to be a permission-less marker granted next to ``member`` on
self-registration; the two now are one baseline role named ``player`` that
carries what ``member`` read.

Per workspace: every ``player`` holder is granted ``member``, the old
``player`` role is deleted (its grants go by cascade), and ``member`` is
renamed to ``player``. A workspace that only had ``player`` keeps that row.
Every ``player`` role then gets exactly the catalog's permission set;
``ensure_workspace_system_roles`` re-syncs it on the next workspace write, so
importing the catalog rather than freezing a copy cannot drift.

Irreversible: after the merge nothing tells a former ``member`` grant from a
former ``player`` one, so ``downgrade`` is a no-op.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from shared.rbac.catalog import permission_names_for_workspace_role

revision: str = "plrole01"
down_revision: str | Sequence[str] | None = "discordmsg02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO auth.user_roles (user_id, role_id)
            SELECT DISTINCT ur.user_id, m.id
            FROM auth.user_roles ur
            JOIN auth.roles p ON p.id = ur.role_id AND p.name = 'player' AND p.workspace_id IS NOT NULL
            JOIN auth.roles m ON m.workspace_id = p.workspace_id AND m.name = 'member'
            WHERE NOT EXISTS (
                SELECT 1 FROM auth.user_roles x WHERE x.user_id = ur.user_id AND x.role_id = m.id
            )
            """
        )
    )
    # Grants and permission rows go with it (ON DELETE CASCADE).
    op.execute(
        sa.text(
            """
            DELETE FROM auth.roles p
            USING auth.roles m
            WHERE p.name = 'player' AND m.name = 'member' AND m.workspace_id = p.workspace_id
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE auth.roles
            SET name = 'player',
                is_system = true,
                description = CASE
                    WHEN description = 'Workspace member system role' THEN 'Workspace player system role'
                    ELSE description
                END
            WHERE name = 'member' AND workspace_id IS NOT NULL
            """
        )
    )

    names = sa.bindparam("names", value=list(permission_names_for_workspace_role("player")), expanding=True)
    op.execute(
        sa.text(
            """
            DELETE FROM auth.role_permissions rp
            USING auth.roles r, auth.permissions p
            WHERE rp.role_id = r.id AND rp.permission_id = p.id
              AND r.name = 'player' AND r.workspace_id IS NOT NULL
              AND p.name NOT IN :names
            """
        ).bindparams(names)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO auth.role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM auth.roles r
            JOIN auth.permissions p ON p.name IN :names
            WHERE r.name = 'player' AND r.workspace_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM auth.role_permissions x WHERE x.role_id = r.id AND x.permission_id = p.id
              )
            """
        ).bindparams(names)
    )


def downgrade() -> None:
    """No-op: see the module docstring."""
