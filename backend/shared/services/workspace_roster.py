"""The roster a workspace balances from: its members, by BattleTag.

``workspace_member`` is the anchor registrations, teams, drafts and achievements
already use, so it is also the roster the mix tools read -- there is no separate
balancer-local player list to keep in sync with it. Adding somebody by BattleTag
therefore provisions the same identity a registration would: find-or-create the
``players.user``, attach the battlenet handle, anchor the membership.

This is the reusable half of ``registration_service.ensure_player_identity``.
The registration-specific precedence (prefer the registering account's own
player, collapse a shadow player's handle onto it, walk declared smurfs) stays
there -- a tag typed into the mix roster carries no claim of ownership.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider, normalize_social_handle
from shared.repository import UserRepository, get_or_create_workspace_member
from shared.services.social_identity import social_identity_service
from shared.services.team_export.identity import find_users_by_battle_tags

__all__ = (
    "RosterMember",
    "ensure_member_for_battle_tag",
    "hosts_by_user_id",
    "list_roster",
    "workspace_member_user_ids",
    "roster_page",
    "roster_summary",
)


@dataclass(frozen=True, slots=True)
class RosterMember:
    """One roster row: the membership, its player, and the tag it is known by."""

    member_id: int
    player_id: int
    battle_tag: str | None
    display_name: str | None
    #: The player's linked login identity (``players.user.auth_user_id``), or
    #: ``None`` if they have never signed in. ``auth.user.id`` is the space a
    #: mix's ``host_user_id`` and its co-host grants are addressed in -- a member
    #: with no linked account can be ranked and rostered, but can never be
    #: picked as a host or co-host, because there is nobody who could log in
    #: and pass the write check.
    auth_user_id: int | None = None


def _main_battle_tag() -> sa.ScalarSelect[str]:
    """The player's primary battlenet handle, as a correlated scalar.

    A scalar subquery rather than a join: a player with declared smurfs owns
    several battlenet rows, and joining them would multiply the roster.
    """
    return (
        sa.select(models.SocialAccount.username)
        .where(
            models.SocialAccount.user_id == models.User.id,
            models.SocialAccount.provider == SocialProvider.BATTLENET,
        )
        .order_by(models.SocialAccount.is_primary.desc(), models.SocialAccount.id.asc())
        .limit(1)
        .correlate(models.User)
        .scalar_subquery()
    )


def _filters(
    workspace_id: int,
    search: str | None,
    *,
    author_user_id: int | None = None,
    author_only: bool = False,
) -> list[sa.ColumnElement[bool]]:
    filters: list[sa.ColumnElement[bool]] = [models.WorkspaceMember.workspace_id == workspace_id]
    if author_only and author_user_id is not None:
        # The "My ranks" shortcut: only members this author has personally
        # corrected -- the book that outranks the canon when *their* mixes
        # are balanced (see ``shared.models.member_rank.MemberRank``).
        filters.append(
            sa.exists().where(
                models.MemberRank.workspace_id == workspace_id,
                models.MemberRank.workspace_member_id == models.WorkspaceMember.id,
                models.MemberRank.author_user_id == author_user_id,
            )
        )
    needle = (search or "").strip()
    if not needle:
        return filters
    like = f"%{needle}%"
    # ``username_normalized`` is casefolded and space-free, so the needle has to
    # be put through the same normalizer to match "Foo # 1234" against "foo#1234".
    normalized = f"%{normalize_social_handle(SocialProvider.BATTLENET, needle)}%"
    filters.append(
        sa.or_(
            models.WorkspaceMember.display_name.ilike(like),
            models.User.name.ilike(like),
            sa.exists().where(
                models.SocialAccount.user_id == models.User.id,
                models.SocialAccount.provider == SocialProvider.BATTLENET,
                models.SocialAccount.username_normalized.like(normalized),
            ),
        )
    )
    return filters


async def roster_page(
    session: AsyncSession,
    *,
    workspace_id: int,
    search: str | None = None,
    page: int = 1,
    per_page: int = 30,
    author_user_id: int | None = None,
    author_only: bool = False,
) -> tuple[list[RosterMember], int]:
    """One page of the workspace roster, newest-agnostic (ordered by member id)."""
    filters = _filters(workspace_id, search, author_user_id=author_user_id, author_only=author_only)
    joined = sa.select(models.WorkspaceMember.id).join(models.User, models.User.id == models.WorkspaceMember.player_id)
    total = await session.scalar(sa.select(sa.func.count()).select_from(joined.where(*filters).subquery()))
    result = await session.execute(
        sa.select(
            models.WorkspaceMember.id,
            models.WorkspaceMember.player_id,
            models.WorkspaceMember.display_name,
            models.User.name,
            models.User.auth_user_id,
            _main_battle_tag(),
        )
        .join(models.User, models.User.id == models.WorkspaceMember.player_id)
        .where(*filters)
        .order_by(models.WorkspaceMember.id.asc())
        .limit(per_page)
        .offset(max(page - 1, 0) * per_page)
    )
    rows = [
        RosterMember(
            member_id=member_id,
            player_id=player_id,
            battle_tag=battle_tag,
            display_name=display_name or player_name,
            auth_user_id=auth_user_id,
        )
        for member_id, player_id, display_name, player_name, auth_user_id, battle_tag in result.all()
    ]
    return rows, int(total or 0)


async def roster_summary(
    session: AsyncSession, *, workspace_id: int, author_user_id: int | None = None
) -> tuple[int, int]:
    """(workspace total, count that author has personally rank-corrected) -- one round trip.

    Backs the add-players dialog's chip counts, which both have to be visible
    before either filter is touched -- a ``roster_page`` call per chip would be
    two round trips (and a page of rows) for numbers that need neither.
    """
    joined = (
        sa.select(models.WorkspaceMember.id)
        .join(models.User, models.User.id == models.WorkspaceMember.player_id)
        .where(models.WorkspaceMember.workspace_id == workspace_id)
        .subquery()
    )
    if author_user_id is None:
        total = await session.scalar(sa.select(sa.func.count()).select_from(joined))
        return int(total or 0), 0
    authored = sa.exists().where(
        models.MemberRank.workspace_id == workspace_id,
        models.MemberRank.workspace_member_id == joined.c.id,
        models.MemberRank.author_user_id == author_user_id,
    )
    total, author_total = (
        await session.execute(
            sa.select(
                sa.func.count(),
                sa.func.count(sa.case((authored, 1), else_=None)),
            ).select_from(joined)
        )
    ).one()
    return int(total or 0), int(author_total or 0)


async def list_roster(
    session: AsyncSession, *, workspace_id: int, member_ids: Sequence[int]
) -> dict[int, RosterMember]:
    """Named roster rows for an explicit set of members (a mix lineup)."""
    if not member_ids:
        return {}
    result = await session.execute(
        sa.select(
            models.WorkspaceMember.id,
            models.WorkspaceMember.player_id,
            models.WorkspaceMember.display_name,
            models.User.name,
            models.User.auth_user_id,
            _main_battle_tag(),
        )
        .join(models.User, models.User.id == models.WorkspaceMember.player_id)
        .where(
            models.WorkspaceMember.workspace_id == workspace_id,
            models.WorkspaceMember.id.in_(list(member_ids)),
        )
    )
    return {
        member_id: RosterMember(
            member_id=member_id,
            player_id=player_id,
            battle_tag=battle_tag,
            display_name=display_name or player_name,
            auth_user_id=auth_user_id,
        )
        for member_id, player_id, display_name, player_name, auth_user_id, battle_tag in result.all()
    }


async def hosts_by_user_id(
    session: AsyncSession, *, workspace_id: int, user_ids: Sequence[int]
) -> dict[int, str | None]:
    """Display name for a set of ``auth.user.id``s, resolved within one workspace.

    ``CustomGame.host_user_id``, its co-host grants and ``MemberRank.author_user_id``
    are all ``auth.user.id``s -- the identity the write checks compare the caller
    against -- not ``workspace_member.player_id``.
    A player can exist with no linked account (``User.auth_user_id`` is a
    nullable 1:0..1 link to ``auth.user``, set only once somebody signs in), so
    joining on ``player_id`` used to resolve nothing for a real host/co-host and
    something wrong for a same-numbered player, letting a member with no login
    identity through ``transfer_host``/``add_co_host``'s membership check only
    to fail at the ``custom_game.host_user_id`` foreign key itself.

    Left-joined, not inner: an author who rank-corrected someone here (any
    workspace member can) need never have added *themselves* as a player/
    member of this workspace's own roster -- an admin fixing ranks without
    playing is the common case. An inner join on ``workspace_member`` dropped
    that account's row entirely, so the caller fell back to ``#<id>`` for
    every such author instead of a name. ``auth.user.username`` is the final
    fallback: it is required and unique, so it resolves for every id that
    still names a real account.
    """
    ids = {uid for uid in user_ids if uid is not None}
    if not ids:
        return {}
    result = await session.execute(
        sa.select(
            models.AuthUser.id,
            models.AuthUser.username,
            models.WorkspaceMember.display_name,
            models.User.name,
        )
        .select_from(models.AuthUser)
        .outerjoin(models.User, models.User.auth_user_id == models.AuthUser.id)
        .outerjoin(
            models.WorkspaceMember,
            sa.and_(
                models.WorkspaceMember.player_id == models.User.id,
                models.WorkspaceMember.workspace_id == workspace_id,
            ),
        )
        .where(models.AuthUser.id.in_(ids))
    )
    return {
        auth_user_id: (display_name or player_name or username)
        for auth_user_id, username, display_name, player_name in result.all()
    }


async def workspace_member_user_ids(
    session: AsyncSession,
    *,
    workspace_id: int,
    user_ids: Sequence[int],
) -> set[int]:
    """The subset of ``auth.user.id``s that belongs to this workspace.

    Server-side twin of ``AuthUser.is_workspace_member``, for ids whose
    ``AuthUser`` the caller does not hold: membership is an RBAC fact -- a role
    scoped to the workspace -- plus the superuser bypass. It is deliberately
    *not* a ``workspace_member`` lookup. That table is the player roster, and
    the two sets differ in both directions: an admin holds a role here without
    ever playing, while a roster row alone would not pass the RBAC gate every
    mix endpoint already applies to the caller. Granting off the roster would
    hand somebody a co-host seat they then get a 403 on.
    """
    ids = {user_id for user_id in user_ids if user_id is not None}
    if not ids:
        return set()
    holds_workspace_role = (
        sa.select(sa.literal(1))
        .select_from(models.user_roles)
        .join(models.Role, models.Role.id == models.user_roles.c.role_id)
        .where(
            models.user_roles.c.user_id == models.AuthUser.id,
            models.Role.workspace_id == workspace_id,
        )
        .exists()
    )
    result = await session.scalars(
        sa.select(models.AuthUser.id).where(
            models.AuthUser.id.in_(ids),
            sa.or_(models.AuthUser.is_superuser.is_(True), holds_workspace_role),
        )
    )
    return set(result.all())


async def ensure_member_for_battle_tag(
    session: AsyncSession,
    *,
    workspace_id: int,
    battle_tag: str,
    display_name: str | None = None,
) -> models.WorkspaceMember:
    """Find-or-create the membership a BattleTag denotes in this workspace.

    The player row is deliberately created without ``auth_user_id``: a tag typed
    into the roster is somebody the host is ranking, not the host's own account,
    and ``get_or_create_workspace_member`` only hands out the baseline RBAC role
    to auth-linked players -- so this never grants anybody workspace access.
    """
    tag = (battle_tag or "").strip()
    if not tag:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="battle_tag is required")

    found = await find_users_by_battle_tags(session, [tag])
    user = found.get(tag)
    if user is None:
        user = await UserRepository().create(session, models.User(name=tag))
    await social_identity_service.upsert(session, user_id=user.id, provider=SocialProvider.BATTLENET, username=tag)
    member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=user.id)
    if display_name is not None:
        member.display_name = display_name or None
        await session.flush()
    return member
