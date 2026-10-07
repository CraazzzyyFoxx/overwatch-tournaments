"""Every rank value a workspace's members hold, as one flat table.

One row = one rank value, long format, no grouping -- a plain ``UNION ALL`` over
the nine places a rank can live (``LAYERS``). The point of the union is that
filtering, sorting, the exact total and the page all run in Postgres: the admin
rank screen is a read over the whole roster's history, which is far too much to
assemble in Python and then slice.

The two *effective* layers are computed here in SQL rather than read from a
table, and they must agree with :meth:`MemberRankService.resolve` -- the resolver
the balancer actually runs on. ``effective_tournament`` is
``TOURNAMENT_ORDER`` without the registration layer (workspace canon, then OW
normalised to the **workspace** grid); ``effective_mix`` is ``MIX_ORDER`` (the
author's book, then the canon, then OW normalised to the **global** grid -- what
mixes use today). ``tests/test_rank_overview.py`` pins that parity.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.social import SocialProvider
from shared.division_grid import DivisionGrid, division_case_expr
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
from shared.models.ranks.overwatch_rank import BattleTagRankState, UserRankSnapshot
from shared.services.division_grid.access import get_effective_division_grid
from shared.services.rank_snapshots import OW_RANK_MAX_AGE

# ``_filters``/``_main_battle_tag`` are the roster's own search predicates and
# primary-BattleTag scalar: what ``q`` matches stays one definition, shared with
# ``rpc.balancer.players.list``.
from shared.services.workspace_roster import _filters as _roster_filters
from shared.services.workspace_roster import _main_battle_tag, hosts_by_user_id

# The layer/sort vocabulary lives in the schemas module so the OpenAPI export
# can name it without importing this query.
from src.schemas.ranks import CURRENT_LAYERS, LAYERS, SORTS

__all__ = ("RankOverviewFilters", "parse_layers", "rank_overview_page")

_AT = sa.DateTime(timezone=True)


@dataclass(frozen=True, slots=True)
class RankOverviewFilters:
    player_id: int | None = None
    query: str | None = None
    layers: tuple[str, ...] = CURRENT_LAYERS
    author_user_ids: tuple[int, ...] = ()
    roles: tuple[str, ...] = ()
    rank_min: int | None = None
    rank_max: int | None = None
    differs_from_canon: bool = False
    date_from: datetime | None = None
    date_to: datetime | None = None
    sort: str = "display_name"
    order: str = "asc"
    page: int = 1
    per_page: int = 50


def _grid_rank_case(ow_rank: sa.ColumnElement[int], grid: DivisionGrid) -> sa.ColumnElement[int]:
    """SQL twin of ``grid.resolve_division_from_ow_rank(ow).rank_min``.

    Same two regimes as the Python helper: once *any* tier carries an explicit
    ``ow_rank_min``/``ow_rank_max`` the admin owns the mapping and an SR outside
    every configured range resolves to nothing; with none configured the raw SR
    is assumed to already live on the grid's own scale and is placed by plain
    ``rank_min``/``rank_max`` containment, which never misses.

    The leading NULL guard is load-bearing: the unconfigured regime ends in an
    ``ELSE`` (nothing is out of range), and the column this wraps is an OUTER
    JOIN miss -- "this member has no OW rank in that role" -- which would
    otherwise fall through to the lowest tier and invent a rank.
    """
    if not grid.tiers:
        return _null(sa.Integer)
    guard: list[tuple[sa.ColumnElement[bool], Any]] = [(ow_rank.is_(None), sa.null())]
    configured = [t for t in grid.tiers if t.ow_rank_min is not None and t.ow_rank_max is not None]
    if configured:
        whens = [
            (
                sa.and_(
                    ow_rank >= min(t.ow_rank_min, t.ow_rank_max),  # type: ignore[type-var]
                    ow_rank <= max(t.ow_rank_min, t.ow_rank_max),  # type: ignore[type-var]
                ),
                t.rank_min,
            )
            for t in configured
        ]
        return sa.case(*guard, *whens, else_=sa.null())
    whens = [
        (
            ow_rank >= t.rank_min if t.rank_max is None else sa.and_(ow_rank >= t.rank_min, ow_rank <= t.rank_max),
            t.rank_min,
        )
        for t in grid.tiers
    ]
    return sa.case(*guard, *whens, else_=grid.tiers[-1].rank_min)


def _null(type_: Any) -> sa.ColumnElement[Any]:
    return sa.cast(sa.null(), type_)


def _at(model: Any) -> sa.ColumnElement[datetime]:
    """``updated_at``, which is NULL until a row is first rewritten."""
    return sa.func.coalesce(model.updated_at, model.created_at)


def _row(
    layer: str,
    members: Any,
    *,
    role: Any,
    rank_value: Any,
    row_id: Any = sa.literal(0),
    author_user_id: Any = None,
    source: Any = None,
    sigma: Any = None,
    delta: Any = None,
    canon_diff: Any = None,
    ow_division: Any = None,
    ow_tier: Any = None,
    context_kind: Any = None,
    context_id: Any = None,
    context_label: Any = None,
    context_team: Any = None,
    context_lobby_index: Any = None,
    at: Any = None,
) -> list[Any]:
    """One branch's column list, in the single order every branch must share."""
    return [
        sa.literal(layer).label("layer"),
        members.c.member_id.label("member_id"),
        members.c.player_id.label("player_id"),
        members.c.display_name.label("display_name"),
        members.c.battle_tag.label("battle_tag"),
        (author_user_id if author_user_id is not None else _null(sa.Integer)).label("author_user_id"),
        sa.cast(role, sa.String).label("role"),
        sa.cast(rank_value, sa.Integer).label("rank_value"),
        (source if source is not None else _null(sa.String)).label("source"),
        (sigma if sigma is not None else _null(sa.Float)).label("sigma"),
        (delta if delta is not None else _null(sa.Integer)).label("delta"),
        (canon_diff if canon_diff is not None else _null(sa.Integer)).label("canon_diff"),
        (ow_division if ow_division is not None else _null(sa.String)).label("ow_division"),
        (ow_tier if ow_tier is not None else _null(sa.Integer)).label("ow_tier"),
        (context_kind if context_kind is not None else _null(sa.String)).label("context_kind"),
        (context_id if context_id is not None else _null(sa.Integer)).label("context_id"),
        (context_label if context_label is not None else _null(sa.String)).label("context_label"),
        (context_team if context_team is not None else _null(sa.String)).label("context_team"),
        (context_lobby_index if context_lobby_index is not None else _null(sa.Integer)).label("context_lobby_index"),
        (at if at is not None else _null(_AT)).label("at"),
        sa.cast(row_id, sa.BigInteger).label("row_id"),
    ]


