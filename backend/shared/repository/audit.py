from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.base import BaseRepository

__all__ = ("AuditLogRepository",)


class AuditLogRepository(BaseRepository[models.AuditLog]):
    """``audit_log`` — append-only platform journal."""

    def __init__(self) -> None:
        super().__init__(models.AuditLog)

    def add(self, session: AsyncSession, row: models.AuditLog) -> models.AuditLog:
        """Stage one row on the caller's session. No flush, no commit.

        The journal has to ride the mutation's transaction unflushed so a
        later rollback takes the row with it.
        """
        session.add(row)
        return row
