"""backfill baseline ``member`` role for role-less auth-linked workspace members

Identity/workspace refactor made ``workspace_member`` do double duty: it anchors
both real RBAC members and tournament participants (see
``lesson_workspace_member_dual_population``). The members screen now treats every
auth-linked member row as an RBAC member, so a row whose auth user holds *no*
workspace role is a "role-less member". This one-time backfill grants such
members the workspace ``member`` system role (going-forward coverage lives in the
identity link-flow and ``get_or_create_workspace_member`` anchor trigger).

SAFETY / SHAPE:
  * Data-only — no DDL, no exclusive locks (INSERT + shared read of source rows).
  * Idempotent / re-runnable — the ``NOT EXISTS`` guard only touches members whose
    auth user has ZERO roles in the workspace, so re-running inserts nothing and
    an already-assigned role is never duplicated. It is also additive: a member
    who already has ``player`` / ``admin`` / a custom role is skipped, never
    downgraded.
  * Tolerant — joins to the workspace's ``member`` system role, so a workspace
    that has not had its system roles seeded yet is simply skipped (the runtime
    autofill + the members-page button pick those up later).

DOWNGRADE is a no-op: the inserted ``member`` grants are indistinguishable from
pre-existing ones, so they are intentionally not removed (data backfill).
"""

from alembic import op

revision: str = "wsmbr01"
down_revision: str | None = "dbarch06"
branch_labels = None
depends_on = None


_BACKFILL_SQL = """
INSERT INTO auth.user_roles (user_id, role_id)
SELECT DISTINCT pu.auth_user_id, r.id
FROM workspace_member wm
JOIN players."user" pu ON pu.id = wm.player_id AND pu.auth_user_id IS NOT NULL
JOIN auth.roles r ON r.workspace_id = wm.workspace_id AND r.name = 'member'
WHERE NOT EXISTS (
    SELECT 1
    FROM auth.user_roles ur
    JOIN auth.roles r2 ON r2.id = ur.role_id
    WHERE ur.user_id = pu.auth_user_id
      AND r2.workspace_id = wm.workspace_id
)
"""


def upgrade() -> None:
    op.execute(_BACKFILL_SQL)


def downgrade() -> None:
    # No-op: autofilled ``member`` grants are indistinguishable from grants made
    # through the UI, so they are not reversible without data loss risk.
    pass
