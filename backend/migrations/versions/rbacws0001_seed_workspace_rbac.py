"""seed workspace RBAC catalog and starter roles

Revision ID: rbacws0001
Revises: apikey0001, c8d2e4f6g8h0
Create Date: 2026-05-01 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from shared.rbac import PERMISSION_CATALOG, WORKSPACE_SYSTEM_ROLE_NAMES, permission_names_for_workspace_role

revision: str = "rbacws0001"
down_revision: str | Sequence[str] | None = ("apikey0001", "c8d2e4f6g8h0")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _seed_permissions(connection) -> None:
    for permission in PERMISSION_CATALOG:
        connection.execute(
            sa.text(
                """
                INSERT INTO auth.permissions (name, resource, action, description, created_at)
                VALUES (
                    CAST(:name AS varchar),
                    CAST(:resource AS varchar),
                    CAST(:action AS varchar),
                    CAST(:description AS varchar),
                    now()
                )
                ON CONFLICT (name) DO UPDATE
                SET resource = EXCLUDED.resource,
                    action = EXCLUDED.action,
                    description = EXCLUDED.description
                """
            ),
            {
                "name": permission.name,
                "resource": permission.resource,
                "action": permission.action,
                "description": permission.description,
            },
        )


def _ensure_workspace_role(connection, workspace_id: int, role_name: str) -> int:
    connection.execute(
        sa.text(
            """
            INSERT INTO auth.roles (name, description, is_system, workspace_id, created_at)
            SELECT CAST(:name AS varchar),
                   CAST(:description AS varchar),
                   true,
                   CAST(:workspace_id AS integer),
                   now()
            WHERE NOT EXISTS (
                SELECT 1
                FROM auth.roles
                WHERE name = CAST(:name AS varchar)
                  AND workspace_id = CAST(:workspace_id AS integer)
            )
            """
        ),
        {
            "name": role_name,
            "description": f"Workspace {role_name} system role",
            "workspace_id": workspace_id,
        },
    )
    connection.execute(
        sa.text(
            """
            UPDATE auth.roles
            SET is_system = true,
                description = COALESCE(description, CAST(:description AS varchar))
            WHERE name = CAST(:name AS varchar)
              AND workspace_id = CAST(:workspace_id AS integer)
            """
        ),
        {
            "name": role_name,
            "description": f"Workspace {role_name} system role",
            "workspace_id": workspace_id,
        },
    )
    role_id = connection.scalar(
        sa.text(
            """
            SELECT id
            FROM auth.roles
            WHERE name = CAST(:name AS varchar)
              AND workspace_id = CAST(:workspace_id AS integer)
            """
        ),
        {"name": role_name, "workspace_id": workspace_id},
    )
    return int(role_id)


def _replace_role_permissions(connection, role_id: int, permission_names: tuple[str, ...]) -> None:
    connection.execute(
        sa.text("DELETE FROM auth.role_permissions WHERE role_id = :role_id"),
        {"role_id": role_id},
    )
    if not permission_names:
        return
    connection.execute(
        sa.text(
            """
            INSERT INTO auth.role_permissions (role_id, permission_id, created_at)
            SELECT CAST(:role_id AS integer), id, now()
            FROM auth.permissions
            WHERE name = ANY(CAST(:permission_names AS varchar[]))
            """
        ),
        {"role_id": role_id, "permission_names": list(permission_names)},
    )


def _seed_workspace_roles(connection) -> None:
    workspace_ids = connection.execute(sa.text("SELECT id FROM public.workspace ORDER BY id")).scalars().all()
    for workspace_id in workspace_ids:
        for role_name in WORKSPACE_SYSTEM_ROLE_NAMES:
            role_id = _ensure_workspace_role(connection, int(workspace_id), role_name)
            _replace_role_permissions(connection, role_id, permission_names_for_workspace_role(role_name))


def _backfill_member_assignments(connection) -> None:
    connection.execute(
        sa.text(
            """
            INSERT INTO auth.user_roles (user_id, role_id, created_at)
            SELECT wm.auth_user_id, r.id, now()
            FROM public.workspace_member wm
            JOIN auth.roles r
              ON r.workspace_id = wm.workspace_id
             AND r.name = CASE
                    WHEN wm.role IN ('owner', 'admin', 'member') THEN wm.role
                    ELSE 'member'
                 END
            WHERE NOT EXISTS (
                SELECT 1
                FROM auth.user_roles ur
                WHERE ur.user_id = wm.auth_user_id AND ur.role_id = r.id
            )
            """
        )
    )


def upgrade() -> None:
    connection = op.get_bind()
    _seed_permissions(connection)
    _seed_workspace_roles(connection)
    _backfill_member_assignments(connection)


def downgrade() -> None:
    # Data seed/backfill migration: keep RBAC data on downgrade to avoid
    # unexpectedly removing access from existing users.
    pass
