"""The workspace's rank values, flattened, over typed RPC.

``rpc.balancer.ranks.list`` -- one read-only row per rank value across all nine
layers (see ``src/services/rank_overview.py``). Admin-only: it exposes every
author's private book side by side with the canon, so it needs the same
``team.update`` grant that writing the canon does (``players.set_ranks`` scope
``workspace``). There is no write path here at all.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from faststream.rabbit import RabbitMessage

from shared.core import http_status as status
from shared.core import pagination
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
from src.core import db
from src.rpc import _common as c
from src.services.rank_overview import SORTS, RankOverviewFilters, parse_layers, rank_overview_page

_SF = db.async_session_maker

_ORDERS = ("asc", "desc")


def _int(data: dict[str, Any], key: str) -> int | None:
    raw = c.q1(data, key)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be an integer"
        ) from None


def _ints(data: dict[str, Any], key: str) -> tuple[int, ...]:
    raw = c.q(data, key) or []
    try:
        return tuple(int(value) for value in raw if str(value).strip() != "")
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be integers"
        ) from None


def _when(data: dict[str, Any], key: str) -> datetime | None:
    """ISO-8601 instant; naive input is read as UTC, since ``at`` is a timestamptz."""
    raw = c.q1(data, key)
    if raw is None or str(raw).strip() == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{key} must be an ISO-8601 datetime"
        ) from None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _bool(data: dict[str, Any], key: str) -> bool:
    raw = c.q1(data, key)
    return raw is not None and str(raw).strip().lower() in ("1", "true", "yes", "on")


def _filters(data: dict[str, Any]) -> RankOverviewFilters:
    page = _int(data, "page") or 1
    per_page = _int(data, "per_page") or 50
    sort = str(c.q1(data, "sort") or "display_name")
    order = str(c.q1(data, "order") or "asc").lower()
    query = str(c.q1(data, "q") or "").strip()
    return RankOverviewFilters(
        player_id=_int(data, "player_id"),
        query=query or None,
        layers=parse_layers(c.q(data, "layer")),
        author_user_ids=_ints(data, "author_user_id"),
        roles=tuple(role for role in (c.q(data, "role") or []) if role in REGISTRATION_ROLE_CODES),
        rank_min=_int(data, "rank_min"),
        rank_max=_int(data, "rank_max"),
        differs_from_canon=_bool(data, "differs_from_canon"),
        date_from=_when(data, "date_from"),
        date_to=_when(data, "date_to"),
        sort=sort if sort in SORTS else "display_name",
        order=order if order in _ORDERS else "asc",
        page=max(page, 1),
        per_page=min(max(per_page, 1), 200),
    )


def register(broker: Any, logger: Any) -> None:
    @broker.subscriber("rpc.balancer.ranks.list")
    async def _list(data: dict, msg: RabbitMessage) -> dict:
        async def op(session: Any) -> Any:
            user = c.active_actor(data)
            workspace_id = c.path_int(data, "workspace_id")
            c.require_member(user, workspace_id)
            # Same gate as writing the canon: this read puts every author's
            # private book on one screen, which only roster management sees.
            c.require_workspace_permission(data, user, workspace_id, "team", "update")
            filters = _filters(data)
            rows, total = await rank_overview_page(session, workspace_id=workspace_id, filters=filters)
            return pagination.paginated_dict(
                rows, total, pagination.PaginationParams(page=filters.page, per_page=filters.per_page)
            )

        return await c.envelope(logger, "ranks.list", op, session_factory=_SF)