def _members_cte(workspace_id: int, filters: RankOverviewFilters) -> Any:
    where = _roster_filters(workspace_id, filters.query)
    if filters.player_id is not None:
        where.append(models.WorkspaceMember.player_id == filters.player_id)
    return (
        sa.select(
            models.WorkspaceMember.id.label("member_id"),
            models.WorkspaceMember.player_id.label("player_id"),
            sa.func.coalesce(models.WorkspaceMember.display_name, models.User.name).label("display_name"),
            _main_battle_tag().label("battle_tag"),
        )
        .join(models.User, models.User.id == models.WorkspaceMember.player_id)
        .where(*where)
        .cte("rank_members")
    )


def _ow_latest_cte(members: Any) -> Any:
    """Newest snapshot per (account, role, platform), kept only when still ranked.

    The same recency/ranked rules as ``fetch_latest_ow_ranks_by_account``: the
    *newest* row of a series is what says whether the role has a rank at all, so
    the ranked filter is applied after the pick, not before it.
    """
    snapshot = UserRankSnapshot
    latest = (
        sa.select(
            models.SocialAccount.user_id.label("user_id"),
            snapshot.battle_tag,
            snapshot.platform,
            snapshot.role,
            snapshot.rank_value,
            snapshot.division,
            snapshot.tier,
            snapshot.captured_at,
            snapshot.is_ranked,
            snapshot.id.label("snapshot_id"),
        )
        .select_from(models.SocialAccount)
        .join(BattleTagRankState, BattleTagRankState.social_account_id == models.SocialAccount.id)
        .join(snapshot, snapshot.social_account_id == models.SocialAccount.id)
        .where(
            models.SocialAccount.provider == SocialProvider.BATTLENET,
            models.SocialAccount.user_id.in_(sa.select(members.c.player_id)),
            BattleTagRankState.last_success_at >= sa.func.now() - OW_RANK_MAX_AGE,
            snapshot.role.in_(REGISTRATION_ROLE_CODES),
        )
        .distinct(models.SocialAccount.id, snapshot.role, snapshot.platform)
        .order_by(models.SocialAccount.id, snapshot.role, snapshot.platform, snapshot.captured_at.desc())
        .subquery("rank_ow_series")
    )
    return sa.select(latest).where(latest.c.is_ranked.is_(True), latest.c.rank_value.is_not(None)).cte("rank_ow_latest")


