"""Public tournament read methods over RPC (typed; reuse the existing flows).

Each handler mirrors a public route in ``src/routes/tournament.py`` exactly,
calling the same flow function and serializing with ``exclude_none=True`` to match
the routes' ``response_model_exclude_none``. The gateway provides path params as
``data["id"]`` and query params as ``data["query"][key] = [values]``.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.query import build_query_model
from shared.services.division_grid_access import build_workspace_division_grid_normalizer
from shared.services.division_grid_normalization import DivisionGridNormalizationError
from src import schemas
from src.core.workspace import get_division_grid
from src.rpc._helpers import _bool, _q, _q1, _read, _require_id
from src.services.encounter import flows as encounter_flows
from src.services.standings import flows as standings_flows
from src.services.team import flows as team_flows
from src.services.tournament import flows as tournament_flows


def _identity_user_id(data: dict[str, Any]) -> int | None:
    identity = data.get("identity") or {}
    raw = identity.get("user_id", identity.get("sub"))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.get_tournament")
    async def _get_tournament(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_flows.get_read(session, _require_id(data), _q(data, "entities") or [])

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.lookup_tournaments")
    async def _lookup(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_flows.lookup(
                session,
                workspace_id=_q1(data, "workspace_id", int),
                is_league=_q1(data, "is_league", _bool),
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.get_stages")
    async def _get_stages(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_flows.get_stages_read(session, _require_id(data))

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.get_standings")
    async def _get_standings(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament = await tournament_flows.get(session, _require_id(data), [])
            return await standings_flows.get_by_tournament(session, tournament, _q(data, "entities") or [])

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.statistics_history")
    async def _statistics_history(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_flows.get_history_tournaments(session, workspace_id=_q1(data, "workspace_id", int))

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.statistics_division")
    async def _statistics_division(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _q1(data, "workspace_id", int)
            fallback_grid = await get_division_grid(session, workspace_id)
            normalizer = None
            if workspace_id is not None:
                try:
                    normalizer = await build_workspace_division_grid_normalizer(
                        session, workspace_id, require_complete=False
                    )
                except DivisionGridNormalizationError:
                    pass  # fall back to the global grid for all tournaments
            return await tournament_flows.get_avg_divisions_tournaments(
                session, workspace_id=workspace_id, normalizer=normalizer, fallback_grid=fallback_grid
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.statistics_overall")
    async def _statistics_overall(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_flows.get_tournaments_overall(session, workspace_id=_q1(data, "workspace_id", int))

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.owal_seasons")
    async def _owal_seasons(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_flows.get_owal_seasons(session, workspace_id=_q1(data, "workspace_id", int))

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.owal_results")
    async def _owal_results(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _q1(data, "workspace_id", int)
            season = _q1(data, "season")
            grid = await get_division_grid(session, workspace_id)
            if season:
                return await tournament_flows.get_owal_standings_by_season(
                    session, season, workspace_id=workspace_id, grid=grid
                )
            return await tournament_flows.get_owal_standings(session, workspace_id=workspace_id, grid=grid)

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.owal_stacks")
    async def _owal_stacks(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _q1(data, "workspace_id", int)
            season = _q1(data, "season")
            if not season:
                seasons = await tournament_flows.get_owal_seasons(session, workspace_id=workspace_id)
                season = seasons[0] if seasons else None
            if not season:
                return []
            return await tournament_flows.get_league_player_stacks(session, season, workspace_id=workspace_id)

        return await _read(logger, op)

    # --- encounters / matches / teams (single reads) ---

    @broker.subscriber("rpc.tournament.get_match")
    async def _get_match(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await encounter_flows.get_match_with_stats(
                session, _require_id(data), _q(data, "entities") or [], workspace_id=_q1(data, "workspace_id", int)
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.get_team")
    async def _get_team(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await team_flows.get_read(session, _require_id(data), _q(data, "entities") or [])

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.get_encounter")
    async def _get_encounter(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await encounter_flows.get_encounter(session, _require_id(data), _q(data, "entities") or [])

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.encounters_overview")
    async def _encounters_overview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(schemas.EncounterSearchQueryParams, data.get("query"))
            params = schemas.EncounterSearchParams.from_query_params(qp)
            return await encounter_flows.get_encounters_overview(
                session,
                params,
                workspace_id=_q1(data, "workspace_id", int),
                viewer_auth_user_id=_identity_user_id(data),
            )

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.saved_views")
    async def _saved_views(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user_id = _identity_user_id(data)
            if user_id is None:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return await encounter_flows.get_saved_views(
                session, workspace_id=_q1(data, "workspace_id", int), auth_user_id=user_id
            )

        return await _read(logger, op, exclude_none=True)

    # --- paginated lists ---

    @broker.subscriber("rpc.tournament.list_tournaments")
    async def _list_tournaments(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(schemas.TournamentPaginationSortSearchQueryParams, data.get("query"))
            params = schemas.TournamentPaginationSortSearchParams.from_query_params(qp)
            return await tournament_flows.get_all(session, params)

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.list_encounters")
    async def _list_encounters(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(schemas.EncounterSearchQueryParams, data.get("query"))
            params = schemas.EncounterSearchParams.from_query_params(qp)
            return await encounter_flows.get_all_encounters(
                session,
                params,
                workspace_id=_q1(data, "workspace_id", int),
                viewer_auth_user_id=_identity_user_id(data),
            )

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.list_matches")
    async def _list_matches(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(schemas.MatchSearchQueryParams, data.get("query"))
            params = schemas.MatchSearchParams.from_query_params(qp)
            return await encounter_flows.get_all_matches(session, params, workspace_id=_q1(data, "workspace_id", int))

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.list_teams")
    async def _list_teams(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(schemas.TeamFilterQueryParams, data.get("query"))
            params = schemas.TeamFilterParams.from_query_params(qp)
            return await team_flows.get_all(session, params, workspace_id=_q1(data, "workspace_id", int))

        return await _read(logger, op, exclude_none=True)
