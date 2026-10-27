"""Public statistics reads, workspace-filtered (the player leaderboards span every game unless one is named): one
game's character playtime, leaderboard and maps, the champion/winrate boards and the almanac players table and
records."""

from __future__ import annotations

import typing
from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core import pagination
from shared.rpc.query import build_query_model
from src import schemas
from src.core import db
from src.rpc import _common as c
from src.services.hero.service import heroes as character_service
from src.services.statistics.service import statistics as statistics_service

_SF = db.async_session_maker
_STAT_SORT = typing.Literal["id", "name", "value"]


def register(broker: Any, logger: Any, *, channel: Any) -> None:
    # GET /api/v1/statistics/{discipline}/characters/playtime — one game's character playtime shares.
    @broker.subscriber("rpc.stats.statistics.character_playtime", channel=channel)
    async def _character_playtime(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            discipline = c.require_discipline(data, in_path=True)
            await c.gate_tournament(session, data, c.q1(data, "tournament_id", int))
            qp = build_query_model(schemas.CharacterPlaytimeQueryPaginationParams, data.get("query"))
            return await character_service.get_playtime(
                session,
                schemas.CharacterPlaytimePaginationParams.from_query_params(qp),
                discipline=discipline,
                workspace_id=c.q_workspace_id(data),
            )

        return await c.envelope(logger, "statistics.character_playtime", op, session_factory=_SF)

    # GET /api/v1/statistics/{discipline}/characters/{entity_id}/leaderboard — 404 for another game's character.
    @broker.subscriber("rpc.stats.statistics.character_leaderboard", channel=channel)
    async def _character_leaderboard(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            discipline = c.require_discipline(data, in_path=True)
            await c.gate_tournament(session, data, c.q1(data, "tournament_id", int))
            ws = await c.analytics_context(session, c.q_workspace_scope(data), discipline)
            qp = build_query_model(schemas.CharacterLeaderboardQueryParams, data.get("query"))
            return await character_service.get_hero_leaderboard(
                session,
                discipline=discipline,
                entity_id=c.require_id(data),
                params=schemas.CharacterLeaderboardParams.from_query_params(qp),
                workspace_id=ws.id,
                grid=ws.grid,
            )

        return await c.envelope(logger, "statistics.character_leaderboard", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.statistics.champion", channel=channel)
    async def _champion(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(pagination.PaginationSortQueryParams[_STAT_SORT], data.get("query"))
            return await statistics_service.get_most_champions(
                session,
                pagination.PaginationSortParams.from_query_params(qp),
                discipline=c.optional_discipline(data),
                workspace_id=c.q_workspace_id(data),
            )

        return await c.envelope(logger, "statistics.champion", op, session_factory=_SF)

    @broker.subscriber("rpc.stats.statistics.winrate", channel=channel)
    async def _winrate(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(pagination.PaginationSortQueryParams[_STAT_SORT], data.get("query"))
            return await statistics_service.get_to_winrate_players(
                session,
                pagination.PaginationSortParams.from_query_params(qp),
                discipline=c.optional_discipline(data),
                workspace_id=c.q_workspace_id(data),
            )

        return await c.envelope(logger, "statistics.winrate", op, session_factory=_SF)

    # GET /api/v1/statistics/players — the almanac players table (titles, tournaments, maps, win rate).
    @broker.subscriber("rpc.stats.statistics.players", channel=channel)
    async def _players(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await statistics_service.get_players(
                session,
                build_query_model(schemas.PlayerLeaderboardQueryParams, data.get("query")),
                discipline=c.optional_discipline(data),
                workspace_id=c.q_workspace_id(data),
            )

        return await c.envelope(logger, "statistics.players", op, session_factory=_SF)

    # GET /api/v1/statistics/records — all-time records; the parsed-log ones only for one game.
    @broker.subscriber("rpc.stats.statistics.records", channel=channel)
    async def _records(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await statistics_service.get_records(
                session, discipline=c.optional_discipline(data), workspace_id=c.q_workspace_id(data)
            )

        return await c.envelope(logger, "statistics.records", op, session_factory=_SF)

    # GET /api/v1/statistics/{discipline}/maps — one game's maps by mode.
    @broker.subscriber("rpc.stats.statistics.maps", channel=channel)
    async def _maps(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await statistics_service.get_maps(
                session,
                discipline=c.require_discipline(data, in_path=True),
                workspace_id=c.q_workspace_id(data),
            )

        return await c.envelope(logger, "statistics.maps", op, session_factory=_SF)
