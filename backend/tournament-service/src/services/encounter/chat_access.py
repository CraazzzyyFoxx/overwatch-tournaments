"""Who somebody is inside a pre-game room's chat.

The encounter half of ``shared.services.chat.ChatAccess``: a domain question
only ("captain of a side, organizer of the owning workspace, or just
watching?"). Whether a spectator may actually READ, and whether this account is
muted, are room policy and belong to ``ChatService`` — see
docs/plans/2026-09-21-shared-room-chat.md.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import UserRepository
from shared.services.chat import SPECTATOR_ROLE, ChatMembership, ChatRoom, ChatService
from shared.services.tournament.visibility import assert_tournament_viewable
from src import models
from src.core import auth
from src.services import visibility_resolvers
from src.services.encounter.captain import captain_service

__all__ = ("EncounterChatAccess", "encounter_chat_service")

#: Spectators never author a message, so nothing snapshots their name and a
#: query to resolve one would be pure waste.
_SPECTATOR = ChatMembership(role=SPECTATOR_ROLE, display_name="", can_write=False, can_moderate=False)


class EncounterChatAccess:
    def __init__(self, *, user_repo: UserRepository = UserRepository()) -> None:
        self.user_repo = user_repo

    async def _display_name(self, session: AsyncSession, auth_user: models.AuthUser) -> str:
        player = await self.user_repo.get_by_auth_user_id(session, auth_user.id)
        # Staff need not be players, so the auth account's own name is the floor.
        return (player.name if player is not None else None) or auth_user.username

    async def resolve(
        self,
        session: AsyncSession,
        auth_user: models.AuthUser | None,
        room: ChatRoom,
    ) -> ChatMembership:
        # Format-agnostic: a lobby has a pre-game room too, and its chat is not
        # a series feature (plan 2026-09-24-ffa-encounters §5.6).
        encounter = await captain_service.load_encounter_any_format(session, room.ref_id)
        # Before anything else: an outsider must not learn that a hidden
        # tournament's encounter exists, chat setting or not.
        tournament_id = await visibility_resolvers.visibility_resolvers_service.tournament_id_for_encounter(
            session, encounter.id
        )
        await assert_tournament_viewable(session, auth_user, tournament_id)

        if auth_user is None:
            return _SPECTATOR

        try:
            side = await captain_service.resolve_captain_side(session, auth_user, encounter)
        except HTTPException:
            # ``resolve_captain_side`` says "not a captain" with a 403, same as
            # ``_captain_my_role`` reads it; here it is the fall-through to staff.
            side = None
        if side:
            return ChatMembership(
                role=side,
                display_name=await self._display_name(session, auth_user),
                can_write=True,
                can_moderate=False,
            )

        workspace_id = await auth.get_encounter_workspace_id(session, encounter.id)
        # Organizer staff, NOT the workspace roster. ``workspace_member`` rows --
        # and the baseline ``member`` role they autofill -- are created for every
        # registrant (``RegistrationService._anchor_registration_member``), and
        # the token's ``workspaces`` list is built from exactly those rows, so
        # ``is_workspace_member`` handed moderation (and a closed room's lobby
        # code) to every player who ever signed up in this workspace.
        # ``has_admin_panel_access`` is the scoped organizer predicate already
        # used as the admin gate: superuser, a global admin-panel role, or any
        # non-read grant in THIS workspace -- a read-only ``member``/``player``
        # and a mix ``host`` are excluded.
        if auth_user.has_admin_panel_access(workspace_id):
            return ChatMembership(
                role="staff",
                display_name=await self._display_name(session, auth_user),
                can_write=True,
                can_moderate=True,
            )

        return _SPECTATOR


encounter_chat_service = ChatService(EncounterChatAccess())
