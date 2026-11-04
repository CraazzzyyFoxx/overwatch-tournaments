"""Public native metadata of the installed disciplines.

Reads declarations and persisted rows only: a capability is the *presence* of a hook on the ``DisciplineSpec``, and no
hook (catalog sync, analytics factory, condition registration, collection handler) is ever called here.
"""

from __future__ import annotations

import dataclasses

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import ApiExc, ApiHTTPException, BaseAPIException
from shared.disciplines import DISCIPLINES, DisciplineSpec
from shared.domain.roles import public_asset_url, public_role_attrs
from shared.domain.team_format import TeamFormat
from shared.models.identity.auth_user import AuthUser
from shared.repository import CatalogRoleRepository, WorkspaceRepository
from shared.schemas.team_format import TeamFormatRead
from src.core import config
from src.schemas.discipline import (
    DisciplineCapabilities,
    DisciplineDescriptor,
    DisciplineMetadata,
    EventTypeRead,
    IngestClientRead,
    LobbyBotRead,
    NativeTierRead,
    OntologyRole,
    RoleDimensionRead,
    StatDefinition,
)

__all__ = ("list_disciplines", "metadata")

#: ``workspace_id=all``: the global view. A missing parameter means the same (the gateway has already filled in a
#: single-workspace credential's scope before it gets here).
_ALL = "all"
_MAX_ID = 2**63 - 1
_roles = CatalogRoleRepository()
_workspaces = WorkspaceRepository()


def _not_found() -> BaseAPIException:
    return BaseAPIException(status_code=404, detail="Workspace not found")


def _scope(raw: str | None) -> int | None:
    """``None`` for the global view, else a workspace id; a non-integer, non-``all`` value is a 422."""
    if raw is None or raw == _ALL:
        return None
    if not (raw.isascii() and raw.isdigit()):
        raise ApiHTTPException(
            status_code=422,
            detail=[ApiExc(code="invalid_workspace_id", msg="workspace_id must be a workspace id or 'all'")],
        )
    digits = raw.lstrip("0")
    # Ids are BigInteger: a longer or larger integer can never name a workspace row, so it reads as the unknown
    # workspace (0 -> the 404 below), never as a malformed value. The length guard keeps ``int`` off absurd inputs.
    value = int(digits or "0") if len(digits) <= 19 else 0
    return value if value <= _MAX_ID else 0


async def _visible_workspace(session: AsyncSession, workspace_id: int, viewer: AuthUser | None) -> models.Workspace:
    """The workspace, or the one 404 an unknown id and a hidden workspace the viewer is not in both get.

    ``workspaces.get`` is public and existence-only; child ontology is not, so a hidden workspace is readable only by
    a superuser or one of its members.
    """
    workspace = await _workspaces.get(session, workspace_id) if workspace_id > 0 else None
    if workspace is None:
        raise _not_found()
    if workspace.is_hidden and not (
        viewer is not None and (viewer.is_superuser or workspace.id in viewer.get_workspace_ids())
    ):
        raise _not_found()
    return workspace


def _descriptor(spec: DisciplineSpec, *, enabled: bool) -> DisciplineDescriptor:
    return DisciplineDescriptor(
        code=spec.code,
        name=spec.name,
        enabled=enabled,
        kinds=dict(spec.kinds),  # type: ignore[arg-type]  # validated against the catalog kinds
        character_classes=list(spec.character_classes),
        identity_provider=spec.identity_provider,
        flex=spec.flex,
        short_name=spec.short_name or spec.name,
        icon=public_asset_url(spec.icon, public_origin=config.settings.s3_public_url),
        ingest_client=(
            IngestClientRead(
                instructions_url=spec.ingest_client.instructions_url,
                installer_url=spec.ingest_client.installer_url,
            )
            if spec.ingest_client is not None
            else None
        ),
        capabilities=DisciplineCapabilities(
            catalog_sync=spec.catalog_sync is not None,
            native_rank_collection="rank.collect" in spec.collection_handlers,
            native_ladder=bool(spec.native_ladder),
            match_fetch=bool(spec.match_fetchers),
            match_search=spec.identity_provider is not None
            and any(kind in spec.match_fetchers for kind in spec.match_searchers),
            lobby_bot=spec.lobby_bot is not None,
            ingest_status=spec.ingest_status is not None,
            log_upload="upload" in spec.ingestors,
            achievement_conditions=spec.achievement_conditions is not None,
            analytics=spec.analytics is not None,
        ),
    )


