"""Pickup mixes over typed RPC.

``rpc.balancer.custom.{create,list,get,rename,update_roster,update_player,set_participation,set_lobby_count,
balance,set_team_names,set_next_map,set_variant_index,
post_discord,post_signup,delete_discord_post,set_voice_channels,voice_options,
transfer_host,add_co_host,remove_co_host,swap_seats,record_outcome,
match_history,undo_match,rotation,stats,close,delete,hard_delete,
self_get,self_current,self_join,self_leave,self_update,set_self_service}``.

Writes require ``actor`` to be the host, a co-host or a superuser; the per-mix check lives in
``CustomGameService._writable``. The reads (``list``, ``get``, ``stats``,
``match_history``, ``rotation``) are public: the gateway forwards no identity
for them (``AuthNone``) and none of them inspects the caller -- a mix board is
read out to a lobby, whose players need no account here.
``hard_delete`` additionally requires workspace admin
(``_require_workspace_admin``). Every request body is validated by a
Pydantic model in ``src.schemas.custom_game`` before it reaches a use case --
nothing here hand-parses a dict.

The six ``self_*`` subjects are the PLAYER's own surface: they are gated by
``mix_self_policy`` inside the service rather than by ``_require_mix``, because
whoever is joining may not be a workspace member yet. ``workspace_id`` is
optional on them -- the bot knows only a ``custom_game_id`` -- and when present
must match the mix's own. ``self_current`` is the exception that requires it:
it answers for the workspace's newest open mix, which is the only input it has.

Every Discord message this service sends is a ``discord_message`` row
(``shared.services.discord_messages``) filed under the mix's subject
(``mix:<id>``): the signup card in slot ``signup``, one row per lineup in slot
``lineup:<lobby>:<match>``. The mix page reads them back as ``discord_posts``,
the host takes one down with ``delete_discord_post``, and deleting the mix
deletes all of them. Commands for the bot are queued through the outbox
(``discord_messages.enqueue``) INSIDE the handler's transaction, so a rolled
back write queues nothing. Keeping the live signup card in step with a
mutation is nobody's job here: every write emits ``emit_pickup_mix_changed``
and ``src.services.mix_signup_projector`` re-renders the card from the
committed state. The bot answers nothing back here -- it writes the row's
outcome itself -- so this module subscribes to no queue but its own RPC
subjects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, TypeVar

import sqlalchemy as sa
from faststream.rabbit import RabbitMessage
from pydantic import BaseModel, ValidationError

from shared import models
from shared.core import http_status as status
from shared.core.enums import CasualTeamSide, MixRoleSelectionMode
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
from shared.services import discord_messages
from shared.services.discord_client import DiscordClient
from shared.services.division_grid.access import get_effective_division_grid
from shared.services.member_rank import MIX_ORDER
from src.core import db
from src.core.config import config
from src.domain.balancer.result_serializer import as_lobby_document
from src.domain.mix_lobbies import seated_member_ids
from src.domain.mix_voice import snowflake
from src.rpc import _common as c
from src.schemas import custom_game as schemas
from src.services.custom_game import custom_game_service, mix_subject
from src.services.pickup_mix_realtime import emit_pickup_mix_changed

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


def _opt_snowflake(value: str | None) -> int | None:
    return int(value) if value is not None else None


#: Moving people waits on Discord's per-member rate limit: seconds, not milliseconds.
_VOICE_RPC_TIMEOUT = 30.0


def _voice_discord(broker: Any) -> DiscordClient:
    """discord-service only: voice lives in the bot's cache, and this service holds no bot token."""
    return DiscordClient(broker=broker, rpc_timeout=_VOICE_RPC_TIMEOUT)


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
    """A write stops at workspace membership; only ``create`` needs a role grant.

    Reads never come through here: a mix board is public (see the module
    docstring), so there is no membership question to ask on the way in.

    ``create`` is the only action still checked against the workspace-level
    permission: it has no existing game to hold a per-game grant, so the
    ``host``/``admin``/``owner`` role (``custom_game.create``) is the only gate
    available for starting a *new* mix.

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


def _require_workspace_admin(user: Any, workspace_id: int) -> None:
    """Workspace admin (or superuser), on top of the membership ``_require_mix`` settles.

    One write needs more than the host-or-co-host grant every other mix write
    checks: ``hard_delete``, which destroys the mix row and every match it ever
    recorded.
    """
    if not user.is_workspace_admin(workspace_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Workspace admin required")


def _dump_row(
    row: Any,
    member: Any | None,
    roles: list[str] | None,
    resolved: dict[tuple[int, str], Any],
    author_ranks: dict[tuple[int, str], int],
    current_lobby: int | None = None,
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
        # Where this player is right now, derived from the lobbies' selected
        # options: ``null`` means waiting for a seat. The host's pin is a
        # separate, durable wish the next balance honours.
        "current_lobby": current_lobby,
        "lobby_pin": row.lobby_pin,
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
    team_names: dict[int, str],
    points_per_win: int,
    workspace_discord_channel_id: int | None,
) -> dict[str, Any]:
    """The mix's own settings, each one a stored fact rather than a config blob.

    Only ``team_names`` is actually the mix's. The other two are resolved
    read-onlys the board would otherwise have to fetch from two more endpoints:
    the host's points knob (``balancer.user_config``, rendered on the win
    buttons as "+50") and the workspace's Discord channel (whose editor lives in
    the workspace admin panel). Neither is writable through a mix.
    """
    return {
        # 0 means the host turned rank adjustment off; the wire says so with the
        # number rather than a null, since every renderer wants an integer.
        "points_per_win": points_per_win,
        "team_names": {str(index): name for index, name in sorted(team_names.items())},
        # A Discord snowflake as a string: it outgrows a JavaScript safe
        # integer, so the wire never carries it as a number.
        "workspace_discord_channel_id": (
            str(workspace_discord_channel_id) if workspace_discord_channel_id is not None else None
        ),
    }


def _dump_lobby(lobby: Any, *, balance_result: bool, activity: tuple[int, Any] | None = None) -> dict[str, Any]:
    """One lobby: its pager, its rolled map, when it was last balanced -- and,
    in the detail read, its own matchup and match count.

    ``balance_result`` is detail-only -- the solver document grows with every
    stored option and no list row renders it. ``lineup_recorded`` is false while
    a balanced lineup has not been played: the UI asks for confirmation before
    anything that would overwrite it.
    """
    out: dict[str, Any] = {
        "lobby_index": lobby.lobby_index,
        "selected_variant_index": lobby.selected_variant_index,
        "next_map_id": lobby.next_map_id,
        "balanced_at": lobby.balanced_at.isoformat() if lobby.balanced_at else None,
        # Carried by the list read too: the page greys out a voice another
        # lobby of the same mix already took.
        "team1_voice_channel_id": snowflake(lobby.team1_voice_channel_id),
        "team2_voice_channel_id": snowflake(lobby.team2_voice_channel_id),
    }
    if balance_result:
        matches_count, last_match_at = activity if activity is not None else (0, None)
        out["balance_result"] = as_lobby_document(lobby.balance_result_json)
        out["matches_count"] = matches_count
        out["lineup_recorded"] = lobby.balanced_at is None or (
            last_match_at is not None and last_match_at >= lobby.balanced_at
        )
    return out


async def _discord_posts(session: Any, game: Any, discord_guild_id: str | None) -> list[dict[str, Any]]:
    """Every Discord message this mix still has out there, oldest first.

    One read of ``discord_message`` by subject. ``deleted`` rows are left out --
    the message is gone and the row only survives as the bot's receipt -- while
    a ``deleting`` one stays visible until the bot confirms, so the button the
    host just pressed does not make the post flicker out and back.

    ``status`` is the effective one: a ``pending`` older than the command
    queue's TTL reads ``lost``, because nothing is going to post it now. The
    jump link needs the workspace's verified guild, so without one a posted
    message is still a post -- just not an addressable one.
    """
    rows = await discord_messages.repository.for_subject(
        session, mix_subject(game.id), statuses=("pending", "posted", "failed", "deleting")
    )
    return [
        {
            "id": row.id,
            "slot": row.slot,
            "kind": row.kind,
            "status": discord_messages.effective_status(row),
            "url": discord_messages.jump_url(row, guild_id=discord_guild_id),
            "error": row.error,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


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
    activity: tuple[int, Any] | None = None,
    lobbies: list[Any] | None = None,
    lobby_activity: dict[int, tuple[int, Any]] | None = None,
    current_lobby: dict[int, int] | None = None,
    discord_posts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    matches_count, last_match_at = activity if activity is not None else (0, None)
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
        # How many lobbies this mix runs, and what each of them is showing: the
        # matchup, the pager and the rolled map are per-lobby facts now.
        "lobby_count": game.lobby_count,
        "lobbies": [
            _dump_lobby(
                lobby,
                balance_result=roster is not None,
                activity=(lobby_activity or {}).get(lobby.lobby_index),
            )
            for lobby in (lobbies or [])
        ],
        # Whether players may seat themselves here (closed | pool | benched) and
        # whether a seated one may re-order their own roles. Both are read by the
        # board's host controls and by the player's own panel.
        "self_signup": game.self_signup,
        "self_role_edit": game.self_role_edit,
        # Where "return everyone" sends them: the mix's own general voice.
        "general_voice_channel_id": snowflake(game.general_voice_channel_id),
        # Every Discord message this mix has out there -- the signup card and
        # every lineup -- oldest first. Only the single-mix read pays for the
        # query; a list row carries the empty list rather than a missing key,
        # so one client type covers both reads.
        "discord_posts": discord_posts or [],
        # How busy this mix has been, so the list can say "3 matches, 20m ago"
        # without fetching every mix's history.
        "matches_count": matches_count,
        "last_match_at": last_match_at.isoformat() if last_match_at else None,
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
                (current_lobby or {}).get(row.workspace_member_id),
            )
            for row in roster
        ]
    return out


async def _game_settings(
    session: Any, game: Any, workspace_channel_id: int | None, points_per_win: int
) -> dict[str, Any]:
    """One mix's settings. The list builds the same dict from grouped reads
    (``_list``); this is the single-mix path."""
    return _dump_settings(
        await custom_game_service.team_names.mapping_for_game(session, game.id),
        points_per_win,
        workspace_channel_id,
    )


async def _with_roster(session: Any, game: Any) -> dict[str, Any]:
    """Roster rows carry the member's name, role order, effective ranks and their source.

    Without the name a client only has member ids and has to guess from a
    separately paginated roster query. Without the source and the host's own
    layer, "2600" could equally be this host's number, the workspace canon or
    an Overwatch snapshot, and the sheet could not say which it is about to
    overwrite.
    """
    # One read for both halves of the workspace's Discord binding: the channel
    # the settings carry, and the guild the posts' jump links need.
    channel_id, guild_id = await custom_game_service.workspace_discord_target(session, game.workspace_id)
    discord_posts = await _discord_posts(session, game, guild_id)
    settings = await _game_settings(
        session,
        game,
        channel_id,
        await custom_game_service.host_points_per_win(session, game.host_user_id),
    )
    roster_shape = (
        await custom_game_service.roster_shape(session, workspace_id=game.workspace_id, host_user_id=game.host_user_id)
    ).model_dump()
    roster = list(await custom_game_service.roster.list_for_game(session, game.id))
    # One name lookup for every identity on the write side: the host and each
    # co-host are all ``auth.user.id``s, and the lookup is left-joined, so an
    # account that holds a role here without playing still resolves to a name.
    co_host_user_ids = await custom_game_service.co_hosts.user_ids_for_game(session, game.id)
    host_names = await custom_game_service.hosts(session, game.workspace_id, [game.host_user_id, *co_host_user_ids])
    host_display_name = host_names.get(game.host_user_id)
    co_hosts = [{"user_id": user_id, "display_name": host_names.get(user_id)} for user_id in co_host_user_ids]
    activity = (await custom_game_service.casual_matches.activity_for_games(session, [game.id])).get(game.id)
    lobbies = list(await custom_game_service.lobbies.list_for_game(session, game.id))
    lobby_activity = await custom_game_service.casual_matches.activity_for_lobbies(session, game.id)
    # Derived once, here: the board, the player sheet and the bot all ask the
    # same question, and none of them should re-parse a solver document.
    current_lobby = {
        member_id: lobby.lobby_index
        for lobby in lobbies
        for member_id in seated_member_ids(lobby.balance_result_json, lobby.selected_variant_index)
    }
    if not roster:
        return _dump_game(
            game,
            settings,
            roster=roster,
            host_display_name=host_display_name,
            roster_shape=roster_shape,
            co_hosts=co_hosts,
            activity=activity,
            lobbies=lobbies,
            lobby_activity=lobby_activity,
            current_lobby=current_lobby,
            discord_posts=discord_posts,
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
        activity=activity,
        lobbies=lobbies,
        lobby_activity=lobby_activity,
        current_lobby=current_lobby,
        discord_posts=discord_posts,
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
        # Which lobby played it: the history chips and the per-lobby undo both
        # read this.
        "lobby_index": match.lobby_index,
        "home_team_name": home.name if home is not None else None,
        "away_team_name": away.name if away is not None else None,
        "home_score": home_score,
        "away_score": away_score,
        "winner": winner,
        "map_id": match.map_id,
        "map_name": map_name,
        "map_image_path": map_image_path,
        # What undoing this match would give back, frozen at record time -- the
        # mix's current points_per_win may say something else entirely.
        "points_per_win_applied": match.points_per_win_applied,
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


def _since(data: dict[str, Any]) -> datetime | None:
    """``?since=`` as a datetime -- the stats window, absent meaning all time.

    A query value arrives as a string (the gateway forwards them verbatim), so
    this is the one place it becomes a datetime. A trailing ``Z`` is accepted
    because that is what ``Date.toISOString()`` produces on the client side;
    anything ``fromisoformat`` cannot read is the caller's mistake, not an
    empty window.
    """
    raw = c.q1(data, "since")
    if raw is None or not str(raw).strip():
        return None
    try:
        return datetime.fromisoformat(str(raw).strip().replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="since must be an ISO 8601 datetime"
        ) from None


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
                clone_from_game_id=body.clone_from_game_id,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="create", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.create", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _int(data, "workspace_id")
            rows = await custom_game_service.list(session, workspace_id=workspace_id)
            game_ids = [row.id for row in rows]
            host_names = await custom_game_service.hosts(session, workspace_id, [row.host_user_id for row in rows])
            # One grouped read per per-row column (activity, team names, points
            # knob) instead of a query per mix.
            activity = await custom_game_service.casual_matches.activity_for_games(session, game_ids)
            team_names = await custom_game_service.team_names.mapping_for_games(session, game_ids)
            lobbies_by_game = await custom_game_service.lobbies.list_for_games(session, game_ids)
            # One query for the workspace's channel, for every row: the setting
            # is workspace-wide, so the list pays nothing per mix for carrying
            # it. No guild here -- a list row shows no Discord posts.
            workspace_channel_id = await custom_game_service.workspace_discord_channel_id(session, workspace_id)
            # A workspace's mixes are typically run by a handful of people, so one
            # grouped read beats a per-row lookup of the same few account rows.
            # Absent = knob off = 0.
            points_by_host = await custom_game_service.host_prefs.points_per_win_by_user(
                session, [row.host_user_id for row in rows]
            )
            return [
                _dump_game(
                    row,
                    _dump_settings(
                        team_names.get(row.id, {}), points_by_host.get(row.host_user_id, 0), workspace_channel_id
                    ),
                    host_display_name=host_names.get(row.host_user_id),
                    lobbies=lobbies_by_game.get(row.id, []),
                    activity=activity.get(row.id),
                )
                for row in rows
            ]

        return await c.envelope(logger, "custom.list", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.get")
    async def _get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _int(data, "workspace_id")
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
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="roster", actor_user_id=user.id
            )
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
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="roster", actor_user_id=user.id
            )
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
                actor_is_superuser=user.is_superuser,
            )
            # The card lists the bench apart, so the projector re-renders it.
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="roster", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_participation", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.self_get")
    async def _self_get(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            return await custom_game_service.self_state(
                session,
                custom_game_id=_game_id(data),
                auth_user=user,
                workspace_id=_opt_int(data, "workspace_id"),
            )

        return await c.envelope(logger, "custom.self_get", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.self_current")
    async def _self_current(data: dict, msg: RabbitMessage) -> dict:
        """The caller's seat in whatever mix the workspace is running NOW.

        What ``/mix`` in Discord asks: the player names no id, so the newest
        mix that is not over answers for them. ``not_found`` when there is none.
        """

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            return await custom_game_service.self_current(
                session, workspace_id=_int(data, "workspace_id"), auth_user=user
            )

        return await c.envelope(logger, "custom.self_current", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.self_join")
    async def _self_join(data: dict, msg: RabbitMessage) -> dict:
        """Seat the caller. Not gated by ``_require_mix``: somebody joining a
        workspace's mix for the first time is not a member of it yet -- the
        enrolment is part of what this does."""

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            custom_game_id = _game_id(data)
            state = await custom_game_service.self_join(
                session,
                custom_game_id=custom_game_id,
                auth_user=user,
                workspace_id=_opt_int(data, "workspace_id"),
            )
            await session.commit()
            return state

        return await c.envelope(logger, "custom.self_join", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.self_leave")
    async def _self_leave(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            custom_game_id = _game_id(data)
            state = await custom_game_service.self_leave(
                session,
                custom_game_id=custom_game_id,
                auth_user=user,
                workspace_id=_opt_int(data, "workspace_id"),
            )
            await session.commit()
            return state

        return await c.envelope(logger, "custom.self_leave", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.self_update")
    async def _self_update(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            body = _body(schemas.CustomGameSelfUpdate, data)
            custom_game_id = _game_id(data)
            state = await custom_game_service.self_update(
                session,
                custom_game_id=custom_game_id,
                auth_user=user,
                # exclude_unset keeps "don't touch my roles" apart from
                # "roles: null" (= every ranked role).
                patch=body.model_dump(exclude_unset=True),
                workspace_id=_opt_int(data, "workspace_id"),
            )
            await session.commit()
            return state

        return await c.envelope(logger, "custom.self_update", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_self_service")
    async def _set_self_service(data: dict, msg: RabbitMessage) -> dict:
        """The host's switches, so this one IS an ordinary mix write: membership
        plus host-or-co-host in ``_writable``."""

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameSelfServicePatch, data)
            game = await custom_game_service.set_self_service(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                patch=body.model_dump(exclude_unset=True),
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="member", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_self_service", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_lobby_count")
    async def _set_lobby_count(data: dict, msg: RabbitMessage) -> dict:
        """How many lobbies this mix runs (1..6). Shrinking drops the lobbies past
        the new count and the pins that named them -- see ``CustomGameService.set_lobby_count``."""

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameLobbyCountPatch, data)
            game = await custom_game_service.set_lobby_count(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                lobby_count=body.lobby_count,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="lobby", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_lobby_count", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.rename")
    async def _rename(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameRename, data)
            game = await custom_game_service.rename(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                name=body.name,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            # The signup card shows the name, so it re-renders like any other change.
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="name", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.rename", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.balance")
    async def _balance(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameBalanceRequest, data)
            game = await custom_game_service.balance(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                scope=body.scope,
                lobby_index=body.lobby_index,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            # A one-lobby balance benches the overflow, which the card shows.
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="balance", actor_user_id=user.id
            )
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
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="team_names", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_team_names", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_next_map")
    async def _set_next_map(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameNextMapPatch, data)
            game = await custom_game_service.set_next_map(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                lobby_index=body.lobby_index,
                map_id=body.map_id,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="next_map", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_next_map", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_variant_index")
    async def _set_variant_index(data: dict, msg: RabbitMessage) -> dict:
        """Which balance option the mix shows. The pager is the host's, the
        view is everyone's -- see ``CustomGameService.set_variant_index``."""

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameVariantIndexPatch, data)
            game = await custom_game_service.set_variant_index(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                lobby_index=body.lobby_index,
                variant_index=body.variant_index,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="variant_index", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_variant_index", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.post_discord")
    async def _post_discord(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGamePostDiscord, data)
            channel_id, commands = await custom_game_service.discord_lineup(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                lobby_index=body.lobby_index,
                variant_index=body.variant_index,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
                board_url_base=config.public_site_url,
                # The host's screenshot wins when there is one: it is the
                # matchup card they were looking at, crests and all, which no
                # rendered text can be. The card then shows the attachment
                # instead of listing the seats.
                image_b64=body.image_b64,
            )
            # Nothing about the mix itself changed, but the post it is about to
            # make is a row of its own, so the commit is real and the board
            # hears about the new entry in ``discord_posts``.
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=_game_id(data), change="discord", actor_user_id=user.id
            )
            await discord_messages.enqueue(session, commands)
            await session.commit()
            return {"status": "queued", "channel_id": str(channel_id)}

        return await c.envelope(logger, "custom.post_discord", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.set_voice_channels")
    async def _set_voice_channels(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGameVoicePatch, data)
            game = await custom_game_service.set_voice_channels(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                general_voice_channel_id=_opt_snowflake(body.general_voice_channel_id),
                lobbies=[
                    (
                        lobby.lobby_index,
                        _opt_snowflake(lobby.team1_voice_channel_id),
                        _opt_snowflake(lobby.team2_voice_channel_id),
                    )
                    for lobby in body.lobbies
                ],
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="voice", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.set_voice_channels", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.voice_options")
    async def _voice_options(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            return await custom_game_service.voice_options(
                session,
                discord=_voice_discord(broker),
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )

        return await c.envelope(logger, "custom.voice_options", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.post_signup")
    async def _post_signup(data: dict, msg: RabbitMessage) -> dict:
        """Open signup and post the card that announces it, in one click."""

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            body = _body(schemas.CustomGamePostSignup, data)
            channel_id, commands = await custom_game_service.signup_post(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                self_signup=body.self_signup,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
                board_url_base=config.public_site_url,
            )
            # The signup mode is a fact about the mix, so the board refreshes;
            # delivery of the card itself is the bot's problem.
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=_game_id(data), change="member", actor_user_id=user.id
            )
            # Queued in THIS transaction: the outbox ties delivery to the
            # commit, so a failed write announces nothing. The previous card's
            # delete leads, so the channel never holds two cards counting two
            # different rosters.
            await discord_messages.enqueue(session, commands)
            await session.commit()
            return {"status": "queued", "channel_id": str(channel_id)}

        return await c.envelope(logger, "custom.post_signup", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.delete_discord_post")
    async def _delete_discord_post(data: dict, msg: RabbitMessage) -> dict:
        """Take one of this mix's Discord messages down, by its ``discord_posts`` id.

        The host's own undo for a post they did not mean to make. Same grant as
        making one (host, co-host or superuser), and the refreshed mix comes
        back so the page re-renders the list it just changed.
        """

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            game, commands = await custom_game_service.delete_discord_post(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                # Path parameter, not a body: the route is
                # DELETE .../discord/posts/{post_id}.
                post_id=_int(data, "post_id"),
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="discord", actor_user_id=user.id
            )
            await discord_messages.enqueue(session, commands)
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.delete_discord_post", op, session_factory=_SF)

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
                actor_is_superuser=user.is_superuser,
            )
            # The card names the host, so handing the mix over re-renders it.
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="host", actor_user_id=user.id
            )
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
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="co_hosts", actor_user_id=user.id
            )
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
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="co_hosts", actor_user_id=user.id
            )
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
                lobby_index=body.lobby_index,
                variant_index=body.variant_index,
                first_uuid=body.first_uuid,
                second_uuid=body.second_uuid,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="teams", actor_user_id=user.id
            )
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
                lobby_index=body.lobby_index,
                winner=body.outcome.winner,
                variant_index=body.variant_index,
                map_id=body.map_id,
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="outcome", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.record_outcome", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.match_history")
    async def _match_history(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _int(data, "workspace_id")
            matches = await custom_game_service.list_matches(
                session, workspace_id=workspace_id, custom_game_id=_game_id(data)
            )
            return await _dump_matches(session, matches)

        return await c.envelope(logger, "custom.match_history", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.undo_match")
    async def _undo_match(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            _require_mix(data, user, workspace_id, "update")
            game = await custom_game_service.undo_last_match(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                match_id=_int(data, "match_id"),
                actor_user_id=user.id,
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="outcome", actor_user_id=user.id
            )
            await session.commit()
            return await _with_roster(session, game)

        return await c.envelope(logger, "custom.undo_match", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.rotation")
    async def _rotation(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _int(data, "workspace_id")
            recommendations = await custom_game_service.rotation(
                session,
                workspace_id=workspace_id,
                custom_game_id=_game_id(data),
                # Query param: the rotation is a read, and which lobby it ranks
                # for is part of the question, not a body.
                lobby_index=c.q1(data, "lobby_index", int, 0),
            )
            return _dump_rotation(recommendations)

        return await c.envelope(logger, "custom.rotation", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.stats")
    async def _stats(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            workspace_id = _int(data, "workspace_id")
            since = _since(data)
            members = await custom_game_service.mix_stats(session, workspace_id=workspace_id, since=since)
            # The filter is echoed back normalized: the client renders the
            # window it actually got, not the string it happened to send.
            return {"since": since.isoformat() if since is not None else None, "members": members}

        return await c.envelope(logger, "custom.stats", op, session_factory=_SF)

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
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="close", actor_user_id=user.id
            )
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
                actor_is_superuser=user.is_superuser,
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=game.id, change="delete", actor_user_id=user.id
            )
            await session.commit()
            channel_id, guild_id = await custom_game_service.workspace_discord_target(session, workspace_id)
            return _dump_game(
                game,
                await _game_settings(
                    session,
                    game,
                    channel_id,
                    await custom_game_service.host_points_per_win(session, game.host_user_id),
                ),
                lobbies=(await custom_game_service.lobbies.list_for_games(session, [game.id])).get(game.id, []),
                activity=(await custom_game_service.casual_matches.activity_for_games(session, [game.id])).get(game.id),
                discord_posts=await _discord_posts(session, game, guild_id),
            )

        return await c.envelope(logger, "custom.delete", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.custom.hard_delete")
    async def _hard_delete(data: dict, msg: RabbitMessage) -> dict:
        """Permanently deletes a mix. Workspace admin only -- unlike ``delete``
        (a status flip a host can trigger on their own game) this destroys the
        row and every match it recorded, so it needs more than host-or-co-host.

        Its Discord messages go with it: a card advertising a mix that no longer
        exists is worse than no card, so every live one is deleted from the
        channel once the deletion itself has committed.
        """

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = _int(data, "workspace_id")
            c.require_member(user, workspace_id)
            _require_workspace_admin(user, workspace_id)
            custom_game_id = _game_id(data)
            commands = await custom_game_service.hard_delete(
                session, workspace_id=workspace_id, custom_game_id=custom_game_id
            )
            await emit_pickup_mix_changed(
                session, workspace_id, custom_game_id=custom_game_id, change="hard_delete", actor_user_id=user.id
            )
            await discord_messages.enqueue(session, commands)
            await session.commit()
            return {"id": custom_game_id}

        return await c.envelope(logger, "custom.hard_delete", op, session_factory=_SF)