def _branches(
    workspace_id: int,
    filters: RankOverviewFilters,
    members: Any,
    ws_grid: DivisionGrid,
    global_grid: DivisionGrid,
) -> list[Any]:
    wanted = set(filters.layers)
    rank = models.MemberRank
    canon = (
        sa.select(
            rank.workspace_member_id.label("member_id"),
            rank.role,
            rank.rank_value,
            _at(rank).label("at"),
            rank.id.label("row_id"),
        )
        .where(rank.workspace_id == workspace_id, rank.author_user_id.is_(None))
        .cte("rank_canon")
    )
    book = (
        sa.select(
            rank.workspace_member_id.label("member_id"),
            rank.author_user_id,
            rank.role,
            rank.rank_value,
            _at(rank).label("at"),
            rank.id.label("row_id"),
        )
        .where(rank.workspace_id == workspace_id, rank.author_user_id.is_not(None))
        .cte("rank_book")
    )
    roles = sa.values(sa.column("role", sa.String), name="rank_roles").data([(r,) for r in REGISTRATION_ROLE_CODES])

    needs_ow = bool(wanted & {"ow", "effective_tournament", "effective_mix"})
    ow_latest = _ow_latest_cte(members) if needs_ow else None
    ow_best = (
        sa.select(
            ow_latest.c.user_id,
            ow_latest.c.role,
            sa.func.max(ow_latest.c.rank_value).label("rank_value"),
        )
        .group_by(ow_latest.c.user_id, ow_latest.c.role)
        .cte("rank_ow_best")
        if ow_latest is not None
        else None
    )

    out: list[Any] = []

    if "canon" in wanted:
        out.append(
            sa.select(
                *_row(
                    "canon",
                    members,
                    role=canon.c.role,
                    rank_value=canon.c.rank_value,
                    at=canon.c.at,
                    row_id=canon.c.row_id,
                )
            ).join_from(members, canon, canon.c.member_id == members.c.member_id)
        )

    if "author" in wanted:
        out.append(
            sa.select(
                *_row(
                    "author",
                    members,
                    role=book.c.role,
                    rank_value=book.c.rank_value,
                    author_user_id=book.c.author_user_id,
                    canon_diff=book.c.rank_value - canon.c.rank_value,
                    at=book.c.at,
                    row_id=book.c.row_id,
                )
            )
            .join_from(members, book, book.c.member_id == members.c.member_id)
            .outerjoin(canon, sa.and_(canon.c.member_id == members.c.member_id, canon.c.role == book.c.role))
        )

    if "ow" in wanted and ow_latest is not None:
        out.append(
            sa.select(
                *_row(
                    "ow",
                    members,
                    role=ow_latest.c.role,
                    rank_value=ow_latest.c.rank_value,
                    ow_division=ow_latest.c.division,
                    ow_tier=ow_latest.c.tier,
                    context_kind=sa.literal("battle_tag"),
                    context_label=ow_latest.c.battle_tag,
                    context_team=ow_latest.c.platform,
                    at=ow_latest.c.captured_at,
                    row_id=ow_latest.c.snapshot_id,
                )
            ).join_from(members, ow_latest, ow_latest.c.user_id == members.c.player_id)
        )

    if "hidden" in wanted:
        hidden = models.MemberHiddenRating
        out.append(
            sa.select(
                *_row(
                    "hidden",
                    members,
                    role=hidden.role,
                    rank_value=sa.func.round(hidden.mu),
                    sigma=hidden.sigma,
                    at=_at(hidden),
                    row_id=hidden.id,
                )
            ).join_from(members, hidden, hidden.workspace_member_id == members.c.member_id)
        )

    if "effective_tournament" in wanted:
        ow_ws = _grid_rank_case(ow_best.c.rank_value, ws_grid) if ow_best is not None else _null(sa.Integer)
        value = sa.func.coalesce(canon.c.rank_value, ow_ws)
        select = (
            sa.select(
                *_row(
                    "effective_tournament",
                    members,
                    role=roles.c.role,
                    rank_value=value,
                    source=sa.case(
                        (canon.c.rank_value.is_not(None), sa.literal("workspace")),
                        (ow_ws.is_not(None), sa.literal("ow")),
                    ),
                )
            )
            .join_from(members, roles, sa.true())
            .outerjoin(canon, sa.and_(canon.c.member_id == members.c.member_id, canon.c.role == roles.c.role))
        )
        if ow_best is not None:
            select = select.outerjoin(
                ow_best, sa.and_(ow_best.c.user_id == members.c.player_id, ow_best.c.role == roles.c.role)
            )
        out.append(select.where(value.is_not(None)))

    if "effective_mix" in wanted:
        authors = sa.select(book.c.member_id, book.c.author_user_id).distinct().cte("rank_mix_authors")
        mix_book = book.alias("rank_mix_book")
        ow_global = _grid_rank_case(ow_best.c.rank_value, global_grid) if ow_best is not None else _null(sa.Integer)
        value = sa.func.coalesce(mix_book.c.rank_value, canon.c.rank_value, ow_global)
        select = (
            sa.select(
                *_row(
                    "effective_mix",
                    members,
                    role=roles.c.role,
                    rank_value=value,
                    author_user_id=authors.c.author_user_id,
                    source=sa.case(
                        (mix_book.c.rank_value.is_not(None), sa.literal("author")),
                        (canon.c.rank_value.is_not(None), sa.literal("workspace")),
                        (ow_global.is_not(None), sa.literal("ow")),
                    ),
                )
            )
            .join_from(members, authors, authors.c.member_id == members.c.member_id)
            .join(roles, sa.true())
            .outerjoin(
                mix_book,
                sa.and_(
                    mix_book.c.member_id == members.c.member_id,
                    mix_book.c.author_user_id == authors.c.author_user_id,
                    mix_book.c.role == roles.c.role,
                ),
            )
            .outerjoin(canon, sa.and_(canon.c.member_id == members.c.member_id, canon.c.role == roles.c.role))
        )
        if ow_best is not None:
            select = select.outerjoin(
                ow_best, sa.and_(ow_best.c.user_id == members.c.player_id, ow_best.c.role == roles.c.role)
            )
        out.append(select.where(value.is_not(None)))

    if "registration" in wanted:
        registration = models.BalancerRegistration
        role_row = models.BalancerRegistrationRole
        tournament = models.Tournament
        out.append(
            sa.select(
                *_row(
                    "registration",
                    members,
                    role=role_row.role,
                    rank_value=role_row.rank_value,
                    context_kind=sa.literal("tournament"),
                    context_id=tournament.id,
                    context_label=tournament.name,
                    at=_at(role_row),
                    row_id=role_row.id,
                )
            )
            .join_from(members, registration, registration.workspace_member_id == members.c.member_id)
            .join(role_row, role_row.registration_id == registration.id)
            .join(tournament, tournament.id == registration.tournament_id)
            .where(
                registration.deleted_at.is_(None),
                role_row.rank_value.is_not(None),
                tournament.workspace_id == workspace_id,
            )
        )

    if "tournament" in wanted:
        player = models.Player
        team = models.Team
        tournament = models.Tournament
        out.append(
            sa.select(
                *_row(
                    "tournament",
                    members,
                    role=player.role,
                    rank_value=player.rank,
                    context_kind=sa.literal("tournament"),
                    context_id=tournament.id,
                    context_label=tournament.name,
                    context_team=team.name,
                    at=_at(player),
                    row_id=player.id,
                )
            )
            .join_from(members, player, player.workspace_member_id == members.c.member_id)
            .join(team, team.id == player.team_id)
            .join(tournament, tournament.id == player.tournament_id)
            .where(tournament.workspace_id == workspace_id)
        )

    if "casual" in wanted:
        seat = models.CasualPlayer
        side = models.CasualTeam
        match = models.CasualMatch
        game = models.CustomGame
        opponent = orm.aliased(models.CasualTeam, name="rank_casual_opponent")
        points = match.points_per_win_applied
        out.append(
            sa.select(
                *_row(
                    "casual",
                    members,
                    role=seat.role,
                    rank_value=seat.rank,
                    author_user_id=game.host_user_id,
                    delta=sa.func.coalesce(
                        seat.rank_delta_applied,
                        sa.case(
                            (sa.or_(points.is_(None), side.score == opponent.score), sa.null()),
                            (side.score > opponent.score, points),
                            else_=-points,
                        ),
                    ),
                    context_kind=sa.literal("mix"),
                    context_id=game.id,
                    context_label=game.name,
                    context_lobby_index=match.lobby_index,
                    at=match.created_at,
                    row_id=seat.id,
                )
            )
            .join_from(members, seat, seat.workspace_member_id == members.c.member_id)
            .join(side, side.id == seat.team_id)
            .join(match, match.id == side.match_id)
            .join(game, game.id == match.custom_game_id)
            .outerjoin(opponent, sa.and_(opponent.match_id == match.id, opponent.id != side.id))
            .where(game.workspace_id == workspace_id)
        )

    return out


