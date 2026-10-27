"""Who somebody is inside a pre-game room's chat.

The encounter half of ``shared.services.chat.ChatAccess``: a domain question
only ("captain of a side, organizer of the owning workspace, or just
watching?"). Whether a spectator may actually READ, and whether this account is
muted, are room policy and belong to ``ChatService``. A mix match's chat is its
own rule (``_mix_member``): its players and hosts, nobody else.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.services.chat import SPECTATOR_ROLE, ChatMembership, ChatRoom, ChatService
from shared.services.mix_hosts import is_mix_host
from shared.services.tournament.display_name import tournament_display_name
from shared.services.tournament.visibility import ensure_tournament_viewable
from src.core import auth
from src.services.encounter.captain import captain_service
from src.services.encounter.ffa import ffa_encounter_service
from src.services.encounter.room_owner import load_room_encounter

__all__ = ("EncounterChatAccess", "encounter_chat_service")

#: Spectators never author a message, so nothing snapshots their name and a
#: query to resolve one would be pure waste.
_SPECTATOR = ChatMembership(role=SPECTATOR_ROLE, display_name="", can_write=False, can_moderate=False)


class EncounterChatAccess:
    async def resolve(
        self,
        session: AsyncSession,
        auth_user: models.AuthUser | None,
        room: ChatRoom,
        *,
        for_update: bool,
    ) -> ChatMembership:
        # Format-agnostic: a lobby has a pre-game room too, and its chat is not a series feature. Locked for a write
        # (one account's posts queue, so the rate limit's count-then-insert holds); a plain read for the history every
        # spectator polls, which must not queue behind the captains.
        encounter = await load_room_encounter(session, room.ref_id, for_update=for_update)
        if encounter.custom_game_id is not None:
            return await self._mix_member(session, auth_user, encounter)
        # Before anything else: an outsider must not learn that a hidden
        # tournament's encounter exists, chat setting or not.
        tournament_id = encounter.tournament_id
        await ensure_tournament_viewable(session, auth_user, tournament_id)

        if auth_user is None:
            return _SPECTATOR

        # An encounter has no sides, so "which side are you?" has no answer:
        # the seated participations are the whole roster, and captaining one of
        # them is one membership whether the encounter seats two or twenty.
        side = "captain" if await ffa_encounter_service.is_participant_captain(session, auth_user, encounter) else None
        if side:
            return ChatMembership(
                role=side,
                display_name=await tournament_display_name(session, auth_user=auth_user, tournament_id=tournament_id),
                can_write=True,
                can_moderate=False,
            )

        workspace_id = await auth.get_encounter_workspace_id(session, encounter.id)
        # Organizer staff, NOT the workspace roster: every registrant gets a
        # ``workspace_member`` row (``RegistrationService._anchor_registration_member``)
        # and the token's ``workspaces`` list is built from those rows, so
        # membership would hand moderation (and a closed room's lobby code) to
        # every player. ``has_admin_panel_access`` is the scoped organizer gate:
        # superuser, a global admin-panel role, or a non-read grant in THIS
        # workspace -- a read-only ``member``/``player`` and a mix ``host`` are out.
        if auth_user.has_admin_panel_access(workspace_id):
            return ChatMembership(
                role="staff",
                display_name=await tournament_display_name(session, auth_user=auth_user, tournament_id=tournament_id),
                can_write=True,
                can_moderate=True,
            )

        return _SPECTATOR

    async def _mix_member(
        self, session: AsyncSession, auth_user: models.AuthUser | None, encounter: models.Encounter
    ) -> ChatMembership:
        """A mix match's chat (spec §4.4): the hosts moderate, the seated players of both teams write, and nobody
        else reads it -- signed in or not -- because the in-game lobby code is shared here."""
        if auth_user is not None:
            if await is_mix_host(session, auth_user, encounter.custom_game_id):
                return ChatMembership(role="staff", display_name=auth_user.username, can_write=True, can_moderate=True)
            try:
                seat, player_id, is_captain, _member = await captain_service.resolve_participant(
                    session, auth_user, encounter
                )
            except HTTPException:
                seat = None
            if seat is not None:
                name = await session.scalar(
                    select(models.EncounterTeamMember.display_name_snapshot)
                    .join(
                        models.WorkspaceMember,
                        models.WorkspaceMember.id == models.EncounterTeamMember.workspace_member_id,
                    )
                    .where(
                        models.EncounterTeamMember.encounter_team_id == seat.id,
                        models.WorkspaceMember.player_id == player_id,
                    )
                )
                return ChatMembership(
                    role="captain" if is_captain else "player",
                    display_name=name or auth_user.username,
                    can_write=True,
                    can_moderate=False,
                )
        raise HTTPException(status_code=403, detail="This match's chat is for its players and hosts")


encounter_chat_service = ChatService(EncounterChatAccess())
