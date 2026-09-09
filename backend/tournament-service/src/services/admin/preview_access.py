"""Admin service for the per-tournament preview allowlist (issue #115).

Idempotent add, hard delete, ordered list. Callers gate on
``is_workspace_admin`` before invoking these.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.tournament.preview_access import TournamentPreviewAccess
from shared.repository import TournamentPreviewAccessRepository
from shared.services.realtime import Resource, Scope, emit


class PreviewAccessService:
    def __init__(
        self,
        *,
        preview_access_repo: TournamentPreviewAccessRepository = TournamentPreviewAccessRepository(),
    ) -> None:
        self.preview_access_repo = preview_access_repo

    async def list_preview_access(self, session: AsyncSession, tournament_id: int) -> list[TournamentPreviewAccess]:
        return list(await self.preview_access_repo.list_for_tournament(session, tournament_id))

    async def _invalidate(self, session: AsyncSession, tournament_id: int) -> None:
        """``tournament.detail`` only: the allowlist changes who may preview the
        tournament and the badge its read model carries, and nothing else — no
        section appears or disappears, and no other service caches it, so this
        needs neither the route-refresh resource nor an outbox row."""
        await emit(
            session,
            scope=Scope.tournament(tournament_id),
            invalidates=[Resource.TOURNAMENT_DETAIL],
        )

    async def add_preview_access(
        self, session: AsyncSession, tournament_id: int, auth_user_id: int
    ) -> TournamentPreviewAccess:
        existing = await self.preview_access_repo.get_grant(
            session, tournament_id=tournament_id, auth_user_id=auth_user_id
        )
        if existing is not None:
            # Idempotent re-grant: nothing moved, so nothing is stale.
            return existing
        row = await self.preview_access_repo.create(
            session, TournamentPreviewAccess(tournament_id=tournament_id, auth_user_id=auth_user_id)
        )
        await self._invalidate(session, tournament_id)
        await session.commit()
        await session.refresh(row)
        return row

    async def remove_preview_access(self, session: AsyncSession, tournament_id: int, auth_user_id: int) -> None:
        await self.preview_access_repo.revoke(session, tournament_id=tournament_id, auth_user_id=auth_user_id)
        await self._invalidate(session, tournament_id)
        await session.commit()


def serialize_entry(row: TournamentPreviewAccess) -> dict:
    return {
        "id": row.id,
        "tournament_id": row.tournament_id,
        "auth_user_id": row.auth_user_id,
        "created_at": row.created_at.isoformat() if row.created_at is not None else None,
    }


preview_access_service = PreviewAccessService()