def _predicates(rows: Any, filters: RankOverviewFilters) -> list[sa.ColumnElement[bool]]:
    preds: list[sa.ColumnElement[bool]] = []
    if filters.author_user_ids:
        preds.append(rows.c.author_user_id.in_(filters.author_user_ids))
    if filters.roles:
        preds.append(rows.c.role.in_(filters.roles))
    if filters.rank_min is not None:
        preds.append(rows.c.rank_value >= filters.rank_min)
    if filters.rank_max is not None:
        preds.append(rows.c.rank_value <= filters.rank_max)
    if filters.differs_from_canon:
        # Only the author layer has a canon to differ from; "no canon at all"
        # counts as a difference, which is what IS DISTINCT FROM 0 says.
        preds.append(sa.and_(rows.c.layer == "author", rows.c.canon_diff.is_distinct_from(0)))
    if filters.date_from is not None:
        preds.append(rows.c.at >= filters.date_from)
    if filters.date_to is not None:
        preds.append(rows.c.at <= filters.date_to)
    return preds


def _order_by(rows: Any, filters: RankOverviewFilters) -> list[Any]:
    descending = filters.order == "desc"
    primary = rows.c[filters.sort if filters.sort in SORTS else "display_name"]
    lead = sa.nulls_last(primary.desc()) if descending else sa.nulls_last(primary.asc())
    # Everything after the requested column exists to make the order total, so
    # paging cannot show the same row twice or skip one.
    return [
        lead,
        rows.c.display_name.asc(),
        rows.c.layer.asc(),
        rows.c.role.asc(),
        rows.c.member_id.asc(),
        sa.nulls_last(rows.c.author_user_id.asc()),
        rows.c.row_id.asc(),
    ]


