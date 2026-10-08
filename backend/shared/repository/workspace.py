from __future__ import annotations

import typing
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core.pagination import PaginationSortParams
from shared.models.identity.rbac import role_permissions, user_lacks_roles, user_roles
from shared.rbac.catalog import WORKSPACE_SYSTEM_ROLE_NAMES
from shared.repository.base import BaseRepository

# Rank assigned to a member holding only custom roles, or none: sorts last.
ROLELESS_RANK = 99

#: The workspace system roles published by the public staff endpoint, best
#: first. A strict prefix of ``WORKSPACE_SYSTEM_ROLE_NAMES``: ``host`` and
#: ``player`` are not staff, so neither puts a name on the public page.
STAFF_ROLE_NAMES: tuple[str, ...] = ("owner", "admin", "referee")


class WorkspaceRepository(BaseRepository[models.Workspace]):
    def __init__(self) -> None:
        super().__init__(models.Workspace)

    async def get_by_slug(self, session: AsyncSession, slug: str) -> models.Workspace | None:
        return await self.get_by(session, options=self.default_grid_options(), slug=slug)

    async def get_by_subdomain(self, session: AsyncSession, subdomain: str) -> models.Workspace | None:
        """Resolve a platform-zone subdomain label to its workspace (Phase 1).

        Deliberately a bare lookup (no eager-loaded grid options): the
        ``by_host`` RPC only needs ``id``/``slug`` for tenant resolution, and
        this runs on the request-resolution hot path.
        """
        result = await session.execute(sa.select(models.Workspace).where(models.Workspace.subdomain == subdomain))
        return result.scalar_one_or_none()

    async def get_by_verified_custom_domain(self, session: AsyncSession, domain: str) -> models.Workspace | None:
        """Resolve a custom domain to its workspace, but only once verified (Phase 2).

        Fail-closed: an unverified (or unclaimed) ``custom_domain`` never
        resolves, so a domain mid-verification can't be used to spoof a
        workspace. Bare lookup, mirroring ``get_by_subdomain``, for the same
        request-resolution hot path.
        """
        result = await session.execute(
            sa.select(models.Workspace).where(
                models.Workspace.custom_domain == domain,
                models.Workspace.custom_domain_verified_at.is_not(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_custom_domain_any(self, session: AsyncSession, domain: str) -> models.Workspace | None:
        """Resolve a custom domain to its owning workspace regardless of
        verification state — the best-effort duplicate-claim pre-check for
        ``set_custom_domain``.

        Unlike ``get_by_verified_custom_domain``, this also matches an
        unverified claim: the unique index ``ix_workspace_custom_domain``
        blocks ANY two workspaces from holding the same ``custom_domain``
        string, verified or not, so the pre-check has to look at the same
        population the index guards. Still just a best-effort check — a
        concurrent claim between this read and the write is a genuine TOCTOU
        gap, closed authoritatively by catching the index's ``IntegrityError``
        at write time (see ``set_custom_domain``).
        """
        result = await session.execute(sa.select(models.Workspace).where(models.Workspace.custom_domain == domain))
        return result.scalar_one_or_none()

    async def get_with_default_grid(self, session: AsyncSession, workspace_id: int) -> models.Workspace | None:
        return await self.get(session, workspace_id, options=self.default_grid_options())

    async def lock_by_id(self, session: AsyncSession, workspace_id: int) -> int | None:
        """``SELECT id ... FOR UPDATE`` — serialize concurrent writers on one workspace.

        Used by the division-grid import paths, where two imports into the same
        workspace must not interleave. The projection is deliberate: the caller wants
        the lock, not the row.
        """
        return await session.scalar(
            sa.select(models.Workspace.id).where(models.Workspace.id == workspace_id).with_for_update()
        )

    async def clear_default_grid_version(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        version_ids: Sequence[int],
    ) -> None:
        """Detach the workspace default when the version it points at is being deleted.

        One statement over the whole set of doomed versions rather than a load-then-check
        per version.
        """
        if not version_ids:
            return
        await session.execute(
            sa.update(models.Workspace)
            .where(
                models.Workspace.id == workspace_id,
                models.Workspace.default_division_grid_version_id.in_(tuple(version_ids)),
            )
            .values(default_division_grid_version_id=None)
        )

    async def list_ordered(self, session: AsyncSession) -> Sequence[models.Workspace]:
        result = await session.execute(
            sa.select(models.Workspace).options(*self.default_grid_options()).order_by(models.Workspace.id.asc())
        )
        return result.scalars().all()

    async def count_by_owner(self, session: AsyncSession, *, owner_id: int) -> int:
        """How many workspaces this account is the create-time accountable party for.

        Backs the self-service create cap. Deliberately a plain count over the
        ``owner_id`` FK with no join through ``auth.user_roles``: the RBAC
        ``owner`` role is a mutable permission grant (co-owners, reassignment,
        revocation), so counting through it both double-counts co-owned
        workspaces and is gameable by handing the role away.
        """
        return int(
            await session.scalar(
                sa.select(sa.func.count(models.Workspace.id)).where(models.Workspace.owner_id == owner_id)
            )
            or 0
        )

    async def list_ids_by_discord_guild(self, session: AsyncSession, guild_id: str) -> Sequence[int]:
        """Workspace ids configured for this Discord guild — usually zero or one.

        Backs instant subscription re-evaluation on Discord role/member events:
        the bot doesn't know which workspace(s) map to a guild until it looks it up.
        """
        result = await session.execute(
            sa.select(models.Workspace.id).where(models.Workspace.discord_guild_id == guild_id)
        )
        return result.scalars().all()

    @staticmethod
    def default_grid_options() -> list[object]:
        return [
            selectinload(models.Workspace.default_division_grid_version).selectinload(models.DivisionGridVersion.tiers)
        ]


class WorkspaceMemberRepository(BaseRepository[models.WorkspaceMember]):
    def __init__(self) -> None:
        super().__init__(models.WorkspaceMember)

    async def get_member(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
    ) -> models.WorkspaceMember | None:
        """Look up a member by the auth identity, joining through ``players.user``.

        ``workspace_member`` is anchored on ``player_id``; this join is the
        bridge so RPC/route callers that only know the current auth user's id
        can still resolve their membership row.
        """
        result = await session.execute(
            sa.select(models.WorkspaceMember)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .options(selectinload(models.WorkspaceMember.player))
            .where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.User.auth_user_id == auth_user_id,
            )
        )
        return result.scalars().first()

    async def get_by_player(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        player_id: int,
    ) -> models.WorkspaceMember | None:
        result = await session.execute(
            sa.select(models.WorkspaceMember).where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.WorkspaceMember.player_id == player_id,
            )
        )
        return result.scalars().first()

    async def list_memberships_for_auth_user(
        self,
        session: AsyncSession,
        auth_user_id: int,
    ) -> list[tuple[int, str]]:
        """``(workspace_id, slug)`` for every workspace an auth user belongs to.

        ``workspace_member`` is anchored on ``player_id``, so the auth identity is
        reached through ``players.user.auth_user_id``. Returns bare tuples: this
        feeds the JWT/RBAC payload, which needs the id and slug and nothing else.
        """
        result = await session.execute(
            sa.select(models.WorkspaceMember.workspace_id, models.Workspace.slug)
            .join(models.Workspace, models.Workspace.id == models.WorkspaceMember.workspace_id)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .where(models.User.auth_user_id == auth_user_id)
        )
        return [(workspace_id, slug) for workspace_id, slug in result.all()]

    async def exists_for_auth_user(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_id: int,
    ) -> bool:
        found = await session.scalar(
            sa.select(sa.literal(True))
            .select_from(models.WorkspaceMember)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.User.auth_user_id == auth_user_id,
            )
            .limit(1)
        )
        return found is True

    async def list_by_workspace(
        self,
        session: AsyncSession,
        workspace_id: int,
    ) -> Sequence[models.WorkspaceMember]:
        """List the workspace's RBAC members — auth-linked players only.

        ``workspace_member`` is anchored on ``player_id`` and now holds two
        distinct populations: real RBAC members (auth users who joined via
        ``add_member``) and tournament participants anchored by
        registration / team / draft / achievement flows via
        ``get_or_create_workspace_member``. The latter frequently have no auth
        account (``players.user.auth_user_id IS NULL``) — they are pure
        tournament players, not workspace members.

        The RBAC members screen (``rpc.app.workspaces.members_list``) only
        deals with the former, and every downstream step resolves the row's
        auth identity (``get_member_auth_user_id``); an auth-less row would
        make the whole listing 500. The INNER JOIN on ``players.user`` plus the
        ``auth_user_id IS NOT NULL`` filter scope this to auth-linked members
        (mirrors ``get_member``'s bridge join).
        """
        result = await session.execute(
            sa.select(models.WorkspaceMember)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .options(selectinload(models.WorkspaceMember.player))
            .where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.User.auth_user_id.isnot(None),
            )
            .order_by(models.WorkspaceMember.id.asc())
        )
        return result.scalars().all()

    async def workspace_ids_for_player(self, session: AsyncSession, player_id: int) -> Sequence[int]:
        """Workspaces this player is anchored to, ids only.

        Feeds the role-autofill run after a player↔auth-user link: the caller
        needs the scope of each membership row, never the row itself.
        """
        result = await session.scalars(
            sa.select(models.WorkspaceMember.workspace_id).where(models.WorkspaceMember.player_id == player_id)
        )
        return result.all()

    async def list_page(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        page: int,
        per_page: int,
        search: str | None = None,
        role_id: int | None = None,
        exclude_role_id: Sequence[int] | None = None,
        sort: str = "username",
        descending: bool = False,
        unlimited_cap: int = 10_000,
    ) -> tuple[int, list[tuple[models.WorkspaceMember, models.AuthUser, list[models.Role]]]]:
        """Paginated, searchable, role-filterable RBAC members with their
        workspace roles.

        Three statements regardless of page size — count, page, and one batched
        role fetch grouped in memory — instead of a role query per row.
        ``per_page == -1`` returns everything up to ``unlimited_cap`` for
        selector/combobox callers. ``sort`` is ``username`` or ``role``, the
        latter ordering by the highest system-role rank the member's auth user
        holds in this workspace.
        """
        total = await session.scalar(
            self._members_filter(
                sa.select(sa.func.count()).select_from(models.WorkspaceMember),
                workspace_id=workspace_id,
                search=search,
                role_id=role_id,
                exclude_role_id=exclude_role_id,
            )
        )

        if sort == "role":
            rank = self._primary_role_rank(workspace_id)
            order_cols: list[sa.UnaryExpression[typing.Any]] = [
                rank.desc() if descending else rank.asc(),
                models.AuthUser.username.asc(),
                models.WorkspaceMember.id.asc(),
            ]
        else:
            order_cols = [
                models.AuthUser.username.desc() if descending else models.AuthUser.username.asc(),
                models.WorkspaceMember.id.asc(),
            ]

        page_query = self._members_filter(
            sa.select(models.WorkspaceMember, models.AuthUser),
            workspace_id=workspace_id,
            search=search,
            role_id=role_id,
            exclude_role_id=exclude_role_id,
        ).order_by(*order_cols)
        if per_page == -1:
            page_query = page_query.limit(unlimited_cap)
        else:
            page_query = page_query.offset(max(page - 1, 0) * per_page).limit(per_page)

        rows = (await session.execute(page_query)).all()
        auth_ids = [auth_user.id for (_member, auth_user) in rows]

        roles_by_user: dict[int, list[models.Role]] = {}
        if auth_ids:
            role_rows = await session.execute(
                sa.select(user_roles.c.user_id, models.Role)
                .join(models.Role, models.Role.id == user_roles.c.role_id)
                .where(
                    user_roles.c.user_id.in_(auth_ids),
                    models.Role.workspace_id == workspace_id,
                )
            )
            for user_id, role in role_rows.all():
                roles_by_user.setdefault(user_id, []).append(role)

        return total or 0, [(member, auth_user, roles_by_user.get(auth_user.id, [])) for (member, auth_user) in rows]

    @staticmethod
    def _members_filter(
        base: sa.Select[typing.Any],
        *,
        workspace_id: int,
        search: str | None,
        role_id: int | None,
        exclude_role_id: Sequence[int] | None = None,
    ) -> sa.Select[typing.Any]:
        """The auth-linked join + workspace scope shared by the count and the page.

        Auth-linked only (INNER JOIN ``players.user`` + ``auth.user``), the same
        scoping ``list_by_workspace`` applies and for the same reason: a row with
        no auth identity is a tournament participant, not an RBAC member.
        """
        base = (
            base.join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .join(models.AuthUser, models.AuthUser.id == models.User.auth_user_id)
            .where(models.WorkspaceMember.workspace_id == workspace_id)
        )
        if search and search.strip():
            like = f"%{search.strip()}%"
            base = base.where(sa.or_(models.AuthUser.username.ilike(like), models.AuthUser.email.ilike(like)))
        if role_id is not None:
            base = base.where(
                sa.exists().where(
                    user_roles.c.user_id == models.AuthUser.id,
                    user_roles.c.role_id == role_id,
                )
            )
        if exclude_role_id:
            base = base.where(user_lacks_roles(models.AuthUser.id, exclude_role_id))
        return base

    @staticmethod
    def _primary_role_rank(workspace_id: int) -> sa.ScalarSelect[typing.Any]:
        """Correlated scalar: the highest system-role rank the member's
        ``auth.user`` holds in ``workspace_id`` (owner=0 … player=4, custom or
        none -> ``ROLELESS_RANK``)."""
        rank_case = sa.case(
            *[(models.Role.name == name, idx) for idx, name in enumerate(WORKSPACE_SYSTEM_ROLE_NAMES)],
            else_=ROLELESS_RANK,
        )
        return (
            sa.select(sa.func.coalesce(sa.func.min(rank_case), ROLELESS_RANK))
            .select_from(user_roles.join(models.Role, models.Role.id == user_roles.c.role_id))
            .where(user_roles.c.user_id == models.AuthUser.id, models.Role.workspace_id == workspace_id)
            .correlate(models.AuthUser)
            .scalar_subquery()
        )

    async def list_staff(self, session: AsyncSession, workspace_id: int) -> list[tuple[str, str]]:
        """Public staff of a workspace: ``(role, player name)``, best role first.

        Source of truth is RBAC (``auth.roles`` scoped to the workspace), not a
        denormalized column — same reason the members screen reads it there. One
        row per PERSON at their highest of owner/admin/referee, so a co-owner who
        also holds ``referee`` appears once, as an owner. The INNER JOIN on
        ``players.user`` is also the skip rule: an account with no linked player
        has no public name to render and simply does not appear.
        """
        rank_case = sa.case(
            *[(models.Role.name == name, idx) for idx, name in enumerate(STAFF_ROLE_NAMES)],
        )
        rank = sa.func.min(rank_case).label("rank")
        result = await session.execute(
            sa.select(rank, models.User.name)
            .select_from(user_roles)
            .join(models.Role, models.Role.id == user_roles.c.role_id)
            .join(models.User, models.User.auth_user_id == user_roles.c.user_id)
            .where(models.Role.workspace_id == workspace_id, models.Role.name.in_(STAFF_ROLE_NAMES))
            .group_by(models.User.id, models.User.name)
            .order_by(rank.asc(), models.User.name.asc())
        )
        return [(STAFF_ROLE_NAMES[rank_value], name) for rank_value, name in result.all()]

    async def bulk_get_or_create(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        player_ids: set[int],
    ) -> dict[int, int]:
        """Batch counterpart of ``get_or_create_workspace_member``: resolve (or
        create) the ``workspace_member`` anchors for a whole roster in two
        statements.

        Mirrors ``get_or_create_workspace_member``'s insert-or-select
        idempotency (``INSERT ... ON CONFLICT DO NOTHING`` on
        ``uq_workspace_member_workspace_player``, then one ``SELECT``), so
        concurrent imports never raise duplicate-key errors. Returns
        ``player_id -> member.id``.
        """
        if not player_ids:
            return {}

        insert_stmt = (
            pg_insert(models.WorkspaceMember)
            .values(
                [
                    {"workspace_id": workspace_id, "player_id": player_id}
                    # Sorted for a deterministic insert order (avoids deadlocks
                    # between concurrent bulk imports).
                    for player_id in sorted(player_ids)
                ]
            )
            .on_conflict_do_nothing(constraint="uq_workspace_member_workspace_player")
        )
        await session.execute(insert_stmt)

        result = await session.execute(
            sa.select(models.WorkspaceMember.player_id, models.WorkspaceMember.id).where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.WorkspaceMember.player_id.in_(list(player_ids)),
            )
        )
        return dict(result.all())


