"""Retire the global ``tournament_organizer`` role in favour of workspace ``referee``.

Revision ID: noorg01
Revises: referee01
Create Date: 2026-09-30 00:00:00.000000

``tournament_organizer`` was never seeded by code: its name alone opened the
admin panel (``ADMIN_PANEL_ROLE_NAMES``) and the balancer, and whatever it could
do beyond that was hand-assigned -- globally, so in every workspace at once.
``referee`` replaces it with a fixed, workspace-scoped grant.

Every holder becomes ``referee`` in each workspace they already belong to --
by any role there, or by a ``workspace_member`` row for their player -- and the
global role is deleted, which drops its grants and permission rows by cascade.
A holder who belongs to no workspace keeps nothing: there is no workspace to be
a referee IN, and handing out membership is not this revision's call.

The ``referee`` role is created here for a workspace that has none yet, with the
catalog's permission set; ``ensure_workspace_system_roles`` re-syncs it on the
next workspace write exactly as for every other system role, so importing the
catalog rather than freezing a copy cannot drift.

Irreversible by design: the old role's hand-assigned permissions and holders
are gone with it, and a downgrade that re-created an empty role would restore
a name, not an authority. ``downgrade`` is therefore a no-op.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from shared.rbac.catalog import permission_names_for_workspace_role

revision: str = "noorg01"
down_revision: str | Sequence[str] | None = "referee01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: (holder, workspace) pairs to seat as referee: every workspace the holder
#: already belongs to, through a workspace role or a player membership row.
_SEATS = """
    organizer AS (
        SELECT ur.user_id
        FROM auth.user_roles ur
        JOIN auth.roles g ON g.id = ur.role_id
        WHERE g.name = 'tournament_organizer' AND g.workspace_id IS NULL
    ),
    seat AS (
        SELECT o.user_id, r.workspace_id
        FROM organizer o
        JOIN auth.user_roles ur ON ur.user_id = o.user_id
        JOIN auth.roles r ON r.id = ur.role_id AND r.workspace_id IS NOT NULL
        UNION
        SELECT o.user_id, wm.workspace_id
        FROM organizer o
        JOIN players."user" pu ON pu.auth_user_id = o.user_id
        JOIN workspace_member wm ON wm.player_id = pu.id
    )
"""


def upgrade() -> None:
    names = sa.bindparam("names", value=list(permission_names_for_workspace_role("referee")), expanding=True)

    op.execute(
        sa.text(
            f"""
            WITH {_SEATS}
            INSERT INTO auth.roles (name, description, is_system, workspace_id)
            SELECT DISTINCT 'referee', 'Workspace referee system role', true, s.workspace_id
            FROM seat s
            WHERE NOT EXISTS (
                SELECT 1 FROM auth.roles r WHERE r.name = 'referee' AND r.workspace_id = s.workspace_id
            )
            """
        )
    )
    # A same-named custom role is taken over, as ensure_workspace_system_roles
    # would on its next run: marked system and given exactly the catalog set.
    op.execute(
        sa.text(
            f"""
            WITH {_SEATS}
            UPDATE auth.roles SET is_system = true
            WHERE name = 'referee' AND workspace_id IN (SELECT workspace_id FROM seat)
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            WITH {_SEATS}
            DELETE FROM auth.role_permissions rp
            USING auth.roles r, auth.permissions p
            WHERE rp.role_id = r.id AND rp.permission_id = p.id
              AND r.name = 'referee' AND r.workspace_id IN (SELECT workspace_id FROM seat)
              AND p.name NOT IN :names
            """
        ).bindparams(names)
    )
    op.execute(
        sa.text(
            f"""
            WITH {_SEATS}
            INSERT INTO auth.role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM auth.roles r
            JOIN auth.permissions p ON p.name IN :names
            WHERE r.name = 'referee' AND r.workspace_id IN (SELECT workspace_id FROM seat)
              AND NOT EXISTS (
                  SELECT 1 FROM auth.role_permissions x WHERE x.role_id = r.id AND x.permission_id = p.id
              )
            """
        ).bindparams(names)
    )
    op.execute(
        sa.text(
            f"""
            WITH {_SEATS}
            INSERT INTO auth.user_roles (user_id, role_id)
            SELECT DISTINCT s.user_id, r.id
            FROM seat s
            JOIN auth.roles r ON r.name = 'referee' AND r.workspace_id = s.workspace_id
            WHERE NOT EXISTS (
                SELECT 1 FROM auth.user_roles x WHERE x.user_id = s.user_id AND x.role_id = r.id
            )
            """
        )
    )
    # Grants and permission rows go with it (ON DELETE CASCADE).
    op.execute(sa.text("DELETE FROM auth.roles WHERE name = 'tournament_organizer' AND workspace_id IS NULL"))


def downgrade() -> None:
    """No-op: see the module docstring."""
