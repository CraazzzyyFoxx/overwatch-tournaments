"""Pickup mixes over typed RPC.

``rpc.balancer.custom.{create,list,get,update_roster,update_player,set_participation,
balance,set_team_names,set_role_mask,set_points_per_win,set_balancer_config,
transfer_host,add_co_host,remove_co_host,swap_seats,record_outcome,match_history,
rotation,close,delete,hard_delete}``.

Writes require ``actor`` to be the host or a co-host; the per-mix check lives in
``CustomGameService._writable``. Reads are open to any workspace member. Every
request body is validated by a Pydantic model in ``src.schemas.custom_game``
before it reaches a use case -- nothing here hand-parses a dict.
"""

from __future__ import annotations

from typing import Any, TypeVar

import sqlalchemy as sa
from faststream.rabbit import RabbitMessage
from pydantic import BaseModel, ValidationError

from shared import models
from shared.core import http_status as status
from shared.core.enums import CasualTeamSide, MixRoleSelectionMode
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
from shared.services.division_grid.access import get_effective_division_grid
from shared.services.member_rank import MIX_ORDER
from src.core import db
from src.rpc import _common as c
from src.schemas import custom_game as schemas
from src.services.custom_game import custom_game_service
from src.services.pickup_mix_realtime import emit_pickup_mix_updated

_SF = db.async_session_maker

_Body = TypeVar("_Body", bound=BaseModel)


def _int(data: dict[str, Any], key: str) -> int:
    body = c.payload(data)
    raw = body.get(key, data.get(key))
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} is required") from None


def _opt_int(data: dict[str, Any], key: str) -> int | None:
    body = c.payload(data)
    raw = body.get(key, data.get(key))
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} is required") from None


def _game_id(data: dict[str, Any]) -> int:
    body = c.payload(data)
    raw = body.get("custom_game_id", data.get("custom_game_id", body.get("id", data.get("id"))))
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="custom_game_id is required"
        ) from None


def _body(schema: type[_Body], data: dict[str, Any]) -> _Body:
    """Validate the gateway body, reporting a schema error as a 422.

    One boundary for every write here: an unknown key, a wrong type or a
    string where a boolean belongs is rejected before a use case sees it.
    """
    try:
        return schema.model_validate(c.payload(data))
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=[{"loc": list(error["loc"]), "msg": error["msg"]} for error in exc.errors()],
        ) from exc


def _require_mix(data: dict[str, Any], user: Any, workspace_id: int, action: str) -> None:
    """Reading a mix is open to any workspace member; only ``create`` needs a role grant.

    ``read`` stops at membership -- a workspace member watching a mix without
    running one needs no ``custom_game`` grant of its own. ``create`` is the
    only action still checked against the workspace-level permission: it has
    no existing game to hold a per-game grant, so the ``host``/``admin``/
    ``owner`` role (``custom_game.create``) is the only gate available for
    starting a *new* mix.

    ``update``/``delete`` deliberately skip the coarse workspace permission:
    every mutating use case re-loads the game and re-checks host-or-co-host
    itself (``CustomGameService._writable``), which is the check that actually
    knows about co-hosts. Gating here too used to 403 a co-host who held only
    the plain ``member`` role before that check ever ran.
    """
    c.require_member(user, workspace_id)
    if action != "create":
        return
    c.require_workspace_permission(data, user, workspace_id, "custom_game", action)


def _dump_row(
    row: Any,
    member: Any | None,
    roles: list[str] | None,
    resolved: dict[tuple[int, str], Any],
    author_ranks: dict[tuple[int, str], int],
) -> dict[str, Any]:
    effective = {
        role: resolved[(row.workspace_member_id, role)]
        for role in REGISTRATION_ROLE_CODES
        if resolved.get((row.workspace_member_id, role)) is not None
        and resolved[(row.workspace_member_id, role)].value is not None
    }
    return {
        "id": row.id,
        "workspace_member_id": row.workspace_member_id,
        "display_name": getattr(member, "display_name", None),
        "battle_tag": getattr(member, "battle_tag", None),
        "sort_order": row.sort_order,
        # One field for the whole lineup state: must_play | pool | benched.
        "participation": row.participation,
        # `explicit` means `roles` is the host's own ordered list, empty
        # included; `all_ranked` means it is `null` and every ranked role plays.
        "role_selection_mode": row.role_selection_mode,
        "is_flex": row.is_flex,
        "roles": roles,
        # The ranks balance would actually use: host book > workspace canon > OW.
        "ranks": {role: rank.value for role, rank in effective.items()},
        # Which of those three a value came from, so the sheet can say whether it
        # is showing this host's own number or the workspace's.
        "rank_sources": {role: rank.source for role, rank in effective.items()},
        # This host's own layer, separately: the sheet edits it directly, and
        # without it "my rank" would be indistinguishable from an inherited one.
        "author_ranks": {
            role: author_ranks[(row.workspace_member_id, role)]
            for role in REGISTRATION_ROLE_CODES
            if (row.workspace_member_id, role) in author_ranks
        },
    }