def _context(row: Any) -> dict[str, Any] | None:
    if row.context_kind is None:
        return None
    return {
        "kind": row.context_kind,
        "id": row.context_id,
        "label": row.context_label,
        "team": row.context_team,
        "lobby_index": row.context_lobby_index,
    }


def _dump(row: Any, author_names: dict[int, str | None]) -> dict[str, Any]:
    return {
        "layer": row.layer,
        "player_id": row.player_id,
        "member_id": row.member_id,
        "display_name": row.display_name,
        "battle_tag": row.battle_tag,
        "author_user_id": row.author_user_id,
        "author_name": author_names.get(row.author_user_id) if row.author_user_id is not None else None,
        "role": row.role,
        "rank_value": row.rank_value,
        "division": row.division,
        "source": row.source,
        "sigma": row.sigma,
        "delta": row.delta,
        "canon_diff": row.canon_diff,
        "ow_division": row.ow_division,
        "ow_tier": row.ow_tier,
        "context": _context(row),
        "at": row.at.isoformat() if row.at is not None else None,
    }


async def rank_overview_page(
    session: AsyncSession,
    *,
    workspace_id: int,
    filters: RankOverviewFilters,
) -> tuple[list[dict[str, Any]], int]:
    """One page of the flat rank table, plus the exact total behind it."""
    if not filters.layers:
        return [], 0

    ws_grid = await get_effective_division_grid(session, workspace_id)
    global_grid = await get_effective_division_grid(session, None)
    members = _members_cte(workspace_id, filters)
    branches = _branches(workspace_id, filters, members, ws_grid, global_grid)
    if not branches:
        return [], 0

    rows = sa.union_all(*branches).subquery("rank_rows") if len(branches) > 1 else branches[0].subquery("rank_rows")
    preds = _predicates(rows, filters)

    total = await session.scalar(
        sa.select(sa.func.count()).select_from(sa.select(sa.literal(1)).select_from(rows).where(*preds).subquery())
    )
    result = await session.execute(
        sa.select(rows, division_case_expr(rows.c.rank_value, ws_grid).label("division"))
        .where(*preds)
        .order_by(*_order_by(rows, filters))
        .limit(filters.per_page)
        .offset(max(filters.page - 1, 0) * filters.per_page)
    )
    page = result.all()
    author_names = await hosts_by_user_id(
        session,
        workspace_id=workspace_id,
        user_ids=[row.author_user_id for row in page if row.author_user_id is not None],
    )
    return [_dump(row, author_names) for row in page], int(total or 0)


def parse_layers(raw: Sequence[str] | None) -> tuple[str, ...]:
    """Requested layers, defaulting to the current ones; unknown names drop out."""
    if not raw:
        return CURRENT_LAYERS
    return tuple(layer for layer in LAYERS if layer in set(raw))
