"""Who somebody is inside a draft room's chat.

The draft half of ``shared.services.chat.ChatAccess``: a domain question only
("captain of a team in THIS session, organizer of the owning workspace, or just
watching?"). Whether a spectator may actually READ, and whether this account is
muted, are room policy and belong to ``ChatService`` — see
docs/plans/2026-09-21-shared-room-chat.md.

The room is the SESSION, not the tournament (ruling R3): a re-seed is a
different draft with a different conversation, so ``room.ref_id`` is a
``balancer.draft_session.id``.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.identity.auth_user import AuthUser
from shared.repository.draft import DraftSessionRepository, DraftTeamRepository
from shared.repository.identity import UserRepository
from shared.services.chat import SPECTATOR_ROLE, ChatMembership, ChatRoom, ChatService
from shared.services.tournament.visibility import assert_tournament_viewable

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
        user_repo: UserRepository = UserRepository(),
    ) -> None:
        self.sessions_repo = sessions_repo
        self.teams_repo = teams_repo
        self.user_repo = user_repo

    async def _display_name(self, session: AsyncSession, auth_user: AuthUser) -> str:
        player = await self.user_repo.get_by_auth_user_id(session, auth_user.id)
        # Staff (and a captain seated before they linked a player) need not be
        # players, so the auth account's own name is the floor.
        return (player.name if player is not None else None) or auth_user.username

    async def resolve(
        self,
        session: AsyncSession,
        auth_user: AuthUser | None,
        room: ChatRoom,
    ) -> ChatMembership:
        draft = await self.sessions_repo.get(session, room.ref_id)
        if draft is None:
            # 403, not 404: the caller may not see this room, and which of the
            # two reasons applies is not theirs to learn.
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Draft chat is not available")
        # Before anything else: an outsider must not learn that a hidden
        # tournament is drafting, chat setting or not.
        await assert_tournament_viewable(session, auth_user, draft.tournament_id)

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
                display_name=await self._display_name(session, auth_user),
                can_write=True,
                can_moderate=False,
            )

        # Membership already answers superuser (AuthUser.is_workspace_member
        # short-circuits on it); chat needs no capability of its own.
        if auth_user.is_workspace_member(draft.workspace_id):
            return ChatMembership(
                role="staff",
                display_name=await self._display_name(session, auth_user),
                can_write=True,
                can_moderate=True,
            )

        return _SPECTATOR


draft_chat_service = ChatService(DraftChatAccess())