def _dump_settings(
    game: Any,
    team_names: dict[int, str],
    role_mask: dict[str, int],
) -> dict[str, Any]:
    """The mix's own settings, each one a stored fact rather than a config blob."""
    return {
        "points_per_win": game.points_per_win,
        "team_names": {str(index): name for index, name in sorted(team_names.items())},
        "role_mask": role_mask or None,
        "balancer_config": game.balancer_config_json,
    }


def _dump_game(
    game: Any,
    settings: dict[str, Any],
    *,
    roster: list[Any] | None = None,
    members: dict[int, Any] | None = None,
    roles_by_player: dict[int, list[str]] | None = None,
    resolved: dict[tuple[int, str], Any] | None = None,
    author_ranks: dict[tuple[int, str], int] | None = None,
    host_display_name: str | None = None,
    roster_shape: dict[str, Any] | None = None,
    co_hosts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": game.id,
        "workspace_id": game.workspace_id,
        "host_user_id": game.host_user_id,
        "host_display_name": host_display_name,
        # Resolved (user_id + display_name) rather than raw ids, so the access
        # dialog never has to guess a name from a separate roster query.
        "co_hosts": co_hosts or [],
        "name": game.name,
        "status": game.status,
        "settings": settings,
        "balance_result": game.balance_result_json,
        "created_at": game.created_at.isoformat() if game.created_at else None,
        "roster_shape": roster_shape,
    }
    if roster is not None:
        by_id = members or {}
        by_player = roles_by_player or {}
        out["players"] = [
            _dump_row(
                row,
                by_id.get(row.workspace_member_id),
                (by_player.get(row.id, []) if row.role_selection_mode == MixRoleSelectionMode.EXPLICIT else None),
                resolved or {},
                author_ranks or {},
            )
            for row in roster
        ]
    return out


async def _game_settings(session: Any, game: Any) -> dict[str, Any]:
    return _dump_settings(
        game,
        await custom_game_service.team_names.mapping_for_game(session, game.id),
        await custom_game_service.role_slots.mapping_for_game(session, game.id),
    )


async def _with_roster(session: Any, game: Any) -> dict[str, Any]:
    """Roster rows carry the member's name, role order, effective ranks and their source.

    Without the name a client only has member ids and has to guess from a
    separately paginated roster query. Without the source and the host's own
    layer, "2600" could equally be this host's number, the workspace canon or
    an Overwatch snapshot, and the sheet could not say which it is about to
    overwrite.
    """
    settings = await _game_settings(session, game)
    roster_shape = (
        await custom_game_service.roster_shape(session, workspace_id=game.workspace_id, custom_game_id=game.id)
    ).model_dump()
    roster = list(await custom_game_service.roster.list_for_game(session, game.id))
    # One name lookup for every identity on the write side: the host and each
    # co-host are all ``auth.user.id``s, and the lookup is left-joined, so an
    # account that holds a role here without playing still resolves to a name.
    co_host_user_ids = await custom_game_service.co_hosts.user_ids_for_game(session, game.id)
    host_names = await custom_game_service.hosts(session, game.workspace_id, [game.host_user_id, *co_host_user_ids])
    host_display_name = host_names.get(game.host_user_id)
    co_hosts = [{"user_id": user_id, "display_name": host_names.get(user_id)} for user_id in co_host_user_ids]
    if not roster:
        return _dump_game(
            game,
            settings,
            roster=roster,
            host_display_name=host_display_name,
            roster_shape=roster_shape,
            co_hosts=co_hosts,
        )
    member_ids = [row.workspace_member_id for row in roster]
    members = await custom_game_service.members(session, game.workspace_id, member_ids)
    roles_by_player = await custom_game_service.player_roles.roles_for_players(session, [row.id for row in roster])
    layer_rows = await custom_game_service.ranks.list_layer_rows(
        session,
        workspace_id=game.workspace_id,
        member_ids=member_ids,
        author_user_id=game.host_user_id,
    )
    resolved = await custom_game_service.ranks.resolve(
        session,
        workspace_id=game.workspace_id,
        members={member_id: member.player_id for member_id, member in members.items()},
        roles=list(REGISTRATION_ROLE_CODES),
        order=MIX_ORDER,
        author_user_id=game.host_user_id,
        grid=await get_effective_division_grid(session, None),
        layers=layer_rows,
    )
    author_ranks = (
        {}
        if game.host_user_id is None
        else {
            (row.workspace_member_id, row.role): row.rank_value for row in layer_rows if row.author_user_id is not None
        }
    )
    return _dump_game(
        game,
        settings,
        roster=roster,
        members=members,
        roles_by_player=roles_by_player,
        resolved=resolved,
        author_ranks=author_ranks,
        host_display_name=host_display_name,
        roster_shape=roster_shape,
        co_hosts=co_hosts,
    )