async def get_or_create_workspace_member(
    session: AsyncSession,
    *,
    workspace_id: int,
    player_id: int,
) -> models.WorkspaceMember:
    """Idempotently create (or fetch) the membership row for ``player_id``.

    Insert-or-select on ``uq_workspace_member_workspace_player``: an
    ``INSERT ... ON CONFLICT DO NOTHING`` followed by a ``SELECT`` when the
    row already existed, so concurrent calls never raise
    ``IntegrityError``/duplicate-key races.
    """
    insert_stmt = (
        pg_insert(models.WorkspaceMember)
        .values(workspace_id=workspace_id, player_id=player_id)
        .on_conflict_do_nothing(constraint="uq_workspace_member_workspace_player")
        .returning(models.WorkspaceMember.id)
    )
    result = await session.execute(insert_stmt)
    member_id = result.scalar_one_or_none()
    if member_id is not None:
        await session.flush()
        member = await session.get(models.WorkspaceMember, member_id)
        assert member is not None
        # Autofill the baseline ``member`` RBAC role for a brand-new anchor of an
        # auth-linked player: the members screen treats every auth-linked row as
        # an RBAC member, so a fresh row must not be role-less. Fires ONLY on a
        # real insert (not idempotent hits) and ONLY when the player has an auth
        # account; the helper is additive (never downgrades a later ``player`` /
        # explicit grant). Local import avoids any shared.repository<->shared.rbac
        # import-time coupling on this widely-imported module.
        from shared.rbac import assign_default_member_role_if_roleless

        auth_user_id = await session.scalar(sa.select(models.User.auth_user_id).where(models.User.id == player_id))
        if auth_user_id is not None:
            await assign_default_member_role_if_roleless(session, user_id=auth_user_id, workspace_id=workspace_id)
        return member

    existing = await WorkspaceMemberRepository().get_by_player(session, workspace_id=workspace_id, player_id=player_id)
    if existing is None:
        raise RuntimeError(
            f"get_or_create_workspace_member: no row after ON CONFLICT DO NOTHING "
            f"(workspace_id={workspace_id}, player_id={player_id})"
        )
    return existing


