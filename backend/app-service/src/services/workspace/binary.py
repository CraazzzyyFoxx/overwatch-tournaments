"""Workspace-scoped binary side effects: branding icons, catalog assets, match logs.

Lifted out of ``src/rpc/binary.py`` so that transport only decodes base64 and
gates permissions. Everything with a consequence lives here: the S3 calls, the
``workspace`` row read/write, the ``audit_log`` row and the transaction boundary.

The two icon writes mutate the workspace, so each appends one ``audit_log`` row in
the same transaction as the write.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.clients.s3.upload import upload_asset, upload_avatar
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import WorkspaceRepository
from shared.services.audit import record_audit
from src import models
from src.core.clients import s3_client
from src.services.workspace.service import WorkspaceService
from src.services.workspace.service import workspaces as _workspaces

__all__ = ["WorkspaceBinaryService", "workspace_binary"]

_ICON_AUDIT_ACTION = "workspace.branding_update"


class WorkspaceBinaryService:
    def __init__(
        self,
        *,
        workspaces: WorkspaceService = _workspaces,
        workspace_repo: WorkspaceRepository = WorkspaceRepository(),
    ) -> None:
        self.workspaces = workspaces
        self.workspace_repo = workspace_repo

    # --- branding icon ------------------------------------------------------

    async def _load_workspace(self, session: AsyncSession, workspace_id: int) -> models.Workspace:
        workspace = await self.workspaces.get_by_id(session, workspace_id)
        if not workspace:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return workspace

    async def _record_icon_change(
        self,
        session: AsyncSession,
        workspace: models.Workspace,
        *,
        workspace_id: int,
        actor: Any,
        icon_before: str | None,
        icon_after: str | None,
    ) -> None:
        await record_audit(
            session,
            action=_ICON_AUDIT_ACTION,
            source="admin",
            actor=actor,
            actor_label=actor.username,
            # The workspace the caller's permission check ran against, reused rather
            # than re-derived: the audit scope must be the authorization scope.
            workspace_id=workspace_id,
            entity_type="workspace",
            entity_id=workspace.id,
            entity_label=workspace.slug,
            before={"icon_url": icon_before},
            after={"icon_url": icon_after},
        )

    async def set_icon(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        actor: Any,
        file_data: bytes,
        content_type: str,
    ) -> models.Workspace:
        workspace = await self._load_workspace(session, workspace_id)
        result = await upload_avatar(
            s3_client,
            entity_type="workspaces",
            entity_id=workspace_id,
            file_data=file_data,
            content_type=content_type,
        )
        if not result.success:
            raise HTTPException(status_code=400, detail=result.error)
        icon_before = workspace.icon_url
        workspace = await self.workspaces.update(session, workspace, {"icon_url": result.public_url})
        await self._record_icon_change(
            session,
            workspace,
            workspace_id=workspace_id,
            actor=actor,
            icon_before=icon_before,
            icon_after=workspace.icon_url,
        )
        await session.commit()
        return workspace

    async def clear_icon(self, session: AsyncSession, *, workspace_id: int, actor: Any) -> models.Workspace:
        workspace = await self._load_workspace(session, workspace_id)
        await s3_client.delete_prefix(f"avatars/workspaces/{workspace_id}/")
        icon_before = workspace.icon_url
        workspace = await self.workspaces.update(session, workspace, {"icon_url": None})
        # The S3 objects are already gone by now; a rollback here would leave the
        # row pointing at a dead URL, and the audit row would vanish with it -- so
        # the trail matches the database, which is what the journal claims to show.
        await self._record_icon_change(
            session,
            workspace,
            workspace_id=workspace_id,
            actor=actor,
            icon_before=icon_before,
            icon_after=None,
        )
        await session.commit()
        return workspace

    # --- catalog assets -----------------------------------------------------

    async def _resolve_workspace_slug(self, session: AsyncSession, workspace_id: int | None) -> str | None:
        if workspace_id is None:
            return None
        workspace = await self.workspace_repo.get(session, workspace_id)
        return workspace.slug if workspace else None

    async def store_asset(
        self,
        session: AsyncSession,
        *,
        asset_type: Any,
        slug: Any,
        file_data: bytes,
        content_type: str,
        workspace_id: int | None,
    ) -> dict[str, Any]:
        workspace_slug = await self._resolve_workspace_slug(session, workspace_id)
        result = await upload_asset(
            s3_client,
            asset_type=asset_type,
            slug=slug,
            file_data=file_data,
            content_type=content_type,
            workspace_slug=workspace_slug,
        )
        if not result.success:
            raise HTTPException(status_code=400, detail=result.error)
        return {"key": result.key, "public_url": result.public_url}

    async def remove_asset(
        self,
        session: AsyncSession,
        *,
        asset_type: Any,
        slug: Any,
        workspace_id: int | None,
    ) -> int:
        workspace_slug = await self._resolve_workspace_slug(session, workspace_id)
        if workspace_slug:
            prefix = f"assets/{asset_type}/{workspace_slug}/{slug}."
        else:
            prefix = f"assets/{asset_type}/{slug}."
        deleted = await s3_client.delete_prefix(prefix)
        if deleted == 0:
            raise HTTPException(status_code=404, detail="Asset not found")
        return deleted

    # --- match logs ---------------------------------------------------------

    def _match_log_ref_query(self, match_id: int) -> sa.Select:
        """The log reference for one match: its file name plus the tournament id
        that keys the S3 prefix. A two-table join, so it stays a query here rather
        than hiding behind a CRUD repository."""
        return (
            sa.select(models.Match.log_name, models.Encounter.tournament_id)
            .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
            .where(models.Match.id == match_id)
        )

    async def resolve_match_log_ref(self, session: AsyncSession, match_id: int) -> tuple[str, int]:
        """The log filename and owning tournament id for one match, or a 404.

        Split from the S3 fetch so a caller can gate tournament visibility
        (hidden tournaments) on the resolved ``tournament_id`` before paying for
        the S3 round trip.
        """
        row = (await session.execute(self._match_log_ref_query(match_id))).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Match not found")
        log_name, tournament_id = row
        filename = (log_name or "").rsplit("/", 1)[-1]
        if not filename or ".." in filename:
            raise HTTPException(status_code=404, detail="No log available for this match")
        return filename, tournament_id

    async def fetch_log_bytes(self, tournament_id: int, filename: str) -> bytes:
        """Fetch one already-resolved log's raw bytes from S3."""
        data_bytes = await s3_client.get_object(f"logs/{tournament_id}/{filename}")
        if data_bytes is None:
            raise HTTPException(status_code=404, detail="Log file not found")
        return data_bytes

    async def match_log(self, session: AsyncSession, match_id: int) -> tuple[str, bytes]:
        """Fetch a match's raw log from S3 as ``(filename, bytes)``."""
        filename, tournament_id = await self.resolve_match_log_ref(session, match_id)
        return filename, await self.fetch_log_bytes(tournament_id, filename)


workspace_binary = WorkspaceBinaryService()