def _dump_match(match: Any, map_info: dict[int, tuple[str, str]]) -> dict[str, Any]:
    sides = {team.side: team for team in match.teams}
    home = sides.get(CasualTeamSide.HOME)
    away = sides.get(CasualTeamSide.AWAY)
    home_score = home.score if home is not None else 0
    away_score = away.score if away is not None else 0
    winner = 1 if home_score > away_score else 2 if away_score > home_score else None
    map_name, map_image_path = map_info.get(match.map_id, (None, None)) if match.map_id is not None else (None, None)
    return {
        "id": match.id,
        "home_team_name": home.name if home is not None else None,
        "away_team_name": away.name if away is not None else None,
        "home_score": home_score,
        "away_score": away_score,
        "winner": winner,
        "map_id": match.map_id,
        "map_name": map_name,
        "map_image_path": map_image_path,
        "recorded_by": match.recorded_by,
        "recorded_at": match.created_at.isoformat() if match.created_at else None,
    }


async def _dump_matches(session: Any, matches: list[Any]) -> list[dict[str, Any]]:
    """Bulk-resolves map name + thumbnail in one query instead of one per row."""
    map_ids = {match.map_id for match in matches if match.map_id is not None}
    map_info: dict[int, tuple[str, str]] = {}
    if map_ids:
        rows = await session.execute(
            sa.select(models.Map.id, models.Map.name, models.Map.image_path).where(models.Map.id.in_(map_ids))
        )
        map_info = {row.id: (row.name, row.image_path) for row in rows}
    return [_dump_match(match, map_info) for match in matches]


