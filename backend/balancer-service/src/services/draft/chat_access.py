"""Who somebody is inside a draft room's chat.

The draft half of ``shared.services.chat.ChatAccess``: a domain question only
("captain of a team in THIS session, organizer of the owning tournament's workspace or host of the owning mix, or
just watching?"). Whether a spectator may actually READ, and whether this account is
muted, are room policy and belong to ``ChatService``.

The room is the SESSION, not the tournament: a re-seed is a different draft
with a different conversation, so ``room.ref_id`` is a
``draft.session.id``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.repository.draft import DraftSessionRepository, DraftTeamRepository
from shared.services.chat import SPECTATOR_ROLE, ChatMembership, ChatRoom, ChatService
from shared.services.mix_hosts import is_mix_host
from shared.services.tournament.display_name import tournament_display_name
from shared.services.tournament.visibility import ensure_tournament_viewable

__all__ = ("DraftChatAccess", "draft_chat_service")

#: Spectators never author a message, so nothing snapshots their name and a
#: query to resolve one would be pure waste.
_SPECTATOR = ChatMembership(role=SPECTATOR_ROLE, display_name="", can_write=False, can_moderate=False)


class DraftChatAccess:
    def __init__(
        self,
        *,
        sessions_repo: DraftSessionRepository = DraftSessionRepository(),
        teams_repo: DraftTeamRepository = DraftTeamRepository(),
    ) -> None:
        self.sessions_repo = sessions_repo
        self.teams_repo = teams_repo

    async def resolve(
        self,
        session: AsyncSession,
        auth_user: AuthUser | None,
        room: ChatRoom,
        *,
        for_update: bool = False,
    ) -> ChatMembership:
        # ``for_update`` (``ChatAccess``) is unused: a draft chat never locked its session row.
        draft = await self.sessions_repo.get(session, room.ref_id)
        if draft is None:
            # 404, the same answer a hidden tournament gets just below: a 403 here
            # would tell "no such draft" apart from "a draft you may not see".
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Draft session not found")
        if draft.custom_game_id is not None:
            return await self._mix_member(session, auth_user, draft)
        # Before anything else: an outsider must not learn that a hidden
        # tournament is drafting, chat setting or not.
        await ensure_tournament_viewable(session, auth_user, draft.tournament_id)

        if auth_user is None:
            return _SPECTATOR

        # ``captain_auth_user_id`` is the captain-gating signal (rules.py reads
        # it the same way) and is independent of whether the seat was ever
        # linked to a public player. A session has a handful of teams, so the
        # match is a scan of the list the board already loads.
        teams = await self.teams_repo.list_by_session(session, draft.id)
        if any(team.captain_auth_user_id == auth_user.id for team in teams):
            return ChatMembership(
                role="captain",
                display_name=await tournament_display_name(
                    session, auth_user=auth_user, tournament_id=draft.tournament_id
                ),
                can_write=True,
                can_moderate=False,
            )

        # Organizer staff, NOT the workspace roster: ``workspace_member`` rows
        # (and the baseline ``member`` role they autofill) exist for every
        # registrant, and the token's ``workspaces`` list is built from them, so
        # ``is_workspace_member`` would hand moderation to every player of the
        # workspace. ``has_admin_panel_access`` is the scoped organizer
        # predicate: superuser, a global admin-panel role, or any non-read grant
        # in THIS workspace.
        if auth_user.has_admin_panel_access(draft.workspace_id):
            return ChatMembership(
                role="staff",
                display_name=await tournament_display_name(
                    session, auth_user=auth_user, tournament_id=draft.tournament_id
                ),
                can_write=True,
                can_moderate=True,
            )

        return _SPECTATOR

    async def _mix_member(self, session: AsyncSession, auth_user: AuthUser | None, draft: Any) -> ChatMembership:
        """A mix draft room (spec §4.4): public to watch, its hosts moderate, its captains write -- under their account
        name, a mix having no registration to name them by."""
        if auth_user is None:
            return _SPECTATOR
        if await is_mix_host(session, auth_user, draft.custom_game_id):
            return ChatMembership(role="staff", display_name=auth_user.username, can_write=True, can_moderate=True)
        teams = await self.teams_repo.list_by_session(session, draft.id)
        if any(team.captain_auth_user_id == auth_user.id for team in teams):
            return ChatMembership(role="captain", display_name=auth_user.username, can_write=True, can_moderate=False)
        return _SPECTATOR


draft_chat_service = ChatService(DraftChatAccess())
