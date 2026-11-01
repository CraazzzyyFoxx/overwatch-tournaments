"""How a tournament surface names a person: ``PersonDisplayRead`` for roster rows and registrations.

The surface's scope is its tournament: the game is ``tournament.discipline``, the visibility workspace is
``tournament.workspace_id``. The snapshot is the event's own record (roster ``player.name``, registration handle).
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.disciplines import identity_provider
from shared.schemas.identity import PersonDisplayRead
from shared.services.person_display import game_handle, pick_game_handle

__all__ = ("player_displays", "registration_display", "registration_person_loader")


def _provider(discipline: str) -> str | None:
    try:
        return identity_provider(discipline)
    except LookupError:  # a game with no identity provider has no game handle to show
        return None


async def player_displays(session: AsyncSession, players: Iterable[models.Player]) -> dict[int, PersonDisplayRead]:
    """``{player.id: display}`` for roster rows: one statement for their tournaments' scopes, one per tournament."""
    by_tournament: dict[int, list[models.Player]] = {}
    for player in players:
        by_tournament.setdefault(player.tournament_id, []).append(player)
    if not by_tournament:
        return {}
    scopes = (
        await session.execute(
            sa.select(models.Tournament.id, models.Tournament.discipline, models.Tournament.workspace_id).where(
                models.Tournament.id.in_(by_tournament)
            )
        )
    ).all()
    displays: dict[int, PersonDisplayRead] = {}
    for tournament_id, discipline, workspace_id in scopes:
        group = by_tournament[tournament_id]
        provider = _provider(discipline)
        handle = (
            game_handle(models.WorkspaceMember.player_id, provider, workspace_id) if provider is not None else sa.null()
        )
        rows = await session.execute(
            sa.select(models.Player.id, models.User.name, models.WorkspaceMember.display_name, handle)
            .select_from(models.Player)
            .join(models.WorkspaceMember, models.WorkspaceMember.id == models.Player.workspace_member_id)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .where(models.Player.id.in_([player.id for player in group]))
        )
        snapshots = {player.id: player.name for player in group}
        for player_id, canonical, workspace_name, shown in rows:
            displays[player_id] = PersonDisplayRead.build(
                canonical=canonical,
                provider=provider,
                handle=shown,
                workspace_name=workspace_name,
                snapshot=snapshots[player_id],
            )
    return displays


def registration_person_loader() -> Any:
    """The chain ``registration_display`` reads, to eager-load on registration rows."""
    return (
        selectinload(models.Registration.workspace_member)
        .selectinload(models.WorkspaceMember.player)
        .selectinload(models.User.social_accounts)
        .selectinload(models.SocialAccount.visibilities)
    )


def registration_display(
    registration: models.Registration, *, provider: str, workspace_id: int, handle: str | None
) -> PersonDisplayRead:
    """The registration's person, named for its tournament. ``handle`` is the registration's own primary game
    handle (the snapshot); a row with no member (manual) is unlinked. Rows must carry ``registration_person_loader``."""
    member = registration.workspace_member
    user = member.player if member is not None else None
    return PersonDisplayRead.build(
        canonical=user.name if user is not None else None,
        provider=provider,
        handle=pick_game_handle(user.social_accounts, provider, workspace_id) if user is not None else None,
        workspace_name=member.display_name if member is not None else None,
        snapshot=handle or registration.display_name,
    )
