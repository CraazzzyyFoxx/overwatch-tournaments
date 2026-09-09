"""The workspace roster and its rank layers, over typed RPC.

``rpc.balancer.players.{list, upsert, set_ranks, summary, authors}``.
Reads and writes require workspace membership. ``set_ranks`` picks the layer from
the body's ``scope``; the *author* layer is always the caller's own, because a
foreign book is readable by every member but writable by nobody else.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core import http_status as status
from shared.core import pagination
from shared.core.errors import BaseAPIException as HTTPException
from shared.services import workspace_roster
from shared.services.member_rank import member_rank_service
from src.core import db
from src.rpc import _common as c
from src.services.pickup_mix_realtime import emit_pickup_mix_updated

_SF = db.async_session_maker

_SCOPES = ("workspace", "author")


def _ranks_payload(data: dict[str, Any]) -> dict[str, int]:
    body = c.payload(data)
    ranks = body.get("ranks", data.get("ranks")) or {}
    if not isinstance(ranks, dict):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ranks is required")
    try:
        return {str(role): int(value) for role, value in ranks.items()}
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ranks is required") from exc


def _clear_payload(data: dict[str, Any]) -> list[str]:
    """Roles to *delete* from the layer -- which is how inheritance is restored."""
    body = c.payload(data)
    raw = body.get("clear", data.get("clear")) or []
    if not isinstance(raw, list):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="clear must be a list")
    return [str(role) for role in raw]


def _scope(data: dict[str, Any]) -> str:
    body = c.payload(data)
    raw = body.get("scope", data.get("scope")) or "workspace"
    if raw not in _SCOPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"scope must be one of {list(_SCOPES)}"
        )
    return str(raw)


def _member_id(data: dict[str, Any]) -> int:
    body = c.payload(data)
    raw = body.get(
        "member_id",
        data.get("member_id", body.get("workspace_member_id", data.get("workspace_member_id", data.get("id")))),
    )
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="member_id is required") from None


def _dump(member: Any, ranks: dict[str, int], author_ranks: dict[str, int]) -> dict[str, Any]:
    return {
        "member_id": member.member_id,
        "player_id": member.player_id,
        "battle_tag": member.battle_tag,
        "display_name": member.display_name,
        # Whether this member has a linked login identity -- a mix's host/
        # co-host picker excludes anyone without one, since both grants are
        # addressed by `auth.user.id` and a member who has never signed in
        # has none.
        "auth_user_id": member.auth_user_id,
        # Two layers side by side: the workspace canon everyone sees, and the book
        # being read (the caller's own unless ``author_user_id`` asked otherwise).
        # Collapsing them into one map would hide whether a number is inherited.
        "ranks": ranks,
        "author_ranks": author_ranks,
    }


#: What ``roster_page`` actually matches a search needle against. Reported on the
#: params so a client can explain the result set; the query itself is server-side.
_SEARCH_FIELDS = ("battle_tag", "display_name", "name")


def _first(raw: Any, key: str) -> Any:
    """One query value, unwrapping the gateway's ``?a=1&a=2`` list form."""
    value = raw.get(key) if isinstance(raw, dict) else None
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _list_params(data: dict[str, Any]) -> pagination.PaginationSortSearchParams:
    raw = data.get("query")
    if not isinstance(raw, dict):
        raw = {}

    def first(key: str) -> Any:
        return _first(raw, key)

    try:
        page = max(int(first("page") or 1), 1)
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(first("per_page") or 30)
    except (TypeError, ValueError):
        per_page = 30
    per_page = min(max(per_page, 1), 100)
    search = str(first("query") or "").strip()
    return pagination.PaginationSortSearchParams(
        page=page,
        per_page=per_page,
        sort="id",
        query=search,
        fields=list(_SEARCH_FIELDS) if search else [],
    )


def _author_to_read(data: dict[str, Any], actor_user_id: int) -> int:
    """Whose book to *read*, defaulting to the caller's own.

    Any member may look at another host's numbers -- that is how the sheet shows
    "what the host thinks" next to the canon. Writing is a different matter: the
    write path takes its author from the actor and never from the wire.
    """
    value = _first(data.get("query"), "author_user_id")
    if value is None or value == "":
        return actor_user_id
    try:
        return int(value)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="author_user_id must be an integer"
        ) from None


def _author_only(data: dict[str, Any]) -> bool:
    """The "My ranks" shortcut: only members the read author has personally corrected."""
    value = _first(data.get("query"), "author_only")
    if value is None or value == "":
        return False
    return str(value).strip().lower() in ("1", "true", "yes")


