"""The organizer journal: what the draft writes down, and how it reads back.

``DraftAuditEvent`` is the private trail behind the Draft Room's journal strip.
Every exceptional AND every ordinary board mutation lands here -- a pick, an
autopick, an override, a clock extension, and each lifecycle move -- so the
organizer reads one ordered story instead of reconstructing it from the board.

Rows are written inside the caller's transaction (``record`` flushes, never
commits), so a mutation and its journal entry land together or not at all.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.balancer.draft import DraftAuditEvent, DraftSession
from shared.repository.draft import DraftAuditEventRepository
from src import schemas

__all__ = ("DEFAULT_REASONS", "JOURNAL_LIMIT_DEFAULT", "JOURNAL_LIMIT_MAX", "DraftJournalService", "journal_service")

JOURNAL_LIMIT_DEFAULT = 100
JOURNAL_LIMIT_MAX = 500

#: ``DraftAuditEvent.reason`` is NOT NULL and most actions have no human reason
#: to give, so each one names itself. A caller with a real reason (an admin's
#: override note, an autopick's ``expiry``/``admin`` cause) passes it instead.
DEFAULT_REASONS: dict[str, str] = {
    "pick_made": "Captain made the pick",
    "pick_autopicked": "Autopicked",
    "pick_overridden": "Admin override",
    "pick_extended": "Admin extended the pick clock",
    "paused": "Draft paused",
    "resumed": "Draft resumed",
    "rollback": "Last resolved pick rolled back",
    "started": "Draft started",
    "completed": "Draft completed",
    "cancelled": "Draft cancelled",
}


class DraftJournalService:
    def __init__(self, *, audit_repo: DraftAuditEventRepository = DraftAuditEventRepository()) -> None:
        self.audit_repo = audit_repo

    async def record(
        self,
        session: AsyncSession,
        session_id: int,
        *,
        action: str,
        entity_type: str,
        entity_id: int,
        actor_auth_user_id: int | None,
        reason: str | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> DraftAuditEvent:
        """Append one journal row. Flushes only -- the caller owns the commit."""
        return await self.audit_repo.create(
            session,
            DraftAuditEvent(
                session_id=session_id,
                actor_auth_user_id=actor_auth_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                reason=(reason or "").strip() or DEFAULT_REASONS.get(action, action),
                before_json=before or {},
                after_json=after or {},
            ),
        )

    async def record_lifecycle(
        self,
        session: AsyncSession,
        draft_session: DraftSession,
        *,
        action: str,
        actor_auth_user_id: int | None,
        after: dict[str, Any] | None = None,
    ) -> DraftAuditEvent:
        """A session-scoped move (start/pause/resume/rollback/cancel/complete)."""
        return await self.record(
            session,
            draft_session.id,
            action=action,
            entity_type="draft_session",
            entity_id=draft_session.id,
            actor_auth_user_id=actor_auth_user_id,
            after={"status": draft_session.status, **(after or {})},
        )

    async def list_entries(
        self, session: AsyncSession, draft_session: DraftSession, *, limit: int
    ) -> schemas.DraftJournalResponse:
        rows = await self.audit_repo.list_with_actor(
            session, draft_session.id, limit=max(1, min(limit, JOURNAL_LIMIT_MAX))
        )
        return schemas.DraftJournalResponse(
            session_id=draft_session.id,
            entries=[_entry(row, actor_name) for row, actor_name in rows],
        )


def _entry(row: DraftAuditEvent, actor_name: str | None) -> schemas.DraftJournalEntry:
    # after over before: the journal answers "what is it now", and only an
    # override writes the same keys twice.
    payload: dict[str, Any] = {**(row.before_json or {}), **(row.after_json or {})}
    return schemas.DraftJournalEntry(
        id=row.id,
        created_at=row.created_at,
        action=row.action,
        actor_auth_user_id=row.actor_auth_user_id,
        # NULL for the clock and every other system action -- there is no account
        # behind them, and inventing one would put a name on nobody's decision.
        actor_name=actor_name if row.actor_auth_user_id is not None else None,
        reason=row.reason,
        pick_no=payload.get("overall_no"),
        team_id=payload.get("team_id"),
        player_id=payload.get("player_id"),
        role=payload.get("role"),
        seconds=payload.get("seconds"),
    )


journal_service = DraftJournalService()