def _enabled(workspace: models.Workspace | None, code: str) -> bool:
    return True if workspace is None else code in workspace.disciplines_enabled


async def list_disciplines(
    session: AsyncSession, raw_scope: str | None, viewer: AuthUser | None
) -> list[DisciplineDescriptor]:
    """The installed games; for a community, its own games first in its ``disciplines_enabled`` order (spec §2: that
    order is "the first enabled game" and every tie-break), then the rest in installed order."""
    workspace_id = _scope(raw_scope)
    workspace = None if workspace_id is None else await _visible_workspace(session, workspace_id, viewer)
    order = {} if workspace is None else {code: index for index, code in enumerate(workspace.disciplines_enabled)}
    codes = sorted(DISCIPLINES, key=lambda code: order.get(code, len(order)))  # stable: the rest keep installed order
    return [_descriptor(DISCIPLINES[code], enabled=_enabled(workspace, code)) for code in codes]


async def metadata(
    session: AsyncSession, code: str, raw_scope: str | None, viewer: AuthUser | None
) -> DisciplineMetadata:
    # ``discipline(code)`` would answer an unknown code with an empty stand-in; a browsing code must never be accepted.
    spec = DISCIPLINES.get(code)
    if spec is None:
        raise ApiHTTPException(
            status_code=404,
            detail=[ApiExc(code="discipline_not_installed", msg=f"Discipline {code!r} is not installed")],
        )
    workspace_id = _scope(raw_scope)
    workspace = None if workspace_id is None else await _visible_workspace(session, workspace_id, viewer)

    dimensions, roles = await _roles.dictionary(session, discipline=code, workspace_id=workspace_id)
    stat_defs = (
        await session.scalars(
            sa.select(models.StatDef)
            .where(models.StatDef.discipline == code)
            .order_by(models.StatDef.sort_order, models.StatDef.code)
        )
    ).all()
    event_types = (
        await session.scalars(
            sa.select(models.EventType).where(models.EventType.discipline == code).order_by(models.EventType.code)
        )
    ).all()
    presets: list[TeamFormatRead] = []
    if spec.team_format_presets:
        # Presets are checked against the *selection* ontology (active dimensions), not the history dictionary.
        ontology = await _roles.ontology(session, discipline=code, workspace_id=workspace_id)
        presets = [
            TeamFormatRead.from_domain(TeamFormat.from_preset(code, preset), source="preset", ontology=ontology)
            for preset in spec.team_format_presets
        ]
    public_origin = config.settings.s3_public_url
    return DisciplineMetadata(
        discipline=_descriptor(spec, enabled=_enabled(workspace, code)),
        workspace_id=workspace_id,
        dimensions=[
            RoleDimensionRead(
                id=row.id,
                code=row.code,
                name=row.name,
                selection_mode=row.selection_mode,  # type: ignore[arg-type]  # CHECK-constrained
                rated=row.rated,
                active=row.active,
                sort_order=row.sort_order,
            )
            for row in dimensions
        ],
        roles=[
            OntologyRole(
                id=role.id,
                dimension=role.dimension,
                code=role.code,
                name=role.name,
                parent_id=role.parent_id,
                workspace_id=role.workspace_id,
                active=role.active,
                selectable=role.selectable,
                sort_order=role.sort_order,
                attrs=public_role_attrs(role.attrs, public_origin=public_origin),
            )
            for role in roles
        ],
        stat_defs=[
            StatDefinition(
                id=row.id,
                code=row.code,
                name=row.name,
                value_format=row.value_format,  # type: ignore[arg-type]  # projected from a validated declaration
                aggregation=row.aggregation,  # type: ignore[arg-type]  # CHECK-constrained
                group=row.stat_group,
                active=row.active,
                sort_order=row.sort_order,
            )
            for row in stat_defs
        ],
        event_types=[EventTypeRead(id=row.id, code=row.code, name=row.name, active=row.active) for row in event_types],
        team_format_presets=presets,
        lobby_bot=(
            LobbyBotRead(regions=list(spec.lobby_bot.regions), default_region=spec.lobby_bot.default_region)
            if spec.lobby_bot is not None
            else None
        ),
        native_ladder=[
            NativeTierRead(
                **{
                    **dataclasses.asdict(tier),
                    "icon_url": public_asset_url(tier.icon_url, public_origin=public_origin) or tier.icon_url,
                }
            )
            for tier in spec.native_ladder
        ],
    )
