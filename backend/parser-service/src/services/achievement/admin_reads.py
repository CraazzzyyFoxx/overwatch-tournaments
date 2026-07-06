"""Workspace-resolution helpers for the achievement-rule admin surface.

Extracted verbatim from the former ``src/routes/admin/achievement_rule.py`` HTTP
route so the typed-RPC handlers (``src/rpc/achievements.py``) can reuse them after
the FastAPI face was removed.

``HTTPException`` here is ``fastapi.HTTPException`` on purpose: the parser RPC
envelope (``src/rpc/_common.py``) maps ``fastapi.HTTPException`` status codes onto
the ``{ok,data,error}`` envelope, and a Starlette base-class instance would not be
caught by that ``except`` clause (it is a strict subclass), silently degrading
404/403/400 into a generic 500.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.errors import BaseAPIException as HTTPException
from src import models


async def _get_workspace_or_404(session: AsyncSession, workspace_id: int) -> models.Workspace:
    workspace = await session.get(models.Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


def _get_visible_workspace_ids(user: models.AuthUser, target_workspace_id: int) -> list[int] | None:
    if user.is_superuser:
        return None
    return [workspace_id for workspace_id in user.get_workspace_ids() if workspace_id != target_workspace_id]


async def _get_source_workspace_or_404(
    session: AsyncSession,
    *,
    target_workspace_id: int,
    source_workspace_id: int,
    user: models.AuthUser,
) -> models.Workspace:
    if source_workspace_id == target_workspace_id:
        raise HTTPException(status_code=400, detail="Source and target workspace must be different")

    workspace = await session.get(models.Workspace, source_workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Source workspace not found")
    if not user.is_superuser and source_workspace_id not in user.get_workspace_ids():
        raise HTTPException(status_code=403, detail="Source workspace is not accessible")
    return workspace
