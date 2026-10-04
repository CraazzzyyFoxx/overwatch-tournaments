"""Who a tournament lifecycle notification is addressed to.

The two competitor reads answer the same question -- "which site accounts are
behind these domain rows" -- and both walk the same chain:
``workspace_member -> players.user -> auth_user_id``. That chain is why they are
joins rather than ``BaseRepository`` CRUD, and why they live together: a shadow
player (a real competitor with no site account behind their ``players.user``
row) has no inbox, so ``auth_user_id IS NULL`` drops them here instead of every
caller remembering to skip them.

``workspace_staff_auth_user_ids`` is the other side of the same page -- the
organizers rather than the players -- and starts from ``auth.user`` directly,
because staff hold RBAC roles, not rosters.

Ids only, never rows: the notifier needs recipients, and selecting the
registration/player rows would drag their whole identity graph into a write
transaction that is about to commit.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models

# Association tables, not mapped classes: the membership edges carry no
# behaviour, and ``models`` exports only the entities.
from shared.models.identity.rbac import role_permissions, user_roles

__all__ = ("NotificationRecipientRepository",)


class NotificationRecipientRepository:
    """Recipient lookups for the tournament lifecycle notifier."""

    async def check_in_pending_auth_user_ids(self, session: AsyncSession, tournament_id: int) -> list[int]:
        """Accounts that still owe this tournament a check-in.

        Approved, not withdrawn, not already checked in -- telling somebody to
        check in when they already have, or when their entry was never
        accepted, is the notification nobody reads the next one after.
        """
        query = (
            sa.select(models.User.auth_user_id)
            .select_from(models.BalancerRegistration)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.BalancerRegistration.workspace_member_id,
            )
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.status == "approved",
                models.BalancerRegistration.deleted_at.is_(None),
                models.BalancerRegistration.checked_in.is_(False),
                models.User.auth_user_id.is_not(None),
            )
            .distinct()
        )
        result = await session.scalars(query)
        return [int(value) for value in result.all()]

    async def team_roster_auth_user_ids(self, session: AsyncSession, team_ids: Sequence[int]) -> list[int]:
        """Accounts on any of these tournament team rosters.

        Takes a sequence so both sides of an encounter cost one query rather
        than one per team; substitutes are included, since a match time is news
        to whoever might play it.
        """
        if not team_ids:
            return []
        query = (
            sa.select(models.User.auth_user_id)
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .where(
                models.Player.team_id.in_(tuple(team_ids)),
                models.User.auth_user_id.is_not(None),
            )
            .distinct()
        )
        result = await session.scalars(query)
        return [int(value) for value in result.all()]

    async def workspace_staff_auth_user_ids(
        self,
        session: AsyncSession,
        workspace_id: int,
        resource: str,
        action: str,
    ) -> list[int]:
        """Accounts that may act on ``(resource, action)`` inside this workspace.

        A set-based mirror of the WORKSPACE branch of
        ``AuthUser.has_workspace_permission`` (``shared/models/identity/auth_user.py``):
        a role scoped to this workspace that is ``owner``/``admin``, or that
        carries a permission matching ``(resource|*, action|*)`` or the
        ``admin:*`` wildcard; minus an explicit ``UserPermissionDeny`` on that
        exact pair, global or for this workspace. Asking the Python predicate
        instead would mean hydrating every account with its whole role graph.

        Global admins and superusers are deliberately absent: they pass that
        predicate for EVERY workspace, so including them here would page the
        platform operators about every tournament on the site. The organizers of
        the workspace that owns the rows are the ones who can act on them.
        """
        query = (
            _staff_grants(resource, action, user_roles.c.user_id)
            .where(models.Role.workspace_id == workspace_id)
            .distinct()
        )
        result = await session.scalars(query)
        return [int(value) for value in result.all()]

    async def staff_workspaces(
        self,
        session: AsyncSession,
        auth_user_id: int,
        resource: str,
        action: str,
    ) -> list[tuple[int, str]]:
        """``(workspace_id, name)`` for every workspace where this account is staff.

        The other direction of ``workspace_staff_auth_user_ids``, over the same
        predicate, so the settings page offers a switch exactly where that read
        would page this account. Sorted by name for a stable list.
        """
        query = (
            _staff_grants(resource, action, models.Workspace.id, models.Workspace.name)
            .join(models.Workspace, models.Workspace.id == models.Role.workspace_id)
            .where(user_roles.c.user_id == auth_user_id)
            .distinct()
            .order_by(models.Workspace.name, models.Workspace.id)
        )
        result = await session.execute(query)
        return [(int(workspace_id), name) for workspace_id, name in result.all()]


def _staff_grants(resource: str, action: str, *columns: Any) -> sa.Select:
    """``columns`` over the ``user_roles ⋈ role`` rows granting ``(resource, action)``
    in the role's own workspace.

    Shared by both directions of the staff lookup; the caller pins either the
    workspace or the account. ``select_from`` is explicit because the selected
    columns need not come from the leftmost table.
    """
    permission_grants = sa.or_(
        sa.and_(
            models.Permission.resource.in_((resource, "*")),
            models.Permission.action.in_((action, "*")),
        ),
        # ``is_workspace_admin``'s wildcard: ``admin:*`` is admin-equivalent
        # without naming a resource.
        sa.and_(models.Permission.resource == "admin", models.Permission.action == "*"),
    )
    denied = (
        sa.select(models.UserPermissionDeny.user_id)
        .join(models.Permission, models.Permission.id == models.UserPermissionDeny.permission_id)
        .where(
            models.UserPermissionDeny.user_id == user_roles.c.user_id,
            # No wildcard expansion on the deny side -- a deny row removes
            # exactly the pair it names, which is what the model documents.
            models.Permission.resource == resource,
            models.Permission.action == action,
            sa.or_(
                models.UserPermissionDeny.workspace_id.is_(None),
                models.UserPermissionDeny.workspace_id == models.Role.workspace_id,
            ),
        )
        .correlate(user_roles, models.Role)
    )
    return (
        sa.select(*columns)
        .select_from(user_roles)
        .join(models.Role, models.Role.id == user_roles.c.role_id)
        # Outer: an ``owner``/``admin`` role grants without carrying a single
        # permission row, and an inner join would drop exactly those people.
        .outerjoin(role_permissions, role_permissions.c.role_id == models.Role.id)
        .outerjoin(models.Permission, models.Permission.id == role_permissions.c.permission_id)
        .where(
            models.Role.workspace_id.is_not(None),
            sa.or_(models.Role.name.in_(("owner", "admin")), permission_grants),
            ~sa.exists(denied),
        )
    )
