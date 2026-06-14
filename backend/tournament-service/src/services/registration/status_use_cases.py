from __future__ import annotations


class ListStatusCatalog:
    def __init__(self, *, status_service) -> None:
        self._status_service = status_service

    async def execute(self, *, session, workspace_id: int):
        return await self._status_service.list_status_catalog(session, workspace_id)


class ListCustomStatuses:
    def __init__(self, *, status_service) -> None:
        self._status_service = status_service

    async def execute(self, *, session, workspace_id: int):
        return await self._status_service.list_custom_statuses(session, workspace_id)


class CreateCustomStatus:
    def __init__(self, *, status_service) -> None:
        self._status_service = status_service

    async def execute(self, *, session, workspace_id: int, payload):
        return await self._status_service.create_custom_status(
            session,
            workspace_id=workspace_id,
            scope=payload.scope,
            icon_slug=payload.icon_slug,
            icon_color=payload.icon_color,
            name=payload.name,
            description=payload.description,
        )


class UpdateCustomStatus:
    def __init__(self, *, status_service) -> None:
        self._status_service = status_service

    async def execute(self, *, session, workspace_id: int, status_id: int, payload):
        return await self._status_service.update_custom_status(
            session,
            workspace_id=workspace_id,
            status_id=status_id,
            icon_slug=payload.icon_slug,
            icon_color=payload.icon_color,
            name=payload.name,
            description=payload.description,
        )


class DeleteCustomStatus:
    def __init__(self, *, status_service) -> None:
        self._status_service = status_service

    async def execute(self, *, session, workspace_id: int, status_id: int) -> None:
        await self._status_service.delete_custom_status(
            session,
            workspace_id=workspace_id,
            status_id=status_id,
        )


class UpsertBuiltinOverride:
    def __init__(self, *, status_service) -> None:
        self._status_service = status_service

    async def execute(self, *, session, workspace_id: int, scope, slug: str, payload):
        return await self._status_service.upsert_builtin_override(
            session,
            workspace_id=workspace_id,
            scope=scope,
            slug=slug,
            icon_slug=payload.icon_slug,
            icon_color=payload.icon_color,
            name=payload.name,
            description=payload.description,
        )


class ResetBuiltinOverride:
    def __init__(self, *, status_service) -> None:
        self._status_service = status_service

    async def execute(self, *, session, workspace_id: int, scope, slug: str) -> None:
        await self._status_service.reset_builtin_override(
            session,
            workspace_id=workspace_id,
            scope=scope,
            slug=slug,
        )
