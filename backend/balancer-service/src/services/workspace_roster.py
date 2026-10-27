"""The roster a workspace balances from: its members, by the handle of the discipline's identity provider.

``workspace_member`` is the anchor registrations, teams, drafts and achievements
already use, so it is also the roster the mix tools read -- there is no separate
balancer-local player list to keep in sync with it. Adding somebody by game
identity therefore provisions the same identity a registration would: find-or-create
the ``players.user``, attach the provider handle, admit the membership.

This is the reusable half of ``registration_service.ensure_player_identity``.
The registration-specific precedence (prefer the registering account's own
player, collapse a shadow player's handle onto it, walk declared extra handles) stays
there -- a handle typed into the mix roster carries no claim of ownership.

Observation anchors (``workspace_member.observed_only``, made by stats ingestion) are not
members: the roster never lists them, and ``ensure_member_for_identity`` is a real admission.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.social import display_social_handle, get_provider, matches_handle_pattern, normalize_social_handle
from shared.disciplines import DISCIPLINES
from shared.repository import (
    SocialAccountRepository,
    UserRepository,
    WorkspaceMemberRepository,
    get_or_create_workspace_member,
)
from shared.schemas.identity import PlayerIdentityRead
from shared.services.ontology import workspace_discipline
from shared.services.social_identity import social_identity_service

__all__ = (
    "RosterMember",
    "ensure_member_for_identity",
    "hosts_by_user_id",
    "list_roster",
    "main_handle",
    "workspace_member_user_ids",
    "roster_page",
    "roster_summary",
)


@dataclass(frozen=True, slots=True)
class RosterMember:
    """One roster row: the membership, its player, and the game identity it is known by."""

    member_id: int
    player_id: int
    #: The player's primary account of the requested discipline's identity provider.
    identity: PlayerIdentityRead | None
    display_name: str | None
    #: The player's linked login identity (``players.user.auth_user_id``), or
    #: ``None`` if they have never signed in. ``auth.user.id`` is the space a
    #: mix's ``host_user_id`` and its co-host grants are addressed in -- a member
    #: with no linked account can be ranked and rostered, but can never be
    #: picked as a host or co-host, because there is nobody who could log in
    #: and pass the write check.
    auth_user_id: int | None = None
    #: ``players.user.name`` -- the unique canonical name every profile link is built from (never a game handle).
    player_name: str | None = None

    @property
    def handle(self) -> str | None:
        """The identity's handle, for labels that fall back to it when there is no display name."""
        return self.identity.handle if self.identity is not None else None


def main_handle(provider: str) -> sa.ScalarSelect[str]:
    """The player's primary ``provider`` handle, as a correlated scalar.

    A scalar subquery rather than a join: a player with several accounts of one
    provider (extra Battle.net accounts) owns several rows, and joining them would
    multiply the roster.
    """
    return (
        sa.select(models.SocialAccount.username)
        .where(
            models.SocialAccount.user_id == models.User.id,
            models.SocialAccount.provider == provider,
        )
        .order_by(models.SocialAccount.is_primary.desc(), models.SocialAccount.id.asc())
        .limit(1)
        .correlate(models.User)
        .scalar_subquery()
    )


def _filters(
    workspace_id: int,
    search: str | None,
    provider: str | None,
    *,
    author_user_id: int | None = None,
    author_only: bool = False,
) -> list[sa.ColumnElement[bool]]:
    filters: list[sa.ColumnElement[bool]] = [
        models.WorkspaceMember.workspace_id == workspace_id,
        # An observation anchor is not a member: the roster never shows it.
        models.WorkspaceMember.observed_only.is_(False),
    ]
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
    matches = [models.WorkspaceMember.display_name.ilike(like), models.User.name.ilike(like)]
    if provider is not None:
        # ``username_normalized`` is the provider's normal form, so the needle has to
        # be put through the same normalizer to match "Foo # 1234" against "foo#1234".
        normalized = f"%{normalize_social_handle(provider, needle)}%"
        matches.append(
            sa.exists().where(
                models.SocialAccount.user_id == models.User.id,
                models.SocialAccount.provider == provider,
                models.SocialAccount.username_normalized.like(normalized),
            )
        )
    filters.append(sa.or_(*matches))
    return filters


