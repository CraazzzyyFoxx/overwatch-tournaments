"""Public tournament read methods over typed RPC.

Most reads serialize with ``exclude_none=True``. The gateway provides path
params as ``data["id"]`` and query params as ``data["query"][key] = [values]``.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from faststream.rabbit.annotations import RabbitMessage

from shared.core.enums import PickBanKind
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain import pick_ban_rules as pbr
from shared.repository import TournamentRepository
from shared.rpc.common import q_workspace_id
from shared.rpc.identity import rehydrate_user_optional
from shared.rpc.query import build_query_model
from shared.schemas.discipline_filter import DisciplineFilterQuery
from shared.services.division_grid.access import build_workspace_division_grid_normalizer
from shared.services.division_grid.normalization import DivisionGridNormalizationError
from shared.services.tournament.visibility import ensure_tournament_viewable
from src import schemas
from src.core import db
from src.core.caching import canonical_entities
from src.core.workspace import get_division_grid
from src.rpc._helpers import _bool, _path_int, _q, _q1, _read, _require_id, _require_q1
from src.services import visibility_resolvers
from src.services.admin.stage import stage_service as admin_stage_service
from src.services.encounter import flows as encounter_flows
from src.services.encounter import pick_ban_config
from src.services.standings import flows as standings_flows
from src.services.team import flows as team_flows
from src.services.tournament import flows as tournament_flows


async def _resolve_tournament_id(session: Any, data: dict[str, Any]) -> int:
    """The public ``{id}`` path segment is a legacy numeric id, the current
    slug, or a slug an explicit admin rename retired -- resolve any of them to
    the canonical numeric id everything downstream (cache keys, invalidation,
    visibility gate) still keys on.
    """
    raw = str(data.get("id") or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="id is required")
    tournament_id = await TournamentRepository().resolve_public_id(session, raw)
    if tournament_id is None:
        raise HTTPException(status_code=404, detail="Tournament not found")
    return tournament_id


def _identity_user_id(data: dict[str, Any]) -> int | None:
    identity = data.get("identity") or {}
    raw = identity.get("user_id", identity.get("sub"))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _encounter_params(data: dict[str, Any]) -> schemas.EncounterSearchParams:
    """The browse's params, with the entities its cached reads key on (``canonical_entities``)."""
    params = schemas.EncounterSearchParams.from_query_params(
        build_query_model(schemas.EncounterSearchQueryParams, data.get("query"))
    )
    return replace(params, entities=canonical_entities(params.entities, encounter_flows.READ_ENTITIES))


