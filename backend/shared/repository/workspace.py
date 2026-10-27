from __future__ import annotations

import typing
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, selectinload

from shared import models
from shared.core.errors import BaseAPIException
from shared.core.pagination import PaginationSortParams
from shared.core.social import SocialProvider
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

    async def get_by_slug(
        self, session: AsyncSession, slug: str, *where: sa.ColumnElement[bool]
    ) -> models.Workspace | None:
        """``slug``'s workspace if it also matches ``where``, with its effective grids."""
        result = await session.execute(
            sa.select(models.Workspace)
            .options(*self.default_grid_options())
            .where(models.Workspace.slug == slug, *where)
        )
        workspace = result.scalar_one_or_none()
        await self.load_effective_grid_versions(session, [workspace] if workspace is not None else [])
        return workspace

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
        workspace = await self.get(session, workspace_id, options=self.default_grid_options())
        await self.load_effective_grid_versions(session, [workspace] if workspace is not None else [])
        return workspace

    async def lock_by_id(self, session: AsyncSession, workspace_id: int) -> int | None:
        """``SELECT id ... FOR NO KEY UPDATE`` — serialize concurrent writers on one workspace.

        Used by the division-grid import paths, where two imports into the same
        workspace must not interleave. NO KEY: the FK inserts of rows referencing the
        workspace (tournaments, grids) take FOR KEY SHARE and go on meanwhile. The
        projection is deliberate: the caller wants the lock, not the row.
        """
        return await session.scalar(
            sa.select(models.Workspace.id).where(models.Workspace.id == workspace_id).with_for_update(key_share=True)
        )

    async def set_default_grid_version(
        self, session: AsyncSession, workspace: models.Workspace, *, discipline: str, version_id: int
    ) -> None:
        """Atomic per-game upsert: another discipline's activation cannot be overwritten."""
        assignment = models.WorkspaceDivisionGridDefault
        stmt = pg_insert(assignment).values(workspace_id=workspace.id, discipline=discipline, version_id=version_id)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[assignment.workspace_id, assignment.discipline],
                set_={"version_id": stmt.excluded.version_id},
            )
        )
        await session.refresh(workspace, ["division_grid_defaults"])
        await self.load_effective_grid_versions(session, [workspace])

    async def clear_default_grid_version(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        version_ids: Sequence[int],
    ) -> None:
        """Remove only assignments pointing at the versions being deleted."""
        if not version_ids:
            return
        await session.execute(
            sa.delete(models.WorkspaceDivisionGridDefault).where(
                models.WorkspaceDivisionGridDefault.workspace_id == workspace_id,
                models.WorkspaceDivisionGridDefault.version_id.in_(tuple(version_ids)),
            )
        )

    async def list_ordered(self, session: AsyncSession, *where: sa.ColumnElement[bool]) -> Sequence[models.Workspace]:
        """Workspaces matching ``where``, ordered by id: list rows, so no effective grids (versions and tiers).

        Filter here, never over the result.
        """
        result = await session.execute(
            sa.select(models.Workspace)
            .options(*self.default_grid_options())
            .where(*where)
            .order_by(models.Workspace.id.asc())
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

    async def load_effective_grid_versions(self, session: AsyncSession, workspaces: Sequence[models.Workspace]) -> None:
        """Resolve public payloads in three batched queries, deduplicating shared versions.

        Explicit selections remain separate from same-game system fallbacks. No
        synthetic version represents a native ladder, and no async lazy read is
        deferred into synchronous WorkspaceRead serialization.
        """
        if not workspaces:
            return
        disciplines = {
            code
            for workspace in workspaces
            for code in (*workspace.disciplines_enabled, *workspace.default_division_grid_versions)
        }
        system = dict(
            (
                await session.execute(
                    sa.select(models.DivisionGrid.discipline, sa.func.min(models.DivisionGridVersion.id))
                    .join(models.DivisionGridVersion, models.DivisionGridVersion.grid_id == models.DivisionGrid.id)
                    .where(models.DivisionGrid.workspace_id.is_(None), models.DivisionGrid.discipline.in_(disciplines))
                    .group_by(models.DivisionGrid.discipline)
                )
            ).all()
        )
        version_ids = set(system.values())
        for workspace in workspaces:
            version_ids.update(workspace.default_division_grid_versions.values())
        rows = (
            (
                await session.execute(
                    sa.select(
                        models.DivisionGridVersion, models.DivisionGrid.discipline, models.DivisionGrid.workspace_id
                    )
                    .join(models.DivisionGrid, models.DivisionGrid.id == models.DivisionGridVersion.grid_id)
                    .options(selectinload(models.DivisionGridVersion.tiers))
                    .where(models.DivisionGridVersion.id.in_(version_ids))
                )
            ).all()
            if version_ids
            else []
        )
        versions = {version.id: (version, discipline, owner) for version, discipline, owner in rows}
        for workspace in workspaces:
            explicit = workspace.default_division_grid_versions
            effective = {}
            for code in set(workspace.disciplines_enabled) | explicit.keys():
                version_id = explicit.get(code, system.get(code))
                if version_id is None:
                    continue
                row = versions.get(version_id)
                if row is None or row[1] != code or row[2] not in (None, workspace.id):
                    raise BaseAPIException(
                        status_code=422, detail="division_grid_discipline_mismatch: invalid workspace default"
                    )
                effective[code] = row[0]
            workspace._effective_grid_versions = effective

    @staticmethod
    def default_grid_options() -> list[object]:
        return [selectinload(models.Workspace.division_grid_defaults)]


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
                models.WorkspaceMember.removed_at.is_(None),
                models.WorkspaceMember.observed_only.is_(False),
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

    async def discord_ids(self, session: AsyncSession, member_ids: Sequence[int]) -> Sequence[sa.Row[tuple[int, str]]]:
        """``(member_id, discord_id)`` for each of ``member_ids`` whose account linked a Discord.

        One batched read down the identity chain: workspace member -> player ->
        auth user -> ``auth.oauth_connections``.
        """
        return (
            await session.execute(
                sa.select(models.WorkspaceMember.id, models.OAuthConnection.provider_user_id)
                .select_from(models.WorkspaceMember)
                .join(models.User, models.User.id == models.WorkspaceMember.player_id)
                .join(models.OAuthConnection, models.OAuthConnection.auth_user_id == models.User.auth_user_id)
                .where(
                    models.WorkspaceMember.id.in_(member_ids),
                    models.OAuthConnection.provider == SocialProvider.DISCORD,
                    models.OAuthConnection.provider_user_id.is_not(None),
                )
            )
        ).all()

    async def auth_user_ids(self, session: AsyncSession, member_ids: Sequence[int]) -> dict[int, int]:
        """``{member_id: auth_user_id}`` for each of ``member_ids`` with a site account behind its player.

        The identity chain of :meth:`discord_ids`, one step shorter; a shadow player (no account) is left out.
        """
        if not member_ids:
            return {}
        rows = await session.execute(
            sa.select(models.WorkspaceMember.id, models.User.auth_user_id)
            .select_from(models.WorkspaceMember)
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .where(models.WorkspaceMember.id.in_(member_ids), models.User.auth_user_id.is_not(None))
        )
        return {int(member_id): int(auth_user_id) for member_id, auth_user_id in rows.all()}

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
            .where(
                models.User.auth_user_id == auth_user_id,
                models.WorkspaceMember.removed_at.is_(None),
                models.WorkspaceMember.observed_only.is_(False),
            )
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
                models.WorkspaceMember.removed_at.is_(None),
                models.WorkspaceMember.observed_only.is_(False),
                models.User.auth_user_id == auth_user_id,
            )
            .limit(1)
        )
        return found is True

    async def workspace_ids_for_player(self, session: AsyncSession, player_id: int) -> Sequence[int]:
        """Workspaces this player is anchored to, ids only.

        Feeds the role-autofill run after a player↔auth-user link: the caller
        needs the scope of each membership row, never the row itself.
        """
        result = await session.scalars(
            sa.select(models.WorkspaceMember.workspace_id).where(
                models.WorkspaceMember.player_id == player_id,
                models.WorkspaceMember.removed_at.is_(None),
                models.WorkspaceMember.observed_only.is_(False),
            )
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
        workspace roles; each auth user's ``player`` rides the page's own join.

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

        page_query = (
            self._members_filter(
                sa.select(models.WorkspaceMember, models.AuthUser),
                workspace_id=workspace_id,
                search=search,
                role_id=role_id,
                exclude_role_id=exclude_role_id,
            )
            .options(contains_eager(models.AuthUser.player))
            .order_by(*order_cols)
        )
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

        Auth-linked only (INNER JOIN ``players.user`` + ``auth.user``): a row
        with no auth identity is a tournament participant, not an RBAC member.
        """
        base = (
            base.join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .join(models.AuthUser, models.AuthUser.id == models.User.auth_user_id)
            .where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.WorkspaceMember.removed_at.is_(None),
                models.WorkspaceMember.observed_only.is_(False),
            )
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

    async def member_ids_by_player(
        self, session: AsyncSession, *, workspace_id: int, player_ids: set[int]
    ) -> dict[int, int]:
        """``player_id -> member.id`` for the rows that already exist, removed or not; creates nothing."""
        rows = await session.execute(
            sa.select(models.WorkspaceMember.player_id, models.WorkspaceMember.id).where(
                models.WorkspaceMember.workspace_id == workspace_id,
                models.WorkspaceMember.player_id.in_(player_ids),
            )
        )
        return dict(rows.tuples().all())


async def insert_missing_workspace_members(
    session: AsyncSession,
    pairs: Sequence[tuple[int, int]],
    *,
    observed_only: bool = False,
) -> dict[tuple[int, int], int]:
    """Create absent (workspace, player) anchors; never revive, grant roles or commit.

    ``observed_only`` marks anchors made by a stats observation: not a membership until a real admission.
    """
    from shared.services.stats_evidence import (
        OWNER_BATCH,
        capture_stats_evidence,
        owner_scopes,
        stage_stats_evidence,
    )

    if not pairs:
        return {}
    existing = await session.execute(
        sa.select(models.WorkspaceMember.workspace_id, models.WorkspaceMember.player_id).where(
            sa.tuple_(models.WorkspaceMember.workspace_id, models.WorkspaceMember.player_id).in_(pairs)
        )
    )
    missing = sorted(set(pairs) - set(existing.tuples().all()))
    created = {}
    for offset in range(0, len(missing), OWNER_BATCH):
        batch = missing[offset : offset + OWNER_BATCH]
        ids = list(
            await session.scalars(
                sa.text(
                    "SELECT nextval(pg_get_serial_sequence('workspace_member','id')) FROM generate_series(1,:count)"
                ),
                {"count": len(batch)},
            )
        )
        # Separate sealed captures let ON CONFLICT discard race losers without
        # claiming that their reserved, still-absent owner ids were created.
        before = {
            member_id: await capture_stats_evidence(session, scopes=owner_scopes("member", (member_id,)))
            for member_id in ids
        }
        rows = (
            await session.execute(
                pg_insert(models.WorkspaceMember)
                .values(
                    [
                        {
                            "id": member_id,
                            "workspace_id": workspace_id,
                            "player_id": player_id,
                            "observed_only": observed_only,
                        }
                        for member_id, (workspace_id, player_id) in zip(ids, batch, strict=True)
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_workspace_member_workspace_player")
                .returning(
                    models.WorkspaceMember.id, models.WorkspaceMember.workspace_id, models.WorkspaceMember.player_id
                )
            )
        ).all()
        for member_id, workspace_id, player_id in rows:
            after = await capture_stats_evidence(session, scopes=owner_scopes("member", (member_id,)))
            await stage_stats_evidence(
                session,
                operation="stats.member_create",
                before=before[member_id],
                after=after,
                workspace_id=workspace_id,
                entity_type="workspace_member",
                entity_id=member_id,
            )
            created[(workspace_id, player_id)] = member_id
    return created


async def insert_observation_members(session: AsyncSession, pairs: Sequence[tuple[int, int]]) -> None:
    """Anchor observations to (workspace, player) pairs without conferring any membership.

    New anchors are ``observed_only``: membership/visibility reads and the link-time role autofill skip them, no role or
    rank is granted and ``removed_at`` stays NULL (nothing was removed). Existing rows are untouched: an admitted member
    stays admitted, a genuinely removed one stays removed. A real admission (``get_or_create_workspace_member``) clears
    the flag.
    """
    await insert_missing_workspace_members(session, pairs, observed_only=True)


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
    created = await insert_missing_workspace_members(session, [(workspace_id, player_id)])
    member_id = created.get((workspace_id, player_id))
    if member_id is not None:
        await session.flush()
        member = await session.get(models.WorkspaceMember, member_id)
        assert member is not None
    else:
        member = await WorkspaceMemberRepository().get_by_player(
            session, workspace_id=workspace_id, player_id=player_id
        )
        if member is None:
            raise RuntimeError(
                f"get_or_create_workspace_member: no row after ON CONFLICT DO NOTHING "
                f"(workspace_id={workspace_id}, player_id={player_id})"
            )
        if member.removed_at is None and not member.observed_only:
            return member
        # Re-adding a removed member reuses the row (its roster history hangs on it); admitting an observation-only
        # anchor makes it a real member. Both are real admissions.
        member.removed_at = None
        member.observed_only = False
        await session.flush()
    # Autofill the baseline ``member`` RBAC role for a brand-new (or re-added) anchor of an
    # auth-linked player: the members screen treats every auth-linked row as
    # an RBAC member, so such a row must not be role-less. Fires ONLY on a
    # real insert or a revival (not idempotent hits) and ONLY when the player has an auth
    # account; the helper is additive (never downgrades a later ``player`` /
    # explicit grant). The new membership changes the account's RBAC payload (its
    # workspace list) whether or not a role was granted, so identity is told in
    # this transaction. Local import avoids any shared.repository<->shared.rbac
    # import-time coupling on this widely-imported module.
    from shared.rbac.bootstrap import assign_default_member_role_if_roleless, stage_rbac_change

    auth_user_id = await session.scalar(sa.select(models.User.auth_user_id).where(models.User.id == player_id))
    if auth_user_id is not None:
        await assign_default_member_role_if_roleless(session, user_id=auth_user_id, workspace_id=workspace_id)
        await stage_rbac_change(session, [auth_user_id], change="added", workspace_id=workspace_id)
    return member


async def resolve_workspace_member_id(
    session: AsyncSession,
    *,
    tournament_id: int,
    player_id: int,
) -> int | None:
    """The ``workspace_member`` anchor for a roster player being created,
    resolved from the tournament they are joining — or ``None`` if
    ``tournament_id`` names no tournament.

    ``tournament-service`` (admin player CRUD) and ``stats-service`` (roster
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

    async def rbac_for_user(
        self,
        session: AsyncSession,
        user_id: int,
        workspace_ids: Sequence[int],
    ) -> tuple[tuple[list[str], list[dict[str, str]]], dict[int, tuple[list[str], list[dict[str, str]]]]]:
        """Global (``workspace_id IS NULL``) RBAC plus ``workspace_rbac_for_user``, in ONE statement.

        The token path's cache miss. Explicit joins rather than relationship
        traversal: an ORM lazy-load would raise under AsyncSession.
        """
        scope = models.Role.workspace_id.is_(None)
        if workspace_ids:
            scope = sa.or_(scope, models.Role.workspace_id.in_(list(workspace_ids)))
        grouped = await self._grouped_rbac(session, user_id, scope)
        return _collect_rbac(grouped.get(None, [])), {
            ws_id: _collect_rbac(grouped.get(ws_id, [])) for ws_id in workspace_ids
        }

    async def workspace_rbac_for_user(
        self,
        session: AsyncSession,
        user_id: int,
        workspace_ids: Sequence[int],
    ) -> dict[int, tuple[list[str], list[dict[str, str]]]]:
        """Role names + deduped permissions, keyed by workspace id.

        Every requested workspace is present in the result (empty lists when the
        user holds no role there), so callers never need a ``.get`` default.
        """
        if not workspace_ids:
            return {}
        grouped = await self._grouped_rbac(session, user_id, models.Role.workspace_id.in_(list(workspace_ids)))
        return {ws_id: _collect_rbac(grouped.get(ws_id, [])) for ws_id in workspace_ids}

    @staticmethod
    async def _grouped_rbac(
        session: AsyncSession,
        user_id: int,
        scope: sa.ColumnElement[bool],
    ) -> dict[int | None, list[tuple[str, str | None, str | None]]]:
        """``(role_name, resource, action)`` rows of the user's roles in ``scope``, by role workspace."""
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
            .where(user_roles.c.user_id == user_id, scope)
        )
        grouped: dict[int | None, list[tuple[str, str | None, str | None]]] = {}
        for ws_id, role_name, resource, action in rows.all():
            grouped.setdefault(ws_id, []).append((role_name, resource, action))
        return grouped


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