def _identity_column(provider: str | None) -> sa.ColumnElement[str | None]:
    return main_handle(provider) if provider is not None else sa.cast(sa.null(), sa.String)


def _roster_member(
    provider: str | None,
    member_id: int,
    player_id: int,
    display_name: str | None,
    player_name: str,
    auth_user_id: int | None,
    handle: str | None,
) -> RosterMember:
    return RosterMember(
        member_id=member_id,
        player_id=player_id,
        identity=PlayerIdentityRead.of(provider, handle),
        display_name=display_name or player_name,
        auth_user_id=auth_user_id,
        player_name=player_name,
    )


async def roster_page(
    session: AsyncSession,
    *,
    workspace_id: int,
    provider: str | None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 30,
    author_user_id: int | None = None,
    author_only: bool = False,
) -> tuple[list[RosterMember], int]:
    """One page of the workspace roster, newest-agnostic (ordered by member id).

    ``provider`` is the discipline's identity provider: the handle each row is known by and the
    account a search needle matches. ``None`` (a discipline with no provider) leaves every identity empty.
    """
    filters = _filters(workspace_id, search, provider, author_user_id=author_user_id, author_only=author_only)
    joined = sa.select(models.WorkspaceMember.id).join(models.User, models.User.id == models.WorkspaceMember.player_id)
    total = await session.scalar(sa.select(sa.func.count()).select_from(joined.where(*filters).subquery()))
    result = await session.execute(
        sa.select(
            models.WorkspaceMember.id,
            models.WorkspaceMember.player_id,
            models.WorkspaceMember.display_name,
            models.User.name,
            models.User.auth_user_id,
            _identity_column(provider),
        )
        .join(models.User, models.User.id == models.WorkspaceMember.player_id)
        .where(*filters)
        .order_by(models.WorkspaceMember.id.asc())
        .limit(per_page)
        .offset(max(page - 1, 0) * per_page)
    )
    rows = [_roster_member(provider, *row) for row in result.all()]
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
        .where(models.WorkspaceMember.workspace_id == workspace_id, models.WorkspaceMember.observed_only.is_(False))
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
    session: AsyncSession, *, workspace_id: int, provider: str | None, member_ids: Sequence[int]
) -> dict[int, RosterMember]:
    """Named roster rows for an explicit set of members (a mix lineup), identified by ``provider`` handles."""
    if not member_ids:
        return {}
    result = await session.execute(
        sa.select(
            models.WorkspaceMember.id,
            models.WorkspaceMember.player_id,
            models.WorkspaceMember.display_name,
            models.User.name,
            models.User.auth_user_id,
            _identity_column(provider),
        )
        .join(models.User, models.User.id == models.WorkspaceMember.player_id)
        .where(
            models.WorkspaceMember.workspace_id == workspace_id,
            models.WorkspaceMember.observed_only.is_(False),
            models.WorkspaceMember.id.in_(list(member_ids)),
        )
    )
    return {row[0]: _roster_member(provider, *row) for row in result.all()}