async def _gate_encounter_board(session: Any, data: dict[str, Any]) -> None:
    """Gate a ``tournament_id``-scoped encounter read BEFORE its cached read: the key carries no visibility, and the
    strips name hidden encounters."""
    tid = _q1(data, "tournament_id", int)
    if tid is not None:
        await ensure_tournament_viewable(session, rehydrate_user_optional(data.get("identity")), tid)


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.tournament.get_tournament")
    async def _get_tournament(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = rehydrate_user_optional(data.get("identity"))
            tournament_id = await _resolve_tournament_id(session, data)
            # Gate BEFORE the cached get_read (cache is keyed without the viewer).
            await ensure_tournament_viewable(session, viewer, tournament_id)
            entities = canonical_entities(_q(data, "entities"), tournament_flows.READ_ENTITIES)
            return await tournament_flows.flows_service.get_read(session, tournament_id, entities)

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.lookup_tournaments")
    async def _lookup(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_flows.flows_service.lookup(
                session,
                workspace_id=q_workspace_id(data),
                is_league=_q1(data, "is_league", _bool),
                # One game's tournaments: absent is every game, a code nobody installed is 422.
                discipline=build_query_model(DisciplineFilterQuery, data.get("query")).discipline,
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.get_stages")
    async def _get_stages(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = rehydrate_user_optional(data.get("identity"))
            await ensure_tournament_viewable(session, viewer, _require_id(data))
            return await tournament_flows.flows_service.get_stages_read(session, _require_id(data))

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.stage_bracket_preview_public")
    async def _stage_bracket_preview_public(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            tournament_id = _require_id(data)
            await ensure_tournament_viewable(session, rehydrate_user_optional(data.get("identity")), tournament_id)
            stage_id = _path_int(data, "stage_id")
            # The gate cleared the tournament in the path, not whichever one owns this stage.
            if await admin_stage_service.get_tournament_id(session, stage_id) != tournament_id:
                raise HTTPException(status_code=404, detail="Stage not found")
            return await admin_stage_service.get_bracket_preview(session, stage_id)

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.get_standings")
    async def _get_standings(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = rehydrate_user_optional(data.get("identity"))
            tournament_id = _require_id(data)
            # Gate BEFORE the cached get_by_tournament (cache is keyed without the viewer).
            await ensure_tournament_viewable(session, viewer, tournament_id)
            entities = canonical_entities(_q(data, "entities"), standings_flows.READ_ENTITIES)
            return await standings_flows.flows_service.get_by_tournament(session, tournament_id, entities)

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.statistics_history")
    async def _statistics_history(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_flows.flows_service.get_history_tournaments(
                session, workspace_id=q_workspace_id(data)
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.statistics_division")
    async def _statistics_division(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # One game's tournaments, its grid and its rated roles: absent is 422, unknown 404.
            discipline = pick_ban_config.installed_discipline(_require_q1(data, "discipline")).code
            workspace_id = q_workspace_id(data)
            fallback_grid = await get_division_grid(session, workspace_id, discipline=discipline)
            normalizer = None
            if workspace_id is not None:
                try:
                    normalizer = await build_workspace_division_grid_normalizer(
                        session, workspace_id, require_complete=False, discipline=discipline
                    )
                except DivisionGridNormalizationError:
                    pass  # fall back to the global grid for all tournaments
            return await tournament_flows.flows_service.get_avg_divisions_tournaments(
                session, discipline, workspace_id=workspace_id, normalizer=normalizer, fallback_grid=fallback_grid
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.statistics_overall")
    async def _statistics_overall(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            return await tournament_flows.flows_service.get_tournaments_overall(
                session, workspace_id=q_workspace_id(data)
            )

        return await _read(logger, op)

    # --- encounters / matches / teams (single reads) ---

    @broker.subscriber("rpc.tournament.get_match")
    async def _get_match(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = rehydrate_user_optional(data.get("identity"))
            match_id = _require_id(data)
            tournament_id = await visibility_resolvers.visibility_resolvers_service.tournament_id_for_match(
                session, match_id
            )
            await ensure_tournament_viewable(session, viewer, tournament_id)
            return await encounter_flows.flows_service.get_match_with_stats(
                session, match_id, _q(data, "entities") or [], workspace_id=q_workspace_id(data)
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.get_match_kill_feed")
    async def _get_match_kill_feed(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = rehydrate_user_optional(data.get("identity"))
            match_id = _require_id(data)
            tournament_id = await visibility_resolvers.visibility_resolvers_service.tournament_id_for_match(
                session, match_id
            )
            await ensure_tournament_viewable(session, viewer, tournament_id)
            return await encounter_flows.flows_service.get_match_kill_feed(
                session, match_id, workspace_id=q_workspace_id(data)
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.get_team")
    async def _get_team(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = rehydrate_user_optional(data.get("identity"))
            team_id = _require_id(data)
            tournament_id = await visibility_resolvers.visibility_resolvers_service.tournament_id_for_team(
                session, team_id
            )
            await ensure_tournament_viewable(session, viewer, tournament_id)
            return await team_flows.flows_service.get_read(session, team_id, _q(data, "entities") or [])

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.get_encounter")
    async def _get_encounter(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = rehydrate_user_optional(data.get("identity"))
            encounter_id = _require_id(data)
            tournament_id = await visibility_resolvers.visibility_resolvers_service.tournament_id_for_encounter(
                session, encounter_id
            )
            await ensure_tournament_viewable(session, viewer, tournament_id)
            return await encounter_flows.flows_service.get_encounter(session, encounter_id, _q(data, "entities") or [])

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.encounters_overview")
    async def _encounters_overview(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            await _gate_encounter_board(session, data)
            # The shared build runs on a session of its own: this one must not sit idle in transaction meanwhile.
            await session.commit()
            return await encounter_flows.flows_service.encounters_overview(
                db.async_session_maker,
                _encounter_params(data),
                workspace_id=q_workspace_id(data),
                viewer_auth_user_id=_identity_user_id(data),
            )

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.encounters_insights")
    async def _encounters_insights(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            await _gate_encounter_board(session, data)
            params = _encounter_params(data)
            return await encounter_flows.flows_service.insights_page(
                session,
                params,
                q_workspace_id(data),
                encounter_flows.scope_viewer(params, _identity_user_id(data)),
            )

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.saved_views")
    async def _saved_views(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user_id = _identity_user_id(data)
            if user_id is None:
                raise HTTPException(status_code=401, detail="Not authenticated")
            return await encounter_flows.flows_service.get_saved_views(
                session, workspace_id=q_workspace_id(data), auth_user_id=user_id
            )

        return await _read(logger, op, exclude_none=True)

    # --- paginated lists ---

    @broker.subscriber("rpc.tournament.list_tournaments")
    async def _list_tournaments(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            qp = build_query_model(schemas.TournamentPaginationSortSearchQueryParams, data.get("query"))
            params = schemas.TournamentPaginationSortSearchParams.from_query_params(qp)
            viewer = rehydrate_user_optional(data.get("identity"))
            return await tournament_flows.flows_service.get_all(session, params, viewer=viewer)

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.tournaments_facets")
    async def _tournaments_facets(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # Through the query MODEL rather than raw `_q1` casts: `status` is an
            # enum, and a bad value has to come back as the same 422 the list
            # subject gives, not a 500 from a bare `ValueError`.
            qp = build_query_model(schemas.TournamentFacetsQueryParams, data.get("query"))
            return await tournament_flows.flows_service.get_facets(
                session,
                viewer=rehydrate_user_optional(data.get("identity")),
                workspace_id=qp.workspace_id,
                status=qp.status,
                is_league=qp.is_league,
                discipline=qp.discipline,
                query=qp.query,
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.list_encounters")
    async def _list_encounters(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            await _gate_encounter_board(session, data)
            # The shared build runs on a session of its own: this one must not sit idle in transaction meanwhile.
            await session.commit()
            return await encounter_flows.flows_service.list_encounters(
                db.async_session_maker,
                _encounter_params(data),
                workspace_id=q_workspace_id(data),
                viewer_auth_user_id=_identity_user_id(data),
            )

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.list_matches")
    async def _list_matches(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = rehydrate_user_optional(data.get("identity"))
            tid = _q1(data, "tournament_id", int)
            if tid is not None:
                await ensure_tournament_viewable(session, viewer, tid)
            qp = build_query_model(schemas.MatchSearchQueryParams, data.get("query"))
            params = schemas.MatchSearchParams.from_query_params(qp)
            return await encounter_flows.flows_service.get_all_matches(
                session, params, workspace_id=q_workspace_id(data)
            )

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.list_teams")
    async def _list_teams(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = rehydrate_user_optional(data.get("identity"))
            tid = _q1(data, "tournament_id", int)
            if tid is not None:
                await ensure_tournament_viewable(session, viewer, tid)
            qp = build_query_model(schemas.TeamFilterQueryParams, data.get("query"))
            params = schemas.TeamFilterParams.from_query_params(qp)
            params = replace(params, entities=canonical_entities(params.entities, team_flows.READ_ENTITIES))
            return await team_flows.flows_service.get_all(session, params, workspace_id=q_workspace_id(data))

        return await _read(logger, op, exclude_none=True)

    @broker.subscriber("rpc.tournament.get_pick_ban_configs")
    async def _get_pick_ban_configs(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            viewer = rehydrate_user_optional(data.get("identity"))
            tournament_id = _require_id(data)
            await ensure_tournament_viewable(session, viewer, tournament_id)
            configs = await pick_ban_config.pick_ban_config_service.list_configs(
                session, tournament_id=tournament_id, kind=PickBanKind.MAP
            )
            return {"configs": [pick_ban_config.serialize_pick_ban_config(config) for config in configs]}

        return await _read(logger, op)

    @broker.subscriber("rpc.tournament.pick_ban_rules_catalog")
    async def _pick_ban_rules_catalog(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            # No tournament, no workspace, no gate: the catalog is the ruleset
            # GRAMMAR (which leaves exist, which params they take, which groups
            # are selectable) plus the presets of ONE game. It describes the
            # engine and that game's vocabulary, not anyone's tournament, and the
            # constructor needs it before a config exists to attach it to. The
            # game is explicit: absent is 422, a code nobody installed is 404
            # ``discipline_not_installed`` (never another game's presets). The
            # only DB read is the map-group vocabulary, which is public catalog
            # data.
            discipline = _require_q1(data, "discipline")
            return pbr.catalog(
                discipline=discipline,
                groups={
                    "hero": await pick_ban_config.group_vocabulary(session, PickBanKind.HERO, discipline),
                    "map": await pick_ban_config.group_vocabulary(session, PickBanKind.MAP, discipline),
                },
            )

        return await _read(logger, op)
