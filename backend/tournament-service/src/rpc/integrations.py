"""Integration endpoints over typed RPC: Challonge, registration Google Sheets,
and the public division-grid catalog.

Each handler mirrors a route in ``src/routes/admin/challonge.py``,
``src/routes/admin/registration_sheet.py``, or ``src/routes/division_grid.py``
EXACTLY: it rehydrates the gateway-injected identity (only where the route is
authed), runs the SAME imperative permission check the route's dependency
performed, validates the SAME body schema, calls the SAME service function with
the SAME args, and serializes the SAME way the route returned. None of these
routes use ``response_model_exclude_none`` -> plain ``model_dump(mode="json")``;
the custom dict-returning routes return their dicts verbatim.

The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.

Commit semantics:
  * Challonge: ``import_tournament`` / ``export_tournament`` / ``auto_push_on_confirm``
    commit internally; ``get_sync_log`` + the fetch_* reads are read-only.
  * Sheets: ``upsert_google_sheet_feed`` and ``sync_google_sheet_feed`` commit
    internally; the get/catalog/suggest/preview/export functions are read-only.
  * Division grid: the WRITE service functions (create_grid, create_version,
    update_version, delete_version, publish_version, clone_version,
    upsert_mapping, import_division_grids) do NOT commit internally — the HTTP
    routes commit explicitly, so the matching handlers add ``await session.commit()``
    in the SAME place. The read functions do not commit.

S3 (division grid marketplace import): the route uses ``request.app.state.s3``;
over RPC there is no request.app, so this module owns a module-level ``S3Client``
constructed from ``src.core.config.settings`` (the same shared S3 settings on
``BaseServiceSettings``) and started lazily on first use. ``S3Client.start()`` is
a no-IO call (it only allocates an aiobotocore session), so lazy start is safe
and serve.py needs no extra startup hook.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException
from faststream.rabbit.annotations import RabbitMessage
from pydantic import ValidationError
from shared.clients.s3 import S3Client
from shared.repository import WorkspaceRepository
from shared.rpc.identity import MissingIdentityError, ensure_workspace_permission, rehydrate_user
from shared.schemas.rpc import rpc_error, rpc_ok, status_to_code

from src import models, schemas
from src.core import auth, config, db
from src.schemas.admin import balancer as admin_schemas
from src.services.challonge import service as challonge_service
from src.services.challonge import sync as challonge_sync
from src.services.division_grid import marketplace as division_grid_marketplace
from src.services.division_grid import service as division_grid_service
from src.services.registration import admin as registration_service
from src.services.registration.serializers import serialize_feed

_workspace_repo = WorkspaceRepository()


# --- helpers -----------------------------------------------------------------


def _identity(data: dict[str, Any]) -> models.AuthUser:
    """Rehydrate the gateway-injected identity into a transient AuthUser."""
    return rehydrate_user(data.get("identity"))


def _payload(data: dict[str, Any]) -> dict[str, Any]:
    return data.get("payload") or {}


def _require_id(data: dict[str, Any]) -> int:
    try:
        return int(data["id"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="id is required") from exc


def _path_int(data: dict[str, Any], name: str) -> int:
    raw = data.get(name)
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{name} is required") from exc


def _q(data: dict[str, Any], key: str) -> list[str] | None:
    vals = (data.get("query") or {}).get(key)
    if vals is None:
        return None
    return vals if isinstance(vals, list) else [vals]


def _q1(data: dict[str, Any], key: str, cast: Callable[[str], Any] = str, default: Any = None) -> Any:
    vals = _q(data, key)
    if not vals:
        return default
    try:
        return cast(vals[0])
    except (TypeError, ValueError):
        return default


def _bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def _dump(obj: Any) -> Any:
    """Plain serialization (these routes keep nulls — no exclude_none)."""
    if obj is None:
        return None
    if isinstance(obj, list):
        return [_dump(x) for x in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json")
    return obj


# --- module-level S3 client (lazy start) -------------------------------------

_s3_client: S3Client | None = None
_s3_started = False


async def _get_s3() -> S3Client:
    """Equivalent of the route's ``Depends(get_s3)`` (``request.app.state.s3``).

    Constructed once from the shared S3 settings and started lazily. ``start()``
    only allocates an aiobotocore session (no network I/O), so this is safe to
    call on the first marketplace-import request without a serve.py startup hook.
    """
    global _s3_client, _s3_started
    if _s3_client is None:
        _s3_client = S3Client(
            access_key=config.settings.s3_access_key,
            secret_key=config.settings.s3_secret_key,
            endpoint_url=config.settings.s3_endpoint_url,
            bucket_name=config.settings.s3_bucket_name,
            public_url=config.settings.s3_public_url,
        )
    if not _s3_started:
        await _s3_client.start()
        _s3_started = True
    return _s3_client


# --- division-grid route-local helpers (replicate division_grid.py verbatim) -


async def _get_workspace_or_404(session: Any, workspace_id: int) -> models.Workspace:
    workspace = await _workspace_repo.get_with_default_grid(session, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def _require_workspace_permission(
    workspace_id: int,
    *,
    session: Any,
    user: models.AuthUser,
    action: str,
) -> models.Workspace:
    if not user.has_workspace_permission(workspace_id, "division_grid", action):
        raise HTTPException(status_code=403, detail=f"Permission denied: division_grid.{action} required")
    return await _get_workspace_or_404(session, workspace_id)


async def _get_source_workspace_or_404(
    session: Any,
    *,
    target_workspace_id: int,
    source_workspace_id: int,
    user: models.AuthUser,
) -> models.Workspace:
    if source_workspace_id == target_workspace_id:
        raise HTTPException(status_code=400, detail="Source and target workspace must be different")

    source_workspace = await _get_workspace_or_404(session, source_workspace_id)
    if not user.is_superuser and source_workspace_id not in user.get_workspace_ids():
        raise HTTPException(status_code=403, detail="Source workspace is not accessible")
    return source_workspace


# --- envelope wrapper ---------------------------------------------------------


async def _run(logger: Any, op: Callable[[Any], Awaitable[Any]]) -> dict[str, Any]:
    """Envelope wrapper mirroring admin_misc._run, with identity-failure mapping."""
    try:
        async with db.async_session_maker() as session:
            return rpc_ok(await op(session))
    except MissingIdentityError as exc:
        return rpc_error("unauthorized", str(exc) or "Not authenticated")
    except HTTPException as exc:
        return rpc_error(status_to_code(exc.status_code), str(exc.detail))
    except ValidationError as exc:
        return rpc_error("unprocessable", str(exc))
    except Exception:  # pragma: no cover - defensive worker guard
        logger.exception("tournament integrations rpc failed")
        return rpc_error("internal", "internal error")


def register(broker: Any, logger: Any) -> None:
    # ══ Challonge (admin) ════════════════════════════════════════════════════
    # Prefix /challonge -> /api/v1/admin/challonge/...

    @broker.subscriber("rpc.tournament.challonge_fetch_tournament")
    async def _challonge_fetch_tournament(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            # Route: Depends(require_permission("challonge", "read")) — global permission.
            if not user.has_permission("challonge", "read"):
                raise HTTPException(status_code=403, detail="Permission denied: challonge.read required")
            tournament_slug = _q1(data, "tournament_slug")
            if not tournament_slug:
                raise HTTPException(status_code=422, detail="tournament_slug is required")
            return _dump(await challonge_service.fetch_tournament(tournament_slug))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_fetch_participants")
    async def _challonge_fetch_participants(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            if not user.has_permission("challonge", "read"):
                raise HTTPException(status_code=403, detail="Permission denied: challonge.read required")
            tournament_id = _q1(data, "tournament_id", int)
            if tournament_id is None:
                raise HTTPException(status_code=422, detail="tournament_id is required")
            return _dump(await challonge_service.fetch_participants(tournament_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_fetch_matches")
    async def _challonge_fetch_matches(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            if not user.has_permission("challonge", "read"):
                raise HTTPException(status_code=403, detail="Permission denied: challonge.read required")
            tournament_id = _q1(data, "tournament_id", int)
            if tournament_id is None:
                raise HTTPException(status_code=422, detail="tournament_id is required")
            return _dump(await challonge_service.fetch_matches(tournament_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_import")
    async def _challonge_import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            # Route: Depends(require_tournament_permission("challonge", "sync")).
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="challonge", action="sync"
            )
            dry_run = _q1(data, "dry_run", _bool, default=False)
            # import_tournament commits internally.
            return await challonge_sync.import_tournament(session, tournament_id, dry_run=dry_run)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_export")
    async def _challonge_export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="challonge", action="sync"
            )
            # export_tournament commits internally.
            return await challonge_sync.export_tournament(session, tournament_id)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_push_result")
    async def _challonge_push_result(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            # Route: Depends(require_encounter_permission("challonge", "sync")).
            ws_id = await auth._get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "challonge", "sync")
            # auto_push_on_confirm commits internally.
            await challonge_sync.auto_push_on_confirm(session, encounter_id)
            return {"status": "ok"}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_sync_log")
    async def _challonge_sync_log(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            # Route: Depends(require_tournament_permission("challonge", "read")).
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="challonge", action="read"
            )
            limit = _q1(data, "limit", int, default=50)
            logs = await challonge_sync.get_sync_log(session, tournament_id, limit)
            return [
                {
                    "id": log.id,
                    "created_at": log.created_at,
                    "source_id": log.source_id,
                    "direction": log.direction,
                    "operation": log.operation,
                    "entity_type": log.entity_type,
                    "entity_id": log.entity_id,
                    "challonge_id": log.challonge_id,
                    "status": log.status,
                    "conflict_type": log.conflict_type,
                    "before_json": log.before_json,
                    "after_json": log.after_json,
                    "error_message": log.error_message,
                }
                for log in logs
            ]

        return await _run(logger, op)

    # ══ Registration Google Sheets (admin) ═══════════════════════════════════
    # Prefix /balancer -> /api/v1/admin/balancer/...

    @broker.subscriber("rpc.tournament.sheet_get")
    async def _sheet_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            # Route: Depends(require_tournament_permission("team", "read")).
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="read"
            )
            feed = await registration_service.get_google_sheet_feed(session, tournament_id)
            if feed is None:
                return None
            return _dump(serialize_feed(feed))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sheet_upsert")
    async def _sheet_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            # Route: Depends(require_tournament_permission("team", "import")).
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="import"
            )
            body = admin_schemas.BalancerGoogleSheetFeedUpsert.model_validate(_payload(data))
            # upsert_google_sheet_feed commits internally.
            feed = await registration_service.upsert_google_sheet_feed(
                session,
                tournament_id,
                source_url=body.source_url,
                title=body.title,
                auto_sync_enabled=body.auto_sync_enabled,
                auto_sync_interval_seconds=body.auto_sync_interval_seconds,
                mapping_config_json=body.mapping_config_json,
                value_mapping_json=body.value_mapping_json,
            )
            return _dump(serialize_feed(feed))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sheet_sync")
    async def _sheet_sync(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            # Route: Depends(require_tournament_permission("team", "import")).
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="import"
            )
            # sync_google_sheet_feed commits internally.
            result = await registration_service.sync_google_sheet_feed(session, tournament_id)
            return _dump(
                admin_schemas.BalancerGoogleSheetFeedSyncResponse(
                    created=result.created,
                    updated=result.updated,
                    withdrawn=result.withdrawn,
                    total=result.total,
                    skipped=result.skipped,
                    errors=[admin_schemas.MappingPreviewFieldError(**error) for error in result.errors],
                    feed=serialize_feed(result.feed),
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sheet_mapping_catalog")
    async def _sheet_mapping_catalog(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            # Route: Depends(require_tournament_permission("team", "read")).
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="read"
            )
            include_headers = _q1(data, "include_headers", _bool, default=False)
            catalog = await registration_service.get_mapping_catalog(
                session, tournament_id, include_headers=include_headers
            )
            return _dump(admin_schemas.BalancerGoogleSheetMappingCatalogResponse(**catalog))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sheet_suggest_mapping")
    async def _sheet_suggest_mapping(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            # Route: Depends(require_tournament_permission("team", "read")).
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="read"
            )
            body = admin_schemas.BalancerGoogleSheetMappingSuggestRequest.model_validate(_payload(data))
            _, headers, mapping = await registration_service.suggest_google_sheet_mapping(
                session, tournament_id, source_url=body.source_url
            )
            return _dump(
                admin_schemas.BalancerGoogleSheetMappingSuggestResponse(
                    headers=headers,
                    mapping_config_json=mapping,
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sheet_preview")
    async def _sheet_preview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            # Route: Depends(require_tournament_permission("team", "read")).
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="read"
            )
            body = admin_schemas.BalancerGoogleSheetMappingPreviewRequest.model_validate(_payload(data))
            preview = await registration_service.preview_google_sheet_mapping(
                session,
                tournament_id,
                source_url=body.source_url,
                mapping_config_json=body.mapping_config_json,
                value_mapping_json=body.value_mapping_json,
                sample_rows=body.sample_rows,
            )
            return _dump(admin_schemas.BalancerGoogleSheetMappingPreviewResponse(**preview))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sheet_players_export")
    async def _sheet_players_export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            # Route: Depends(require_tournament_permission("player", "read")).
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="player", action="read"
            )
            payload = await registration_service.export_active_registrations(session, tournament_id)
            return _dump(admin_schemas.BalancerPlayerExportResponse(**payload))

        return await _run(logger, op)

    # ══ Division grids (PUBLIC — NOT under /admin) ════════════════════════════
    # Prefix /division-grids -> /api/v1/division-grids/...
    #
    # Auth split: every route here has Depends(auth.get_current_active_user) in
    # the HTTP service, so ALL division-grid endpoints require an authenticated
    # user. The two "open" reads (get_version, get_mapping) still require auth but
    # NOT a workspace permission. The remaining reads/writes additionally enforce
    # the division_grid.<action> workspace permission via _require_workspace_permission.

    @broker.subscriber("rpc.tournament.grid_workspace_list")
    async def _grid_workspace_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await _require_workspace_permission(workspace_id, session=session, user=user, action="read")
            grids = await division_grid_service.get_workspace_grids(session, workspace_id)
            return [
                _dump(schemas.DivisionGridRead.model_validate(grid, from_attributes=True)) for grid in grids
            ]

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_workspace_create")
    async def _grid_workspace_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await _require_workspace_permission(workspace_id, session=session, user=user, action="create")
            body = schemas.DivisionGridCreate.model_validate(_payload(data))
            grid = await division_grid_service.create_grid(session, workspace_id, body)
            await session.commit()  # route commits explicitly (service does not).
            return _dump(schemas.DivisionGridRead.model_validate(grid, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_marketplace_workspaces")
    async def _grid_marketplace_workspaces(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await _require_workspace_permission(workspace_id, session=session, user=user, action="read")
            return _dump(
                await division_grid_marketplace.list_marketplace_workspaces(
                    session, target_workspace_id=workspace_id, user=user
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_marketplace_grids")
    async def _grid_marketplace_grids(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await _require_workspace_permission(workspace_id, session=session, user=user, action="read")
            source_workspace_id = _q1(data, "source_workspace_id", int)
            if source_workspace_id is None:
                raise HTTPException(status_code=422, detail="source_workspace_id is required")
            source_workspace = await _get_source_workspace_or_404(
                session,
                target_workspace_id=workspace_id,
                source_workspace_id=source_workspace_id,
                user=user,
            )
            return _dump(
                await division_grid_marketplace.list_marketplace_grids(
                    session, source_workspace_id=source_workspace.id
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_marketplace_import")
    async def _grid_marketplace_import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            target_workspace = await _require_workspace_permission(
                workspace_id, session=session, user=user, action="import"
            )
            body = schemas.DivisionGridMarketplaceImportRequest.model_validate(_payload(data))
            source_workspace = await _get_source_workspace_or_404(
                session,
                target_workspace_id=workspace_id,
                source_workspace_id=body.source_workspace_id,
                user=user,
            )
            source_grids = await division_grid_marketplace.get_marketplace_grids_by_ids(
                session,
                source_workspace_id=source_workspace.id,
                source_grid_ids=body.source_grid_ids,
            )
            s3 = await _get_s3()
            result = await division_grid_marketplace.import_division_grids(
                session,
                s3,
                target_workspace=target_workspace,
                source_workspace=source_workspace,
                source_grids=source_grids,
                set_default=body.set_default,
            )
            await session.commit()  # route commits explicitly (service does not).
            return _dump(result)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_versions_list")
    async def _grid_versions_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            grid_id = _require_id(data)
            grid = await division_grid_service.get_grid_by_id(session, grid_id)
            await _require_workspace_permission(grid.workspace_id, session=session, user=user, action="read")
            versions = await division_grid_service.get_versions(session, grid.workspace_id, grid_id)
            return [
                _dump(schemas.DivisionGridVersionRead.model_validate(version, from_attributes=True))
                for version in versions
            ]

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_create")
    async def _grid_version_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            grid_id = _require_id(data)
            grid = await division_grid_service.get_grid_by_id(session, grid_id)
            await _require_workspace_permission(grid.workspace_id, session=session, user=user, action="create")
            body = schemas.DivisionGridVersionCreate.model_validate(_payload(data))
            version = await division_grid_service.create_version(session, grid.workspace_id, grid_id, body)
            await session.commit()  # route commits explicitly (service does not).
            return _dump(schemas.DivisionGridVersionRead.model_validate(version, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_get")
    async def _grid_version_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Route: Depends(get_current_active_user) only — no workspace permission.
            _identity(data)
            version_id = _require_id(data)
            version = await division_grid_service.get_version(session, version_id)
            return _dump(schemas.DivisionGridVersionRead.model_validate(version, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_update")
    async def _grid_version_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            version_id = _require_id(data)
            version = await division_grid_service.get_version(session, version_id)
            await _require_workspace_permission(
                version.grid.workspace_id, session=session, user=user, action="update"
            )
            body = schemas.DivisionGridVersionUpdate.model_validate(_payload(data))
            version = await division_grid_service.update_version(session, version_id, body)
            await session.commit()  # route commits explicitly (service does not).
            return _dump(schemas.DivisionGridVersionRead.model_validate(version, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_delete")
    async def _grid_version_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            version_id = _require_id(data)
            version = await division_grid_service.get_version(session, version_id)
            await _require_workspace_permission(
                version.grid.workspace_id, session=session, user=user, action="delete"
            )
            await division_grid_service.delete_version(session, version_id)
            await session.commit()  # route commits explicitly (service does not).
            return None  # route returns 204 (no body).

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_publish")
    async def _grid_version_publish(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            version_id = _require_id(data)
            version = await division_grid_service.get_version(session, version_id)
            await _require_workspace_permission(
                version.grid.workspace_id, session=session, user=user, action="publish"
            )
            version = await division_grid_service.publish_version(session, version_id)
            await session.commit()  # route commits explicitly (service does not).
            return _dump(schemas.DivisionGridVersionRead.model_validate(version, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_clone")
    async def _grid_version_clone(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            version_id = _require_id(data)
            version = await division_grid_service.get_version(session, version_id)
            await _require_workspace_permission(
                version.grid.workspace_id, session=session, user=user, action="create"
            )
            cloned = await division_grid_service.clone_version(session, version_id)
            await session.commit()  # route commits explicitly (service does not).
            return _dump(schemas.DivisionGridVersionRead.model_validate(cloned, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_mapping_get")
    async def _grid_mapping_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Route: Depends(get_current_active_user) only — no workspace permission.
            _identity(data)
            source_version_id = _path_int(data, "source_version_id")
            target_version_id = _path_int(data, "target_version_id")
            mapping = await division_grid_service.get_mapping(session, source_version_id, target_version_id)
            if mapping is None:
                raise HTTPException(status_code=404, detail="Division grid mapping not found")
            return _dump(schemas.DivisionGridMappingRead.model_validate(mapping, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_mapping_put")
    async def _grid_mapping_put(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            source_version_id = _path_int(data, "source_version_id")
            target_version_id = _path_int(data, "target_version_id")
            source_version = await division_grid_service.get_version(session, source_version_id)
            await _require_workspace_permission(
                source_version.grid.workspace_id, session=session, user=user, action="update"
            )
            body = schemas.DivisionGridMappingWrite.model_validate(_payload(data))
            mapping = await division_grid_service.upsert_mapping(
                session, source_version_id, target_version_id, body
            )
            await session.commit()  # route commits explicitly (service does not).
            return _dump(schemas.DivisionGridMappingRead.model_validate(mapping, from_attributes=True))

        return await _run(logger, op)