def _by_member(layer: dict[tuple[int, str], int]) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    for (member_id, role), value in layer.items():
        out.setdefault(member_id, {})[role] = value
    return out


async def _layers(
    session: Any, workspace_id: int, member_ids: list[int], author_user_id: int
) -> tuple[dict[int, dict[str, int]], dict[int, dict[str, int]]]:
    canon = await member_rank_service.list_layer(session, workspace_id=workspace_id, member_ids=member_ids)
    author = await member_rank_service.list_layer(
        session, workspace_id=workspace_id, member_ids=member_ids, author_user_id=author_user_id
    )
    return _by_member(canon), _by_member(author)


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.balancer.players.list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = c.path_int(data, "workspace_id")
            c.require_member(user, workspace_id)
            params = _list_params(data)
            author_user_id = _author_to_read(data, user.id)
            rows, total = await workspace_roster.roster_page(
                session,
                workspace_id=workspace_id,
                search=params.query or None,
                page=params.page,
                per_page=params.per_page,
                author_user_id=author_user_id,
                author_only=_author_only(data),
            )
            canon, author = await _layers(session, workspace_id, [row.member_id for row in rows], author_user_id)
            return pagination.paginated_dict(
                [_dump(row, canon.get(row.member_id, {}), author.get(row.member_id, {})) for row in rows],
                total,
                params,
            )

        return await c.envelope(logger, "players.list", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.players.summary")
    async def _summary(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = c.path_int(data, "workspace_id")
            c.require_member(user, workspace_id)
            total, author_total = await workspace_roster.roster_summary(
                session, workspace_id=workspace_id, author_user_id=_author_to_read(data, user.id)
            )
            return {"total": total, "author_total": author_total}

        return await c.envelope(logger, "players.summary", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.players.upsert")
    async def _upsert(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = c.path_int(data, "workspace_id")
            c.require_member(user, workspace_id)
            body = c.payload(data)
            battle_tag = body.get("battle_tag", data.get("battle_tag"))
            if not isinstance(battle_tag, str) or not battle_tag.strip():
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="battle_tag is required")
            display_name = body.get("display_name", data.get("display_name"))
            if isinstance(display_name, str):
                display_name = display_name.strip() or None
            elif display_name is not None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="display_name is required")
            member = await workspace_roster.ensure_member_for_battle_tag(
                session,
                workspace_id=workspace_id,
                battle_tag=battle_tag,
                display_name=display_name,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="member", actor_user_id=user.id)
            await session.commit()
            # Re-read through the roster query so the answer carries the resolved
            # BattleTag and name, identically shaped to a ``players.list`` row.
            roster = await workspace_roster.list_roster(session, workspace_id=workspace_id, member_ids=[member.id])
            row = roster.get(member.id)
            if row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace member not found")
            canon, author = await _layers(session, workspace_id, [member.id], user.id)
            return _dump(row, canon.get(member.id, {}), author.get(member.id, {}))

        return await c.envelope(logger, "players.upsert", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.players.set_ranks")
    async def _set_ranks(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = c.path_int(data, "workspace_id")
            c.require_member(user, workspace_id)
            # ``author`` is the caller's own layer, full stop: accepting an
            # author id here would let one member rewrite another's private book.
            author_user_id = user.id if _scope(data) == "author" else None
            # ``set_ranks`` runs ``member_in_workspace`` itself, so a member from
            # another workspace 404s before any row is written.
            ranks = await member_rank_service.set_ranks(
                session,
                workspace_id=workspace_id,
                workspace_member_id=_member_id(data),
                ranks=_ranks_payload(data),
                clear=_clear_payload(data),
                author_user_id=author_user_id,
            )
            await emit_pickup_mix_updated(session, workspace_id, change="rank", actor_user_id=user.id)
            await session.commit()
            return {"ranks": ranks}

        return await c.envelope(logger, "players.set_ranks", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.players.authors")
    async def _authors(data: dict, msg: RabbitMessage) -> dict:
        """Everyone who has personally rank-corrected a member here, busiest
        first -- the add-players dialog's per-author filter chips beyond the
        two fixed ones (workspace canon, caller's own book).
        """

        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = c.path_int(data, "workspace_id")
            c.require_member(user, workspace_id)
            counts = await member_rank_service.list_authors(session, workspace_id=workspace_id)
            names = await workspace_roster.hosts_by_user_id(
                session, workspace_id=workspace_id, user_ids=[author_user_id for author_user_id, _ in counts]
            )
            return {
                "authors": [
                    {"user_id": author_user_id, "display_name": names.get(author_user_id), "count": count}
                    for author_user_id, count in counts
                ]
            }

        return await c.envelope(logger, "players.authors", op, session_factory=_SF)
