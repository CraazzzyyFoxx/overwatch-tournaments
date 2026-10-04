"""Config-driven public read engine for app-service reference entities.

hero/map/gamemode/achievement get+list are uniform public reads (no auth, no
owning workspace), so they run through the shared CRUD engine with
``public_read=True`` instead of bespoke subscribers. ``service_get``/``list_fn``
delegate to the existing flows (which own entity-expansion, pagination, search
and caching), so behavior + serialization are identical to the HTTP routes.

Gateway routes set ``data["entity"]`` + ``action`` and hit ``rpc.app.read.get`` /
``rpc.app.read.list`` (see ``src/rpc/reads_generic.py``).
"""

from __future__ import annotations

import typing
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.achievements.achievement import AchievementRule
from shared.repository import GamemodeRepository
from shared.rpc.crud import CrudDispatcher, EntityConfig
from shared.rpc.query import build_query_model
from src import models, schemas
from src.core import db, errors, pagination
from src.rpc import _common as c
from src.services.achievements.service import achievements as achievement_service
from src.services.hero.service import heroes as hero_service
from src.services.map.service import maps as map_service

# Sort-field whitelists mirror the route declarations exactly. The Literal only
# constrains the `sort` field; an out-of-set value raises ValidationError, which
# the engine maps to ``unprocessable`` (same 422 as the HTTP route).
_HERO_SORT = typing.Literal["id", "name", "slug", "similarity:name", "similarity:slug"]
_MAP_SORT = typing.Literal["id", "gamemode_id", "name", "similarity:name"]
_GAMEMODE_SORT = typing.Literal["id", "name", "slug", "similarity:name", "similarity:slug"]
_ACH_SORT = typing.Literal["id", "name", "slug", "rarity", "similarity:name", "similarity:slug"]

_gamemode_repo = GamemodeRepository()


def _entities(data: dict[str, Any]) -> list[str]:
    return c.q(data, "entities") or []


async def _ser(session: AsyncSession, obj: Any) -> Any:
    # service_get hooks return a Pydantic schema (HeroRead/MapRead/...). No
    # response_model_exclude_none anywhere -> exclude_none=False (FastAPI default).
    return obj.model_dump(mode="json")


# --- hero --------------------------------------------------------------------
async def _hero_get(session: AsyncSession, obj_id: int, data: dict[str, Any]) -> Any:
    return await hero_service.get(session, obj_id)


async def _hero_list(session: AsyncSession, data: dict[str, Any]) -> Any:
    qp = build_query_model(pagination.PaginationSortSearchQueryParams[_HERO_SORT], data.get("query"))
    params = pagination.PaginationSortSearchParams.from_query_params(qp)
    return (await hero_service.get_all(session, params)).model_dump(mode="json")


# --- map ---------------------------------------------------------------------
async def _map_get(session: AsyncSession, obj_id: int, data: dict[str, Any]) -> Any:
    return await map_service.get(session, obj_id, _entities(data))


async def _map_list(session: AsyncSession, data: dict[str, Any]) -> Any:
    qp = build_query_model(pagination.PaginationSortSearchQueryParams[_MAP_SORT], data.get("query"))
    params = pagination.PaginationSortSearchParams.from_query_params(qp)
    return (await map_service.get_all(session, params)).model_dump(mode="json")


# --- gamemode ----------------------------------------------------------------
# Gamemode is a pure reference table: no cache, no analytical SQL, no
# transaction, nothing bespoke. Its whole read surface is these three functions
# over `GamemodeRepository`, so it has no service module of its own — a class
# holding only `repo.get` + 404 + schema construction earned nothing.


def _gamemode_read(gamemode: models.Gamemode) -> schemas.GamemodeRead:
    """Spreads ``to_dict()`` rather than enumerating fields, matching the map and
    hero serializers. The enumerated version silently dropped every column added
    after it was written: ``aliases`` fell back to the schema default ``[]``, so
    the admin dialog rendered an empty editor over real data and saving it would
    have wiped the aliases the log parser resolves names through."""
    return schemas.GamemodeRead(**gamemode.to_dict())


async def _gamemode_get(session: AsyncSession, obj_id: int, data: dict[str, Any]) -> Any:
    gamemode = await _gamemode_repo.get_expanded(session, obj_id, _entities(data))
    if gamemode is None:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[errors.ApiExc(code="not_found", msg=f"Gamemode not found with id={obj_id}")],
        )
    return _gamemode_read(gamemode)


async def _gamemode_list(session: AsyncSession, data: dict[str, Any]) -> Any:
    qp = build_query_model(pagination.PaginationSortSearchQueryParams[_GAMEMODE_SORT], data.get("query"))
    params = pagination.PaginationSortSearchParams.from_query_params(qp)
    gamemodes, total = await _gamemode_repo.all(session, params, entities=params.entities)
    return pagination.Paginated(
        total=total,
        per_page=params.per_page,
        page=params.page,
        results=[_gamemode_read(gamemode) for gamemode in gamemodes],
    ).model_dump(mode="json")


async def gamemode_lookup(session: AsyncSession) -> list[schemas.LookupItem]:
    """``(id, name)`` pairs for the admin/filter pickers, name-ordered.

    Public because ``rpc/gamemodes.py`` serves it on its own topic
    (``rpc.app.gamemodes.lookup``), outside the get/list registry below.
    """
    rows = await _gamemode_repo.list_lookup(session)
    return [schemas.LookupItem(id=row.id, name=row.name) for row in rows]


# --- achievement -------------------------------------------------------------
async def _achievement_get(session: AsyncSession, obj_id: int, data: dict[str, Any]) -> Any:
    return await achievement_service.get(session, obj_id, _entities(data))


async def _achievement_list(session: AsyncSession, data: dict[str, Any]) -> Any:
    qp = build_query_model(pagination.PaginationSortQueryParams[_ACH_SORT], data.get("query"))
    params = pagination.PaginationSortParams.from_query_params(qp)
    result = await achievement_service.get_all(session, params, workspace_id=c.q_workspace_id(data))
    return result.model_dump(mode="json")


REGISTRY: dict[str, EntityConfig] = {
    "hero": EntityConfig(
        entity="hero",
        model=models.Hero,
        permission_resource="hero",
        serializer=_ser,
        public_read=True,
        service_get=_hero_get,
        list_fn=_hero_list,
        not_found_detail="Hero not found",
        actions=frozenset({"get", "list"}),
    ),
    "map": EntityConfig(
        entity="map",
        model=models.Map,
        permission_resource="map",
        serializer=_ser,
        public_read=True,
        service_get=_map_get,
        list_fn=_map_list,
        not_found_detail="Map not found",
        actions=frozenset({"get", "list"}),
    ),
    "gamemode": EntityConfig(
        entity="gamemode",
        model=models.Gamemode,
        permission_resource="gamemode",
        serializer=_ser,
        public_read=True,
        service_get=_gamemode_get,
        list_fn=_gamemode_list,
        not_found_detail="Gamemode not found",
        actions=frozenset({"get", "list"}),
    ),
    "achievement": EntityConfig(
        entity="achievement",
        model=AchievementRule,
        permission_resource="achievement",
        serializer=_ser,
        public_read=True,
        service_get=_achievement_get,
        list_fn=_achievement_list,
        not_found_detail="Achievement not found",
        actions=frozenset({"get", "list"}),
    ),
}

dispatcher = CrudDispatcher(REGISTRY, db.async_session_maker)
