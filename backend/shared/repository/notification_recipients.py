"""Who a tournament lifecycle notification is addressed to.

Both reads answer the same question -- "which site accounts are behind these
domain rows" -- and both walk the same chain:
``workspace_member -> players.user -> auth_user_id``. That chain is why they are
joins rather than ``BaseRepository`` CRUD, and why they live together: a shadow
player (a real competitor with no site account behind their ``players.user``
row) has no inbox, so ``auth_user_id IS NULL`` drops them here instead of every
caller remembering to skip them.

Ids only, never rows: the notifier needs recipients, and selecting the
registration/player rows would drag their whole identity graph into a write
transaction that is about to commit.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models

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