async def hosts_by_user_id(
    session: AsyncSession, *, workspace_id: int, user_ids: Sequence[int]
) -> dict[int, str | None]:
    """Display name for a set of ``auth.user.id``s, resolved within one workspace.

    ``CustomGame.host_user_id``, its co-host grants and ``MemberRank.author_user_id``
    are all ``auth.user.id``s -- the identity the write checks compare the caller
    against -- not ``workspace_member.player_id``.
    A player can exist with no linked account (``User.auth_user_id`` is a
    nullable 1:0..1 link to ``auth.user``, set only once somebody signs in), so
    joining on ``player_id`` would resolve nothing for a real host/co-host and
    something wrong for a same-numbered player.

    Left-joined, not inner: an author who rank-corrected someone here (any
    workspace member can) need never have added *themselves* as a player/
    member of this workspace's own roster -- an admin fixing ranks without
    playing is the common case. ``auth.user.username`` is the final fallback:
    it is required and unique, so it resolves for every id that still names a
    real account.
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


def _handle_error(provider: str, key: str) -> ApiHTTPException:
    return ApiHTTPException(
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        [ApiExc(msg=f"Invalid {provider} handle", code=key, field="identity.handle")],
    )


async def ensure_member_for_identity(
    session: AsyncSession,
    *,
    workspace_id: int,
    discipline: str,
    provider: str,
    handle: str,
    admit_account_holders: bool,
    display_name: str | None = None,
) -> models.WorkspaceMember:
    """Find-or-admit the membership a game identity denotes in this workspace.

    ``provider`` must be the discipline's own identity provider and ``handle`` must fit its grammar. Exactly one
    existing player carrying that normalized handle is reused; none creates an unlinked player named after the
    handle; several distinct players is a ``409 identity_conflict`` before anything is written. A handle is
    never matched through a display name, and creating one confers no verification, provider subject or login.

    The player row is deliberately created without ``auth_user_id``: a handle typed into the roster is somebody
    the host is ranking, not the host's own account, so admitting a new or unlinked player grants no workspace
    access. Admitting an existing auth-linked player does (``get_or_create_workspace_member`` hands them the
    baseline RBAC role), so unless ``admit_account_holders`` (the caller may create workspace members) it is a
    ``403 forbidden`` before anything is written; an account holder who already is an admitted member stays an
    idempotent hit for anyone. It is a real admission (clears ``observed_only``). Flushes only; the caller commits.
    """
    await workspace_discipline(session, workspace_id=workspace_id, requested=discipline)
    declared = DISCIPLINES[discipline].identity_provider
    if declared is None or declared != provider:
        raise ApiHTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            [
                ApiExc(
                    msg=f"{discipline!r} identifies players by {declared!r}, not {provider!r}",
                    code="identity.provider_mismatch",
                    field="identity.provider",
                )
            ],
        )
    spec = get_provider(provider)
    error_key = spec.handle_error_key if spec is not None else "identity.format"
    shown = display_social_handle(provider, handle)
    if not shown or not matches_handle_pattern(provider, shown):
        raise _handle_error(provider, error_key)

    normalized = normalize_social_handle(provider, shown)
    owners = await SocialAccountRepository().find_players_by_handle(
        session, provider=provider, username_normalized=normalized
    )
    if len(owners) > 1:
        raise ApiHTTPException(
            status.HTTP_409_CONFLICT,
            [
                ApiExc(
                    msg="Several players carry this handle; merge them first",
                    code="identity_conflict",
                    field="identity.handle",
                )
            ],
        )
    if owners:
        user = owners[0]
        if user.auth_user_id is not None and not admit_account_holders:
            current = await WorkspaceMemberRepository().get_by_player(
                session, workspace_id=workspace_id, player_id=user.id
            )
            if current is None or current.removed_at is not None or current.observed_only:
                raise ApiHTTPException(
                    status.HTTP_403_FORBIDDEN,
                    [
                        ApiExc(
                            msg="This player has an account; only a member manager can add them to the workspace",
                            code="forbidden",
                            field="identity.handle",
                        )
                    ],
                )
    else:
        user = await UserRepository().create_player(session, name=shown, identity=(provider, normalized))
        await social_identity_service.upsert(session, user_id=user.id, provider=provider, username=shown)
    member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=user.id)
    if display_name is not None:
        member.display_name = display_name or None
        await session.flush()
    return member