def _dump_rotation(recommendations: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "workspace_member_id": rec.member_id,
            "status": rec.status.value,
            "reason": rec.reason,
            "consecutive_sat": rec.consecutive_sat,
            "consecutive_played": rec.consecutive_played,
            "games_played": rec.games_played,
        }
        for rec in recommendations
    ]


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.balancer.custom.create")
    async def _create(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "create")
            body = _body(schemas.CustomGameCreate, data)
            game = await custom_game_service.create(
                session,
                workspace_id=workspace_id,
                host_user_id=_opt_int(data, "host_user_id") or user.id,
                name=body.name,
                actor_user_id=user.id,
                # An empty list opens an empty mix; the host fills it from the
                # roster sheet afterwards. There is no pool to default to.
                member_ids=body.member_ids,
                balancer_config=body.balancer_config,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="create", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.create", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "read")
            rows = await custom_game_service.list(session, workspace_id=workspace_id)
            host_names = await custom_game_service.hosts(session, workspace_id, [row.host_user_id for row in rows])
            return [
                _dump_game(
                    row,
                    await _game_settings(session, row),
                    host_display_name=host_names.get(row.host_user_id),
                )
                for row in rows
            ]

        return await c.envelope(logger, "custom.list", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.get")
    async def _get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "read")
            game = await custom_game_service.get(session, workspace_id=workspace_id, custom_game_id=_game_id(data))
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.update_roster")
    async def _update_roster(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameRosterUpdate, data)
            game = await custom_game_service.update_roster(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                member_ids=body.member_ids,
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="roster", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.update_roster", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.update_player")
    async def _update_player(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGamePlayerPatch, data)
            game = await custom_game_service.update_player(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                workspace_member_id=_int(data, "workspace_member_id"),
                patch=body.model_dump(exclude_unset=True),
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="roster", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.update_player", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_participation")
    async def _set_participation(data: dict, msg: RabbitMessage) -> dict:
        """Move several roster rows between lineup states in ONE transaction.

        The rotation-hint button applies a whole verdict at once. Sent as N
        single-row patches it raced on whose response landed last and needed a
        follow-up refetch to converge; one request settles the whole lineup and
        emits one realtime signal.
        """

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGamePlayersParticipationPatch, data)
            game = await custom_game_service.set_participation(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                participation={player.workspace_member_id: player.participation for player in body.players},
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="roster", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_participation", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.balance")
    async def _balance(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            game = await custom_game_service.balance(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="balance", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.balance", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_team_names")
    async def _set_team_names(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameTeamNamesPatch, data)
            game = await custom_game_service.set_team_names(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                team_names=body.team_names,
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="team_names", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_team_names", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_role_mask")
    async def _set_role_mask(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameRoleMaskPatch, data)
            game = await custom_game_service.set_role_mask(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                role_mask=body.role_mask,
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="role_mask", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_role_mask", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_points_per_win")
    async def _set_points_per_win(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGamePointsPerWinPatch, data)
            game = await custom_game_service.set_points_per_win(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                points_per_win=body.points_per_win,
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="points_per_win", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_points_per_win", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_balancer_config")
    async def _set_balancer_config(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameBalancerConfigPatch, data)
            game = await custom_game_service.set_balancer_config(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                balancer_config=body.balancer_config,
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="balancer_config", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_balancer_config", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.transfer_host")
    async def _transfer_host(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameHostTransfer, data)
            game = await custom_game_service.transfer_host(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                new_host_user_id=body.new_host_user_id,
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="host", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.transfer_host", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.add_co_host")
    async def _add_co_host(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameCoHostPatch, data)
            game = await custom_game_service.add_co_host(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                co_host_user_id=body.co_host_user_id,
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="co_hosts", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.add_co_host", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.remove_co_host")
    async def _remove_co_host(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            game = await custom_game_service.remove_co_host(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                # Path parameter, not a body: the route is
                # DELETE .../co-hosts/{co_host_user_id}.
                co_host_user_id=_int(data, "co_host_user_id"),
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="co_hosts", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.remove_co_host", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.swap_seats")
    async def _swap_seats(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameSeatSwap, data)
            game = await custom_game_service.swap_seats(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                variant_index=body.variant_index,
                first_uuid=body.first_uuid,
                second_uuid=body.second_uuid,
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="teams", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.swap_seats", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.record_outcome")
    async def _record_outcome(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameRecordOutcome, data)
            game = await custom_game_service.record_outcome(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                winner=body.outcome.winner,
                variant_index=body.variant_index,
                map_id=body.map_id,
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="outcome", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.record_outcome", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.match_history")
    async def _match_history(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "read")
            matches = await custom_game_service.list_matches(
                session, workspace_id=workspace_id, custom_game_id=_game_id(data)
            )
            return await _dump_matches(session, matches)

        return await c.envelope(logger, "custom.match_history", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.rotation")
    async def _rotation(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "read")
            recommendations = await custom_game_service.rotation(
                session, workspace_id=workspace_id, custom_game_id=_game_id(data)
            )
            return _dump_rotation(recommendations)

        return await c.envelope(logger, "custom.rotation", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.close")
    async def _close(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            game = await custom_game_service.close(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="close", actor_user_id=user.id)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.close", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.delete")
    async def _delete(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "delete")
            game = await custom_game_service.cancel(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                actor_user_id=user.id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="delete", actor_user_id=user.id)
            await session.commit()
            return _dump_game(game, await _game_settings(session, game))

        return await c.envelope(logger, "custom.delete", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.hard_delete")
    async def _hard_delete(data: dict, msg: RabbitMessage) -> dict:
        """Permanently deletes a mix. Workspace admin only -- unlike ``delete``
        (a status flip a host can trigger on their own game) this destroys the
        row and every match it recorded, so it needs more than host-or-co-host.
        """

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            c.require_member(user, workspace_id)
            if not user.is_workspace_admin(workspace_id):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace admin required")
            custom_game_id = _game_id(data)
            await custom_game_service.hard_delete(session, workspace_id=workspace_id, custom_game_id=custom_game_id)
            await emit_pickup_mix_updated(session, workspace_id, change="hard_delete", actor_user_id=user.id)
            await session.commit()
            return {"id": custom_game_id}

        return await c.envelope(logger, "custom.hard_delete", op, session_factory=_SF)
