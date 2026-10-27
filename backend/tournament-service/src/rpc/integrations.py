"""Integration endpoints over typed RPC: Challonge, registration Google Sheets,
and the public division-grid catalog.

The gateway passes path params as ``data["<name>"]`` (and the primary id as
``data["id"]`` when the RouteSpec sets IDParam), query params as
``data["query"][key] = [values]``, and the JSON body as ``data["payload"]``.
Responses are plain ``model_dump(mode="json")``; the custom dict-returning
handlers return their dicts verbatim.

Commit semantics:
  * Challonge: ``import_tournament`` / ``export_tournament`` / ``auto_push_on_confirm``
    commit internally; ``get_sync_log`` + the fetch_* reads are read-only. A sync
    already running for the tournament is a 409, Challonge unreachable a 503.
  * Sheets: ``upsert_google_sheet_feed`` and ``sync_google_sheet_feed`` commit
    internally; the get/catalog/suggest/preview/export functions are read-only.
  * Division grid: the WRITE service functions (create_grid, create_version,
    update_version, delete_version, publish_version, clone_version,
    upsert_mapping, import_division_grids) do NOT commit internally, so the
    matching handlers ``await session.commit()`` themselves; the grid-cache
    invalidations those writes stage run once that commit lands
    (``shared.services.division_grid.cache.invalidate_after_commit``). The reads
    do not commit.

S3 (division grid marketplace import): the client comes from
``src.rpc._s3.get_s3`` — one lazily-started, process-wide ``S3Client`` shared
with the other S3-using subscriber modules.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared import models, quota
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from shared.services.audit import record_admin_audit
from shared.services.division_grid.access import (
    require_grid_version_read_access,
    require_marketplace_source_access,
)
from src import schemas
from src.clients.challonge import challonge_client
from src.core import auth
from src.rpc._helpers import _bool, _dump, _identity, _path_int, _payload, _q1, _require_id, _require_q1, _run
from src.rpc._s3 import get_s3
from src.services.admin import tournament as tournament_admin_service
from src.services.challonge import sync as challonge_sync
from src.services.division_grid import import_jobs as division_grid_import_jobs
from src.services.division_grid import marketplace as division_grid_marketplace
from src.services.division_grid import portable as division_grid_portable
from src.services.division_grid.service import division_grid_service, require_writable
from src.services.registration import sheet_sync
from src.services.registration.player_export import (
    PLAYER_EXPORT_DEFAULT_FORMAT,
    PLAYER_EXPORT_FORMATS,
    player_export_service,
)
from src.services.registration.serializers import serialize_feed
from src.services.tournament import flows as tournament_flows

# --- division-grid helpers ---------------------------------------------------


async def _get_workspace_or_404(session: Any, workspace_id: int) -> models.Workspace:
    workspace = await division_grid_service.get_workspace_with_default_grid(session, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return workspace


async def require_workspace_permission(
    workspace_id: int,
    *,
    session: Any,
    user: models.AuthUser,
    action: str,
) -> models.Workspace:
    # ``None`` only comes from a system grid's row (a route naming the grid or version): no workspace may write it.
    if action != "read":
        require_writable(workspace_id)
    if not user.has_workspace_permission(workspace_id, "division_grid", action):
        raise HTTPException(status_code=403, detail=f"Permission denied: division_grid.{action} required")
    return await _get_workspace_or_404(session, workspace_id)


def _version_read(version: Any, discipline: str | None = None) -> schemas.DivisionGridVersionRead:
    """The version read, carrying its game when the grid is at hand (never a lazy load)."""
    read = schemas.DivisionGridVersionRead.model_validate(version, from_attributes=True)
    if discipline is None and "grid" in vars(version):
        discipline = version.grid.discipline
    read.discipline = discipline
    return read


def _require_version_read_access(user: models.AuthUser, version: Any) -> None:
    require_grid_version_read_access(user, version.grid.workspace_id)


def _require_grid_read_access(user: models.AuthUser, grid: Any) -> None:
    require_grid_version_read_access(user, grid.workspace_id, "Division grid not found")


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
    require_marketplace_source_access(
        user,
        source_workspace_id=source_workspace_id,
        source_is_hidden=source_workspace.is_hidden,
    )
    return source_workspace


def register(broker: Any, logger: Any) -> None:
    # ══ Challonge (admin) ════════════════════════════════════════════════════

    @broker.subscriber("rpc.tournament.challonge_fetch_tournament")
    async def _challonge_fetch_tournament(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            # A global permission, not a workspace one.
            if not user.has_permission("challonge", "read"):
                raise HTTPException(status_code=403, detail="Permission denied: challonge.read required")
            tournament_slug = _q1(data, "tournament_slug")
            if not tournament_slug:
                raise HTTPException(status_code=422, detail="tournament_slug is required")
            return _dump(await challonge_client.fetch_tournament(tournament_slug))

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
            return _dump(await challonge_client.fetch_participants(tournament_id))

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
            return _dump(await challonge_client.fetch_matches(tournament_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_import")
    async def _challonge_import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="challonge", action="update"
            )
            dry_run = _q1(data, "dry_run", _bool, default=False)
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            # An import spends CHALLONGE's rate limit, not ours: the bracket, the
            # participants and every match come over their API on one budget shared
            # by every workspace we host, and no amount of our own capacity buys
            # more of it. A dry run costs exactly the same — it fetches everything
            # and only skips the writes.
            await quota.charge(user, "tournament.challonge_import", workspace_id=ws_id)
            # import_tournament commits internally, so the row is staged on that
            # session first; the workspace is the one the check above resolved.
            await record_admin_audit(
                session,
                action="challonge.import",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                after={"dry_run": dry_run},
                source="challonge",
            )
            # An admin waits a few seconds for a running import (the auto-sync's, say), then gets a 409.
            return await challonge_sync.sync_service.import_tournament(
                session, tournament_id, dry_run=dry_run, lock_wait_seconds=challonge_sync.ADMIN_LOCK_WAIT_SECONDS
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_export")
    async def _challonge_export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="challonge", action="update"
            )
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            # Same third-party budget as the import, spent in the other direction:
            # one write per participant and per match against Challonge's limit.
            await quota.charge(user, "tournament.challonge_export", workspace_id=ws_id)
            # export_tournament commits internally — stage the row first.
            await record_admin_audit(
                session,
                action="challonge.export",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
                source="challonge",
            )
            return await challonge_sync.sync_service.export_tournament(session, tournament_id)

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_push_result")
    async def _challonge_push_result(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            encounter_id = _require_id(data)
            ws_id = await auth.get_encounter_workspace_id(session, encounter_id)
            ensure_workspace_permission(user, ws_id, "challonge", "update")
            # auto_push_on_confirm commits internally.
            await record_admin_audit(
                session,
                action="challonge.push_result",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="encounter",
                entity_id=encounter_id,
                source="challonge",
            )
            await challonge_sync.sync_service.auto_push_on_confirm(session, encounter_id)
            return {"status": "ok"}

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_sync_log")
    async def _challonge_sync_log(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="challonge", action="read"
            )
            limit = min(max(_q1(data, "limit", int, default=50), 1), 200)
            logs = await challonge_sync.sync_service.get_sync_log(session, tournament_id, limit)
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
                    # Structured detail the admin UI groups on — e.g. an import
                    # failure's `missing_participant_ids`, which it would
                    # otherwise have to parse back out of `error_message`.
                    "payload_json": log.payload_json,
                    "before_json": log.before_json,
                    "after_json": log.after_json,
                    "error_message": log.error_message,
                }
                for log in logs
            ]

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_create_tournament")
    async def _challonge_create_tournament(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _require_q1(data, "workspace_id", int)
            ensure_workspace_permission(user, workspace_id, "tournament", "create")
            is_league = _q1(data, "is_league", _bool, default=False)
            start_date = _require_q1(data, "start_date", date.fromisoformat)
            end_date = _require_q1(data, "end_date", date.fromisoformat)
            challonge_slug = _require_q1(data, "challonge_slug")
            # The game the imported tournament is played in: the caller's explicit choice, never a default.
            discipline = _require_q1(data, "discipline")
            division_grid_version_id = _q1(data, "division_grid_version_id", int)
            # create_tournament_from_challonge commits, so the row is staged before
            # it: the tournament id does not exist yet, the request is the story.
            await record_admin_audit(
                session,
                action="challonge.create",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="tournament",
                entity_label=challonge_slug,
                after={
                    "challonge_slug": challonge_slug,
                    "discipline": discipline,
                    "is_league": is_league,
                    "start_date": start_date,
                    "end_date": end_date,
                    "division_grid_version_id": division_grid_version_id,
                },
                source="challonge",
            )
            tournament = await tournament_admin_service.tournament_service.create_tournament_from_challonge(
                session,
                workspace_id=workspace_id,
                discipline=discipline,
                is_league=is_league,
                start_date=start_date,
                end_date=end_date,
                challonge_slug=challonge_slug,
                division_grid_version_id=division_grid_version_id,
            )
            # `tournament_read`, not `to_pydantic`: `create_tournament_from_challonge`
            # just created the `challonge_source` row this response's
            # `challonge_id`/`challonge_slug` are derived from, and `to_pydantic`
            # emits them as None unless the refs are resolved and passed in.
            return _dump(await tournament_flows.flows_service.tournament_read(session, tournament, ["stages"]))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_team_preview")
    async def _challonge_team_preview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_q1(data, "tournament_id", int)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="challonge", action="read"
            )
            return _dump(await challonge_sync.sync_service.preview_team_mapping(session, tournament_id))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.challonge_team_apply")
    async def _challonge_team_apply(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_q1(data, "tournament_id", int)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="challonge", action="update"
            )
            body = schemas.ChallongeTeamSyncRequest.model_validate(_payload(data))
            # apply_team_mapping commits internally — stage the row first.
            await record_admin_audit(
                session,
                action="challonge.team_apply",
                actor=user,
                data=data,
                workspace_id=await auth.get_tournament_workspace_id(session, tournament_id),
                entity_type="tournament",
                entity_id=tournament_id,
                after={"mapping_count": len(body.mappings)},
                source="challonge",
            )
            return _dump(await challonge_sync.sync_service.apply_team_mapping(session, tournament_id, body.mappings))

        return await _run(logger, op)

    # ══ Registration Google Sheets (admin) ═══════════════════════════════════

    @broker.subscriber("rpc.tournament.sheet_get")
    async def _sheet_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="read"
            )
            feed = await sheet_sync.sheet_sync_service.get_google_sheet_feed(session, tournament_id)
            if feed is None:
                return None
            return _dump(serialize_feed(feed))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sheet_upsert")
    async def _sheet_upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="create"
            )
            body = schemas.BalancerGoogleSheetFeedUpsert.model_validate(_payload(data))
            # upsert_google_sheet_feed commits internally — stage the row first.
            await record_admin_audit(
                session,
                action="registration.sheet_upsert",
                actor=user,
                data=data,
                workspace_id=await auth.get_tournament_workspace_id(session, tournament_id),
                entity_type="tournament",
                entity_id=tournament_id,
                after={
                    "source_url": body.source_url,
                    "title": body.title,
                    "auto_sync_enabled": body.auto_sync_enabled,
                    "auto_sync_interval_seconds": body.auto_sync_interval_seconds,
                },
            )
            feed = await sheet_sync.sheet_sync_service.upsert_google_sheet_feed(
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
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="create"
            )
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            # A sync spends GOOGLE's per-project Sheets read quota, which every
            # workspace's feed draws from and which our own headroom cannot
            # replace: exhaust it and nobody's sheet syncs until the window rolls.
            await quota.charge(user, "tournament.sheet_sync", workspace_id=ws_id)
            # sync_google_sheet_feed commits internally (including on its error
            # paths), so the row is staged before it — which is also why it carries
            # no counts: those only exist once that commit has already happened.
            await record_admin_audit(
                session,
                action="registration.sheet_sync",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="tournament",
                entity_id=tournament_id,
            )
            result = await sheet_sync.sheet_sync_service.sync_google_sheet_feed(session, tournament_id)
            if result.locked:
                # The scheduler (or another "Sync now") holds this feed: nothing was applied, so an
                # empty success would read as an empty sheet.
                raise HTTPException(status_code=409, detail="A sync of this sheet is already running")
            return _dump(
                schemas.BalancerGoogleSheetFeedSyncResponse(
                    created=result.created,
                    updated=result.updated,
                    withdrawn=result.withdrawn,
                    total=result.total,
                    skipped=result.skipped,
                    errors=[schemas.MappingPreviewFieldError(**error) for error in result.errors],
                    feed=serialize_feed(result.feed),
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sheet_mapping_catalog")
    async def _sheet_mapping_catalog(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="read"
            )
            include_headers = _q1(data, "include_headers", _bool, default=False)
            catalog = await sheet_sync.sheet_sync_service.get_mapping_catalog(
                session, tournament_id, include_headers=include_headers
            )
            return _dump(schemas.BalancerGoogleSheetMappingCatalogResponse(**catalog))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sheet_suggest_mapping")
    async def _sheet_suggest_mapping(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="read"
            )
            body = schemas.BalancerGoogleSheetMappingSuggestRequest.model_validate(_payload(data))
            _, headers, mapping = await sheet_sync.sheet_sync_service.suggest_google_sheet_mapping(
                session, tournament_id, source_url=body.source_url
            )
            return _dump(
                schemas.BalancerGoogleSheetMappingSuggestResponse(
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
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="team", action="read"
            )
            body = schemas.BalancerGoogleSheetMappingPreviewRequest.model_validate(_payload(data))
            preview = await sheet_sync.sheet_sync_service.preview_google_sheet_mapping(
                session,
                tournament_id,
                source_url=body.source_url,
                mapping_config_json=body.mapping_config_json,
                value_mapping_json=body.value_mapping_json,
                sample_rows=body.sample_rows,
            )
            return _dump(schemas.BalancerGoogleSheetMappingPreviewResponse(**preview))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.sheet_players_export")
    async def _sheet_players_export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            tournament_id = _require_id(data)
            await auth.require_tournament_id_permission(
                session, user, tournament_id=tournament_id, resource="player", action="read"
            )
            export_format = _q1(data, "format") or PLAYER_EXPORT_DEFAULT_FORMAT
            if export_format not in PLAYER_EXPORT_FORMATS:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unknown export format {export_format!r}; expected one of {', '.join(PLAYER_EXPORT_FORMATS)}",
                )
            ws_id = await auth.get_tournament_workspace_id(session, tournament_id)
            # The one metered subject here whose cost is ours, not a third party's:
            # it materializes the WHOLE pool — every roster, and under ``owt-1``
            # every player's rank sources, divisions and top heroes — so a polling
            # client replays the balancer job's heaviest read on every call.
            # Charged after the format check so a malformed request costs nothing.
            await quota.charge(user, "tournament.sheet_players_export", workspace_id=ws_id)
            payload = await player_export_service.export(
                session,
                tournament_id,
                export_format=export_format,
                include_private=bool(_q1(data, "include_private", _bool, default=False)),
            )
            return _dump(schemas.BalancerPlayerExportResponse(**payload))

        return await _run(logger, op)

    # ══ Division grids (PUBLIC — NOT under /admin) ════════════════════════════
    #
    # Auth split: every division-grid subject requires an authenticated user.
    # The two "open" reads (get_version, get_mapping) need no workspace
    # permission; the rest enforce division_grid.<action> via
    # require_workspace_permission.
    #
    # 403 vs 404, one rule for every handler: a route naming a workspace checks
    # division_grid.<action> there first (403). Any id the caller cannot see —
    # missing, another workspace's private grid/version/job, or a row outside the
    # path's workspace — is 404, so ids cannot be probed across workspaces. A
    # route naming only a grid/version checks it is visible (404) before the
    # permission on its workspace (403). A system grid (no workspace) is read
    # by anyone through the two open reads (grid_version_get, grid_mapping_get)
    # and copied with grid_workspace_create(from_version_id); the workspace-
    # scoped reads (grid_versions_list, grid_portable_export) need a permission
    # on the grid's workspace, which a system grid has none of: they refuse it
    # (403; a superuser or global grant passes the check and finds no workspace, 404).
    # It is writable by none: every write to it, its versions or tiers, and a
    # mapping FROM one of its versions, is 403 ``division_grid_read_only``
    # (``require_writable``). A workspace's own rows that point at it stay
    # allowed: activating a system version as the workspace default, and a
    # mapping from the workspace's own version onto a system version (a mapping
    # belongs to its source version's workspace).

    @broker.subscriber("rpc.tournament.grid_workspace_list")
    async def _grid_workspace_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await require_workspace_permission(workspace_id, session=session, user=user, action="read")
            grids = await division_grid_service.get_workspace_grids(session, workspace_id)
            counts = await division_grid_service.get_grid_tournament_counts(session, workspace_id)
            return [
                _dump(
                    schemas.DivisionGridRead.model_validate(grid, from_attributes=True).model_copy(
                        update={"tournament_count": counts.get(grid.id, 0)}
                    )
                )
                for grid in grids
            ]

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_workspace_create")
    async def _grid_workspace_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await require_workspace_permission(workspace_id, session=session, user=user, action="create")
            body = schemas.DivisionGridCreate.model_validate(_payload(data))
            grid = await division_grid_service.create_grid(session, workspace_id, body)
            await record_admin_audit(
                session,
                action="division_grid.create",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="division_grid",
                entity_id=grid.id,
                entity_label=grid.name,
                after={"slug": grid.slug, "name": grid.name, "description": grid.description},
            )
            await session.commit()
            return _dump(schemas.DivisionGridRead.model_validate(grid, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_update")
    async def _grid_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            grid_id = _require_id(data)
            grid = await division_grid_service.get_grid_by_id(session, grid_id)
            _require_grid_read_access(user, grid)
            body = schemas.DivisionGridUpdate.model_validate(_payload(data))
            action = "delete" if body.archived is True else "update"
            await require_workspace_permission(grid.workspace_id, session=session, user=user, action=action)
            before = {"name": grid.name, "archived": grid.archived_at is not None}
            updated = await division_grid_service.update_grid(session, grid_id=grid_id, data=body)
            await record_admin_audit(
                session,
                action="division_grid.update",
                actor=user,
                data=data,
                workspace_id=grid.workspace_id,
                entity_type="division_grid",
                entity_id=grid_id,
                entity_label=updated.name,
                before=before,
                after={"name": updated.name, "archived": updated.archived_at is not None},
            )
            await session.commit()
            return _dump(schemas.DivisionGridRead.model_validate(updated, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_delete")
    async def _grid_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            grid_id = _require_id(data)
            grid = await division_grid_service.get_grid_by_id(session, grid_id)
            _require_grid_read_access(user, grid)
            await require_workspace_permission(grid.workspace_id, session=session, user=user, action="delete")
            force = _q1(data, "force", _bool, default=False)
            ws_id, grid_name = grid.workspace_id, grid.name
            await division_grid_service.delete_grid(session, grid_id, force=force)
            await record_admin_audit(
                session,
                action="division_grid.delete",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="division_grid",
                entity_id=grid_id,
                entity_label=grid_name,
                before={"name": grid_name},
                after={"force": force},
            )
            await session.commit()
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_portable_export")
    async def _grid_portable_export(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            grid_id = _require_id(data)
            grid = await division_grid_service.get_grid_by_id(session, grid_id)
            _require_grid_read_access(user, grid)
            await require_workspace_permission(grid.workspace_id, session=session, user=user, action="read")
            return _dump(
                await division_grid_portable.portable_service.export_portable_document(session, grid_id=grid_id)
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_portable_import")
    async def _grid_portable_import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await require_workspace_permission(workspace_id, session=session, user=user, action="create")
            body = schemas.DivisionGridPortableImportRequest.model_validate(_payload(data))
            grid = await division_grid_portable.portable_service.import_portable_document(
                session,
                workspace_id=workspace_id,
                request=body,
            )
            await record_admin_audit(
                session,
                action="division_grid.import",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="division_grid",
                entity_id=grid.id,
                entity_label=grid.name,
                after={
                    "mode": body.mode,
                    "slug": body.document.slug,
                    "version_count": len(body.document.versions),
                },
            )
            await session.commit()
            return _dump(schemas.DivisionGridRead.model_validate(grid, from_attributes=True))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_marketplace_workspaces")
    async def _grid_marketplace_workspaces(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await require_workspace_permission(workspace_id, session=session, user=user, action="read")
            return _dump(
                await division_grid_marketplace.marketplace_service.list_marketplace_workspaces(
                    session, target_workspace_id=workspace_id, user=user
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_marketplace_grids")
    async def _grid_marketplace_grids(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await require_workspace_permission(workspace_id, session=session, user=user, action="read")
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
                await division_grid_marketplace.marketplace_service.list_marketplace_grids(
                    session, source_workspace_id=source_workspace.id
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_marketplace_preflight")
    async def _grid_marketplace_preflight(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await require_workspace_permission(workspace_id, session=session, user=user, action="create")
            body = schemas.DivisionGridMarketplaceImportRequest.model_validate(_payload(data))
            source_workspace = await _get_source_workspace_or_404(
                session,
                target_workspace_id=workspace_id,
                source_workspace_id=body.source_workspace_id,
                user=user,
            )
            source_grids = await division_grid_marketplace.marketplace_service.get_marketplace_grids_by_ids(
                session,
                source_workspace_id=source_workspace.id,
                source_grid_ids=[body.source_grid_id],
            )
            s3 = await get_s3()
            return _dump(
                await division_grid_marketplace.marketplace_service.preflight_division_grid_import(
                    session,
                    public_url=getattr(s3, "_public_url", None),
                    target_workspace_id=workspace_id,
                    source_workspace=source_workspace,
                    source_grids=source_grids,
                    source_version_id=body.source_version_id,
                    include_icons=body.include_icons,
                    include_native_rank_mappings=body.include_native_rank_mappings,
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_marketplace_import")
    async def _grid_marketplace_import(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await require_workspace_permission(workspace_id, session=session, user=user, action="create")
            body = schemas.DivisionGridMarketplaceImportRequest.model_validate(_payload(data))
            source_workspace = await _get_source_workspace_or_404(
                session,
                target_workspace_id=workspace_id,
                source_workspace_id=body.source_workspace_id,
                user=user,
            )
            source_grids = await division_grid_marketplace.marketplace_service.get_marketplace_grids_by_ids(
                session,
                source_workspace_id=source_workspace.id,
                source_grid_ids=[body.source_grid_id],
            )
            s3 = await get_s3()
            preflight = await division_grid_marketplace.marketplace_service.preflight_division_grid_import(
                session,
                public_url=getattr(s3, "_public_url", None),
                target_workspace_id=workspace_id,
                source_workspace=source_workspace,
                source_grids=source_grids,
                source_version_id=body.source_version_id,
                include_icons=body.include_icons,
                include_native_rank_mappings=body.include_native_rank_mappings,
            )
            job = await division_grid_import_jobs.import_jobs_service.create_import_job(
                session,
                workspace_id=workspace_id,
                source_workspace_id=source_workspace.id,
                requested_by_user_id=user.id,
                source_grid_id=body.source_grid_id,
                source_version_id=body.source_version_id,
                include_icons=body.include_icons,
                include_native_rank_mappings=body.include_native_rank_mappings,
                source_fingerprint=preflight.source_fingerprint,
            )
            await record_admin_audit(
                session,
                action="division_grid.import",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="division_grid",
                entity_id=body.source_grid_id,
                after={
                    "job_id": job.id,
                    "source_workspace_id": source_workspace.id,
                    "source_version_id": body.source_version_id,
                    "include_icons": body.include_icons,
                    "include_native_rank_mappings": body.include_native_rank_mappings,
                },
            )
            await session.commit()
            return _dump(division_grid_import_jobs.to_read(job))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_import_jobs_list")
    async def _grid_import_jobs_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await require_workspace_permission(workspace_id, session=session, user=user, action="read")
            jobs = await division_grid_import_jobs.import_jobs_service.list_import_jobs(
                session,
                workspace_id=workspace_id,
                active_only=_q1(data, "active_only", _bool, False),
                limit=_q1(data, "limit", int, 20),
            )
            return _dump([division_grid_import_jobs.to_read(job) for job in jobs])

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_import_job_get")
    async def _grid_import_job_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            await require_workspace_permission(workspace_id, session=session, user=user, action="read")
            job = await division_grid_import_jobs.import_jobs_service.get_import_job(
                session,
                workspace_id=workspace_id,
                job_id=_path_int(data, "job_id"),
            )
            if job is None:
                raise HTTPException(status_code=404, detail="Division grid import job not found")
            return _dump(division_grid_import_jobs.to_read(job))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_versions_list")
    async def _grid_versions_list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            grid_id = _require_id(data)
            grid = await division_grid_service.get_grid_by_id(session, grid_id)
            _require_grid_read_access(user, grid)
            await require_workspace_permission(grid.workspace_id, session=session, user=user, action="read")
            versions = await division_grid_service.get_versions(session, grid.workspace_id, grid_id)
            return [_dump(_version_read(version, grid.discipline)) for version in versions]

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_create")
    async def _grid_version_create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            grid_id = _require_id(data)
            grid = await division_grid_service.get_grid_by_id(session, grid_id)
            _require_grid_read_access(user, grid)
            await require_workspace_permission(grid.workspace_id, session=session, user=user, action="create")
            body = schemas.DivisionGridVersionCreate.model_validate(_payload(data))
            version = await division_grid_service.create_version(session, grid.workspace_id, grid_id, body)
            await record_admin_audit(
                session,
                action="division_grid.version_create",
                actor=user,
                data=data,
                workspace_id=grid.workspace_id,
                entity_type="division_grid",
                entity_id=version.id,
                entity_label=version.label,
                after={
                    "grid_id": grid_id,
                    "label": version.label,
                    "version": version.version,
                    "tier_count": len(body.tiers),
                },
            )
            await session.commit()
            return _dump(_version_read(version))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_get")
    async def _grid_version_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            version_id = _require_id(data)
            version = await division_grid_service.get_version(session, version_id)
            _require_version_read_access(user, version)
            return _dump(_version_read(version))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_update")
    async def _grid_version_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            version_id = _require_id(data)
            version = await division_grid_service.get_version(session, version_id)
            _require_version_read_access(user, version)
            await require_workspace_permission(version.grid.workspace_id, session=session, user=user, action="update")
            body = schemas.DivisionGridVersionUpdate.model_validate(_payload(data))
            before = {"label": version.label, "status": version.status}
            ws_id = version.grid.workspace_id
            version = await division_grid_service.update_version(session, version_id, body)
            await record_admin_audit(
                session,
                action="division_grid.version_update",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="division_grid",
                entity_id=version_id,
                entity_label=version.label,
                before=before,
                after={
                    "label": version.label,
                    "status": version.status,
                    "tier_count": len(body.tiers) if body.tiers is not None else None,
                },
            )
            await session.commit()
            return _dump(_version_read(version))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_delete")
    async def _grid_version_delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            version_id = _require_id(data)
            version = await division_grid_service.get_version(session, version_id)
            _require_version_read_access(user, version)
            await require_workspace_permission(version.grid.workspace_id, session=session, user=user, action="delete")
            ws_id, label, status = version.grid.workspace_id, version.label, version.status
            await division_grid_service.delete_version(session, version_id)
            await record_admin_audit(
                session,
                action="division_grid.version_delete",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="division_grid",
                entity_id=version_id,
                entity_label=label,
                before={"label": label, "status": status},
            )
            await session.commit()
            return None

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_publish")
    async def _grid_version_publish(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            version_id = _require_id(data)
            version = await division_grid_service.get_version(session, version_id)
            _require_version_read_access(user, version)
            await require_workspace_permission(version.grid.workspace_id, session=session, user=user, action="update")
            ws_id = version.grid.workspace_id
            version = await division_grid_service.publish_version(session, version_id)
            await record_admin_audit(
                session,
                action="division_grid.version_publish",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="division_grid",
                entity_id=version_id,
                entity_label=version.label,
                after={"status": version.status, "published_at": version.published_at},
            )
            await session.commit()
            return _dump(_version_read(version))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_readiness")
    async def _grid_version_readiness(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            version_id = _path_int(data, "version_id")
            await require_workspace_permission(workspace_id, session=session, user=user, action="read")
            return _dump(
                await division_grid_service.get_activation_readiness(
                    session,
                    workspace_id=workspace_id,
                    target_version_id=version_id,
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_activate")
    async def _grid_version_activate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            version_id = _path_int(data, "version_id")
            workspace = await require_workspace_permission(
                workspace_id,
                session=session,
                user=user,
                action="update",
            )
            version = await division_grid_service.activate_version(
                session,
                workspace=workspace,
                version_id=version_id,
            )
            await record_admin_audit(
                session,
                action="division_grid.version_activate",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="division_grid",
                entity_id=version_id,
                entity_label=version.label,
                after={"grid_id": version.grid_id, "status": version.status},
            )
            await session.commit()
            return _dump(_version_read(version))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_save")
    async def _grid_save(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            workspace_id = _path_int(data, "workspace_id")
            workspace = await require_workspace_permission(workspace_id, session=session, user=user, action="update")
            body = schemas.DivisionGridSaveRequest.model_validate(_payload(data))
            outcome = await division_grid_service.save_workspace_grid(session, workspace=workspace, data=body)
            await record_admin_audit(
                session,
                action="division_grid.save",
                actor=user,
                data=data,
                workspace_id=workspace_id,
                entity_type="division_grid",
                entity_id=outcome.grid.id,
                entity_label=outcome.grid.name,
                after={
                    "mode": outcome.mode,
                    "active_version_id": outcome.active_version_id,
                    "saved_version_id": outcome.saved_version_id,
                    "tier_count": len(body.tiers),
                },
            )
            await session.commit()
            return _dump(
                schemas.DivisionGridSaveResult(
                    mode=outcome.mode,
                    grid=schemas.DivisionGridRead.model_validate(outcome.grid, from_attributes=True),
                    active_version_id=outcome.active_version_id,
                    saved_version_id=outcome.saved_version_id,
                    readiness=outcome.readiness,
                )
            )

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_version_clone")
    async def _grid_version_clone(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            version_id = _require_id(data)
            version = await division_grid_service.get_version(session, version_id)
            _require_version_read_access(user, version)
            await require_workspace_permission(version.grid.workspace_id, session=session, user=user, action="create")
            ws_id = version.grid.workspace_id
            cloned = await division_grid_service.clone_version(session, version_id)
            await record_admin_audit(
                session,
                action="division_grid.version_clone",
                actor=user,
                data=data,
                workspace_id=ws_id,
                entity_type="division_grid",
                entity_id=cloned.id,
                entity_label=cloned.label,
                after={"source_version_id": version_id, "grid_id": cloned.grid_id, "label": cloned.label},
            )
            await session.commit()
            return _dump(_version_read(cloned))

        return await _run(logger, op)

    @broker.subscriber("rpc.tournament.grid_mapping_get")
    async def _grid_mapping_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = _identity(data)
            source_version_id = _path_int(data, "source_version_id")
            target_version_id = _path_int(data, "target_version_id")
            source_version = await division_grid_service.get_version(session, source_version_id)
            _require_version_read_access(user, source_version)
            target_version = await division_grid_service.get_version(session, target_version_id)
            _require_version_read_access(user, target_version)
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
            _require_version_read_access(user, source_version)
            await require_workspace_permission(
                source_version.grid.workspace_id, session=session, user=user, action="update"
            )
            # The mapping references the target's tier structure — the caller
            # must be able to read the target version (member or system grid),
            # otherwise mapping rows can point into foreign private grids (404).
            target_version = await division_grid_service.get_version(session, target_version_id)
            _require_version_read_access(user, target_version)
            body = schemas.DivisionGridMappingWrite.model_validate(_payload(data))
            mapping = await division_grid_service.upsert_mapping(session, source_version_id, target_version_id, body)
            await record_admin_audit(
                session,
                action="division_grid.mapping_put",
                actor=user,
                data=data,
                workspace_id=source_version.grid.workspace_id,
                entity_type="division_grid",
                entity_id=source_version_id,
                entity_label=body.name,
                after={
                    "target_version_id": target_version_id,
                    "name": body.name,
                    "rule_count": len(body.rules),
                },
            )
            await session.commit()
            return _dump(schemas.DivisionGridMappingRead.model_validate(mapping, from_attributes=True))

        return await _run(logger, op)
