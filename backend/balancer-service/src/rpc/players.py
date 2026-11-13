"""The workspace roster and its rank layers, over typed RPC.

``rpc.balancer.players.{list, upsert, set_ranks, summary, authors}``.
Reads require workspace membership. Writes additionally require a grant:
``upsert`` (creating a roster member) needs workspace ``team.create`` or a mix
host's ``custom_game.create`` -- a host adds whoever is in the lobby right now;
renaming an existing row (``display_name``) stays ``team.create``. The
``workspace`` (canon) layer of ``set_ranks`` needs ``team.update`` -- the same
grants the sibling roster-shaping writes in ``admin.py``/``binary.py`` require.
The ``author`` layer is the exception: it is always the caller's own private
book, so membership alone is enough to write it -- a foreign book is readable
by every member but writable by nobody else regardless of grant.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core import http_status as status
from shared.core import pagination
from shared.core.errors import BaseAPIException as HTTPException
from shared.rpc.identity import ensure_workspace_permission
from src.core import db
from src.rpc import _common as c
from src.schemas import WorkspacePlayerRanksWrite, WorkspacePlayerUpsert
from src.services import workspace_roster
from src.services.players import workspace_players_service

_SF = db.async_session_maker


def _member_id(data: dict[str, Any]) -> int:
    body = c.payload(data)
    raw = body.get(
        "member_id",
        data.get("member_id", body.get("workspace_member_id", data.get("workspace_member_id", data.get("id")))),
    )
    try:
        return int(raw)
    except TypeError, ValueError:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="member_id is required") from None


#: What ``roster_page`` actually matches a search needle against. Reported on the
#: params so a client can explain the result set; the query itself is server-side.
_SEARCH_FIELDS = ("handle", "display_name", "name")


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
    except TypeError, ValueError:
        page = 1
    try:
        per_page = int(first("per_page") or 30)
    except TypeError, ValueError:
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
    except TypeError, ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="author_user_id must be an integer"
        ) from None


def _author_only(data: dict[str, Any]) -> bool:
    """The "My ranks" shortcut: only members the read author has personally corrected."""
    value = _first(data.get("query"), "author_only")
    if value is None or value == "":
        return False
    return str(value).strip().lower() in ("1", "true", "yes")


def _requested_discipline(data: dict[str, Any]) -> str | None:
    """The ``discipline`` query of a read; omitted means the workspace's first enabled discipline.

    Writes never default the game: their bodies require ``discipline``.
    """
    raw = c.q1(data, "discipline")
    return str(raw) if raw else None


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.balancer.players.list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = c.path_int(data, "workspace_id")
            c.require_member(user, workspace_id)
            params = _list_params(data)
            rows, total = await workspace_players_service.page(
                session,
                workspace_id=workspace_id,
                discipline=_requested_discipline(data),
                search=params.query or None,
                page=params.page,
                per_page=params.per_page,
                author_user_id=_author_to_read(data, user.id),
                author_only=_author_only(data),
            )
            return pagination.paginated_dict([row.model_dump(mode="json") for row in rows], total, params)

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
            body = WorkspacePlayerUpsert.model_validate(c.payload(data))
            # A mix host (``custom_game.create``) may add a game identity nobody
            # has registered yet: that is the add-players dialog's whole point.
            # Renaming a shared roster row is still roster management, and
            # enrolling somebody who has an account is member admission.
            can_manage_roster = user.has_workspace_permission(workspace_id, "team", "create")
            if not can_manage_roster:
                ensure_workspace_permission(user, workspace_id, "custom_game", "create")
            if body.display_name is not None and not can_manage_roster:
                ensure_workspace_permission(user, workspace_id, "team", "create")
            member_id, discipline = await workspace_players_service.upsert(
                session,
                workspace_id=workspace_id,
                discipline=body.discipline,
                provider=body.identity.provider,
                handle=body.identity.handle,
                admit_account_holders=user.has_workspace_permission(workspace_id, "workspace_member", "create"),
                display_name=body.display_name,
                actor_user_id=user.id,
            )
            await session.commit()
            # Re-read through the roster query so the answer carries the resolved
            # identity and name, identically shaped to a ``players.list`` row.
            return await workspace_players_service.get(
                session, workspace_id=workspace_id, member_id=member_id, author_user_id=user.id, discipline=discipline
            )

        return await c.envelope(logger, "players.upsert", op, session_factory=_SF)

    @broker.subscriber("rpc.balancer.players.set_ranks")
    async def _set_ranks(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = c.path_int(data, "workspace_id")
            c.require_member(user, workspace_id)
            body = WorkspacePlayerRanksWrite.model_validate(c.payload(data))
            # ``author`` is the caller's own layer, full stop: accepting an
            # author id here would let one member rewrite another's private book.
            is_author_scope = body.scope == "author"
            if not is_author_scope:
                ensure_workspace_permission(user, workspace_id, "team", "update")
            author_user_id = user.id if is_author_scope else None
            ranks = await workspace_players_service.set_ranks(
                session,
                workspace_id=workspace_id,
                discipline=body.discipline,
                workspace_member_id=_member_id(data),
                ranks=body.ranks,
                clear=body.clear,
                author_user_id=author_user_id,
                actor_user_id=user.id,
            )
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
            return {"authors": await workspace_players_service.authors(session, workspace_id=workspace_id)}

        return await c.envelope(logger, "players.authors", op, session_factory=_SF)