async def resolve_workspace_member_id(
    session: AsyncSession,
    *,
    tournament_id: int,
    player_id: int,
) -> int | None:
    """The ``workspace_member`` anchor for a roster player being created,
    resolved from the tournament they are joining — or ``None`` if
    ``tournament_id`` names no tournament.

    ``tournament-service`` (admin player CRUD) and ``parser-service`` (roster
    import) each derived this identically — workspace from tournament, then
    ``get_or_create_workspace_member`` — and each raises its own not-found
    error on ``None``, so that part stays with the caller rather than here.
    """
    workspace_id = await session.scalar(
        sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
    )
    if workspace_id is None:
        return None
    member = await get_or_create_workspace_member(session, workspace_id=workspace_id, player_id=player_id)
    return member.id


class RoleRepository(BaseRepository[models.Role]):
    def __init__(self) -> None:
        super().__init__(models.Role)

    async def get_by_name(
        self,
        session: AsyncSession,
        *,
        name: str,
        workspace_id: int | None = None,
    ) -> models.Role | None:
        return await self.get_by(session, name=name, workspace_id=workspace_id)

    async def get_with_permissions(self, session: AsyncSession, role_id: int) -> models.Role | None:
        return await self.get(session, role_id, options=[selectinload(models.Role.permissions)])

    async def find_in_scope(
        self,
        session: AsyncSession,
        *,
        name: str,
        workspace_id: int | None,
        exclude_id: int | None = None,
    ) -> models.Role | None:
        """Name-uniqueness probe within one scope (global vs a workspace).

        ``workspace_id IS NULL`` and a concrete workspace are separate uniqueness
        namespaces (see ``uq_roles_name_global`` / ``uq_roles_name_workspace``),
        so the NULL case must use ``IS NULL`` rather than ``==``.
        """
        query = self.select().where(models.Role.name == name)
        if workspace_id is None:
            query = query.where(models.Role.workspace_id.is_(None))
        else:
            query = query.where(models.Role.workspace_id == workspace_id)
        if exclude_id is not None:
            query = query.where(models.Role.id != exclude_id)
        return await session.scalar(query)

    async def list_in_scope(
        self,
        session: AsyncSession,
        params: PaginationSortParams,
        *,
        workspace_id: int | None,
        search: str | None = None,
    ) -> tuple[Sequence[models.Role], int]:
        filters: list[sa.ColumnElement[bool]] = [
            models.Role.workspace_id.is_(None) if workspace_id is None else models.Role.workspace_id == workspace_id
        ]
        if search:
            term = f"%{search}%"
            filters.append(sa.or_(models.Role.name.ilike(term), models.Role.description.ilike(term)))
        return await self.list(session, params, filters=filters)

    async def list_for_user_workspace(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        workspace_id: int,
    ) -> list[models.Role]:
        result = await session.execute(
            sa.select(models.Role)
            .join(user_roles, user_roles.c.role_id == models.Role.id)
            .where(user_roles.c.user_id == user_id, models.Role.workspace_id == workspace_id)
            .order_by(models.Role.is_system.desc(), models.Role.name.asc())
        )
        return list(result.scalars().all())

    async def global_rbac_for_user(
        self,
        session: AsyncSession,
        user_id: int,
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Global (``workspace_id IS NULL``) role names + deduped permissions.

        Explicit joins rather than relationship traversal: this runs on the token
        path, where an ORM lazy-load would raise under AsyncSession.
        """
        rows = await session.execute(
            sa.select(models.Role.name, models.Permission.resource, models.Permission.action)
            .select_from(user_roles)
            .join(models.Role, user_roles.c.role_id == models.Role.id)
            .outerjoin(role_permissions, role_permissions.c.role_id == models.Role.id)
            .outerjoin(models.Permission, role_permissions.c.permission_id == models.Permission.id)
            .where(user_roles.c.user_id == user_id, models.Role.workspace_id.is_(None))
        )
        return _collect_rbac(rows.all())

    async def workspace_rbac_for_user(
        self,
        session: AsyncSession,
        user_id: int,
        workspace_ids: Sequence[int],
    ) -> dict[int, tuple[list[str], list[dict[str, str]]]]:
        """Same shape as ``global_rbac_for_user``, keyed by workspace id.

        Every requested workspace is present in the result (empty lists when the
        user holds no role there), so callers never need a ``.get`` default.
        """
        result: dict[int, tuple[list[str], list[dict[str, str]]]] = {ws_id: ([], []) for ws_id in workspace_ids}
        if not workspace_ids:
            return result

        rows = await session.execute(
            sa.select(
                models.Role.workspace_id,
                models.Role.name,
                models.Permission.resource,
                models.Permission.action,
            )
            .select_from(user_roles)
            .join(models.Role, user_roles.c.role_id == models.Role.id)
            .outerjoin(role_permissions, role_permissions.c.role_id == models.Role.id)
            .outerjoin(models.Permission, role_permissions.c.permission_id == models.Permission.id)
            .where(user_roles.c.user_id == user_id, models.Role.workspace_id.in_(list(workspace_ids)))
        )

        grouped: dict[int, list[tuple[str, str | None, str | None]]] = {}
        for ws_id, role_name, resource, action in rows.all():
            grouped.setdefault(ws_id, []).append((role_name, resource, action))
        for ws_id, ws_rows in grouped.items():
            result[ws_id] = _collect_rbac(ws_rows)
        return result


def _collect_rbac(
    rows: Sequence[tuple[str, str | None, str | None]],
) -> tuple[list[str], list[dict[str, str]]]:
    """Fold ``(role_name, resource, action)`` rows into deduped roles + permissions.

    The outer joins above emit one row per role×permission pair (and a single row
    with NULL resource/action for a role that carries none), so both lists are
    deduped here while preserving first-seen order.
    """
    role_names: list[str] = []
    seen_roles: set[str] = set()
    permissions: list[dict[str, str]] = []
    seen_permissions: set[tuple[str, str]] = set()

    for role_name, resource, action in rows:
        if role_name not in seen_roles:
            seen_roles.add(role_name)
            role_names.append(role_name)
        if resource is None or action is None:
            continue
        key = (resource, action)
        if key not in seen_permissions:
            seen_permissions.add(key)
            permissions.append({"resource": resource, "action": action})

    return role_names, permissions


class PermissionRepository(BaseRepository[models.Permission]):
    def __init__(self) -> None:
        super().__init__(models.Permission)

    async def get_by_name(self, session: AsyncSession, name: str) -> models.Permission | None:
        return await self.get_by(session, name=name)

    async def list_searchable(
        self,
        session: AsyncSession,
        params: PaginationSortParams,
        *,
        search: str | None = None,
    ) -> tuple[Sequence[models.Permission], int]:
        filters: list[sa.ColumnElement[bool]] = []
        if search:
            term = f"%{search}%"
            filters.append(
                sa.or_(
                    models.Permission.name.ilike(term),
                    models.Permission.resource.ilike(term),
                    models.Permission.action.ilike(term),
                    models.Permission.description.ilike(term),
                )
            )
        return await self.list(session, params, filters=filters)

    async def role_ids_with_permission(self, session: AsyncSession, permission_id: int) -> Sequence[int]:
        result = await session.execute(
            sa.select(role_permissions.c.role_id).where(role_permissions.c.permission_id == permission_id)
        )
        return result.scalars().all()
