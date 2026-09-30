"""Split ``match.result`` off ``match.update`` and ``registration.roles`` off ``registration.update``.

Revision ID: referee01
Revises: draftcap01
Create Date: 2026-09-30 00:00:00.000000

The ``referee`` workspace system role enters results and handles registrations
without touching the bracket or anyone's roles and ranks, which the old grants
could not express: ``match.update`` gated a score and a slot swap alike, and
``registration.update`` gated a display name and a rank alike.

The catalog rows are code-seeded by ``ensure_permission_catalog``, and the
``referee`` role itself is created lazily by ``ensure_workspace_system_roles``
like every system role. What code cannot do is keep existing grants whole: every
role, API key and deny that names the old permission is extended to the new one,
so nobody's effective authority moves on deploy -- a custom role that entered
results keeps entering them, a key scoped ``match.update`` keeps confirming, and
a user denied ``match.update`` stays unable to confirm.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "referee01"
down_revision: str | Sequence[str] | None = "draftcap01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# old permission -> the one split off it
_SPLITS = (("match.update", "match.result"), ("registration.update", "registration.roles"))
_NEW = tuple(new for _, new in _SPLITS)


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO auth.permissions (name, resource, action, description)
            VALUES
                ('match.result', 'match', 'result', 'Enter and correct encounter results'),
                ('registration.roles', 'registration', 'roles', 'Edit a registration''s roles and ranks')
            ON CONFLICT (name) DO NOTHING
            """
        )
    )
    for old, new in _SPLITS:
        params = {"old": old, "new": new}
        op.execute(
            sa.text(
                """
                INSERT INTO auth.role_permissions (role_id, permission_id)
                SELECT rp.role_id, new_p.id
                FROM auth.role_permissions rp
                JOIN auth.permissions old_p ON old_p.id = rp.permission_id AND old_p.name = :old
                CROSS JOIN auth.permissions new_p
                WHERE new_p.name = :new
                  AND NOT EXISTS (
                      SELECT 1 FROM auth.role_permissions x
                      WHERE x.role_id = rp.role_id AND x.permission_id = new_p.id
                  )
                """
            ).bindparams(**params)
        )
        op.execute(
            sa.text(
                """
                INSERT INTO auth.api_key_scope (api_key_id, scope)
                SELECT s.api_key_id, :new
                FROM auth.api_key_scope s
                WHERE s.scope = :old
                ON CONFLICT DO NOTHING
                """
            ).bindparams(**params)
        )
        op.execute(
            sa.text(
                """
                INSERT INTO auth.user_permission_deny (user_id, permission_id, workspace_id, created_by, reason)
                SELECT d.user_id, new_p.id, d.workspace_id, d.created_by, d.reason
                FROM auth.user_permission_deny d
                JOIN auth.permissions old_p ON old_p.id = d.permission_id AND old_p.name = :old
                CROSS JOIN auth.permissions new_p
                WHERE new_p.name = :new
                  AND NOT EXISTS (
                      SELECT 1 FROM auth.user_permission_deny x
                      WHERE x.user_id = d.user_id
                        AND x.permission_id = new_p.id
                        AND COALESCE(x.workspace_id, 0) = COALESCE(d.workspace_id, 0)
                  )
                """
            ).bindparams(**params)
        )


def downgrade() -> None:
    new = sa.bindparam("new", value=list(_NEW), expanding=True)
    # The system role the code seeds for this split; its members lose it, and
    # the old code never lists or re-creates it.
    op.execute(sa.text("DELETE FROM auth.roles WHERE name = 'referee' AND is_system AND workspace_id IS NOT NULL"))
    op.execute(sa.text("DELETE FROM auth.api_key_scope WHERE scope IN :new").bindparams(new))
    # role_permissions and user_permission_deny cascade from the permission rows.
    op.execute(sa.text("DELETE FROM auth.permissions WHERE name IN :new").bindparams(new))
