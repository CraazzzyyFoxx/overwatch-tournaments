"""Admin service for the per-tournament preview allowlist (issue #115).

Idempotent add, hard delete, ordered list. Callers gate on
``is_workspace_admin`` before invoking these.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.tournament.preview_access import TournamentPreviewAccess


async def list_preview_access(session: AsyncSession, tournament_id: int) -> list[TournamentPreviewAccess]:
    rows = await session.execute(
        sa.select(TournamentPreviewAccess)
        .where(TournamentPreviewAccess.tournament_id == tournament_id)
        .order_by(TournamentPreviewAccess.created_at)
    )
    return list(rows.scalars().all())


async def add_preview_access(
    session: AsyncSession, tournament_id: int, auth_user_id: int
) -> TournamentPreviewAccess:
    existing = await session.scalar(
        sa.select(TournamentPreviewAccess).where(
            TournamentPreviewAccess.tournament_id == tournament_id,
            TournamentPreviewAccess.auth_user_id == auth_user_id,
        )
    )
    if existing is not None:
        return existing
    row = TournamentPreviewAccess(tournament_id=tournament_id, auth_user_id=auth_user_id)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


async def remove_preview_access(session: AsyncSession, tournament_id: int, auth_user_id: int) -> None:
    await session.execute(
        sa.delete(TournamentPreviewAccess).where(
            TournamentPreviewAccess.tournament_id == tournament_id,
            TournamentPreviewAccess.auth_user_id == auth_user_id,
        )
    )
    await session.commit()


def serialize_entry(row: TournamentPreviewAccess) -> dict:
    return {
        "id": row.id,
        "tournament_id": row.tournament_id,
        "auth_user_id": row.auth_user_id,
        "created_at": row.created_at.isoformat() if row.created_at is not None else None,
    }
