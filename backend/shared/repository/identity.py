"""Data access for the identity domain (auth users, sessions, OAuth, RBAC denies) and the player profiles anchored to it.

Every SQL statement the identity service issues against these tables lives here.
Services above compose these calls and own the transaction boundary; repositories
never commit, never raise HTTP errors, and never make policy decisions.

``UserRepository`` is the only writer of ``players.user`` for every service: a player row is born in
``create_player`` and its account link changes in ``link_auth_user``, nowhere else
(``backend/tests/test_identity_write_ownership.py``).
"""

from __future__ import annotations

import hashlib
from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from typing import Any, ClassVar
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, noload, selectinload
from sqlalchemy.orm.strategy_options import _AbstractLoad

from shared import models
from shared.core import secretbox
from shared.core.pagination import PaginationSortParams, SortOrder
from shared.core.utils import join_entity
from shared.models.identity.rbac import user_lacks_roles
from shared.repository.base import BaseRepository

#: ``players.user.name`` cap; a collision suffix is fitted inside it.
_MAX_PLAYER_NAME = 255


class UserRepository(BaseRepository[models.User]):
    """``players.user`` — the tournament identity an auth account is anchored to."""

    def __init__(self) -> None:
        super().__init__(models.User)

    async def get_by_name(self, session: AsyncSession, name: str) -> models.User | None:
        return await self.get_by(session, name=name)

    async def get_by_auth_user_id(self, session: AsyncSession, auth_user_id: int) -> models.User | None:
        return await self.get_by(session, auth_user_id=auth_user_id)

    async def get_id_by_auth_user_id(self, session: AsyncSession, auth_user_id: int) -> int | None:
        """Player id only — avoids hydrating the row when just the id is needed."""
        return await session.scalar(sa.select(models.User.id).where(models.User.auth_user_id == auth_user_id).limit(1))

    async def create_player(
        self,
        session: AsyncSession,
        *,
        name: str,
        auth_user_id: int | None = None,
        identity: tuple[str, str] | None = None,
    ) -> models.User:
        """The one place a ``players.user`` row is born.

        ``name`` is UNIQUE and proves nothing, so a taken one gets a deterministic suffix: the auth id when the player
        is born linked, else ``provider:hash`` of the ``identity`` (provider, normalized handle) it is named after.
        Deterministic so two concurrent creations for different people never race to the same suffix. With neither,
        the caller has already refused a taken name and the unique index is the backstop.
        """
        name = name[:_MAX_PLAYER_NAME]
        if await self.get_by_name(session, name) is not None:
            if auth_user_id is not None:
                suffix = f" ({auth_user_id})"
            elif identity is not None:
                provider, normalized = identity
                suffix = f" ({provider}:{hashlib.sha1(normalized.encode()).hexdigest()[:8]})"  # noqa: S324 - a label
            else:
                suffix = ""
            name = name[: _MAX_PLAYER_NAME - len(suffix)] + suffix
        return await self.create(session, models.User(name=name, auth_user_id=auth_user_id))

    async def ensure_for_auth_user(
        self,
        session: AsyncSession,
        *,
        auth_user_id: int,
        name_hint: str | None,
    ) -> models.User:
        """Return the ``players.user`` linked to ``auth_user_id``, provisioning a
        bare one if none exists (the identity backbone every auth user needs to
        anchor a ``workspace_member``).

        Idempotent — returns the existing link unchanged. The ``name_hint``
        (username/email) falls back to ``user-<id>``; a taken name is suffixed
        with the auth id (``create_player``).
        """
        existing = await self.get_by_auth_user_id(session, auth_user_id)
        if existing is not None:
            return existing
        return await self.create_player(
            session, name=(name_hint or "").strip() or f"user-{auth_user_id}", auth_user_id=auth_user_id
        )

    async def link_auth_user(self, session: AsyncSession, player: models.User, auth_user_id: int | None) -> None:
        """Set (or, with ``None``, clear) the player↔account link. Unique: one player per account."""
        player.auth_user_id = auth_user_id
        await session.flush()

    async def set_avatar(self, session: AsyncSession, *, auth_user_id: int, avatar_url: str | None) -> None:
        """Point the avatar of the player linked to ``auth_user_id`` at ``avatar_url``; a no-op without one."""
        await session.execute(
            sa.update(models.User).where(models.User.auth_user_id == auth_user_id).values(avatar_url=avatar_url)
        )

    async def avatar_urls_by_auth_user(
        self,
        session: AsyncSession,
        auth_user_ids: Collection[int],
    ) -> dict[int, str | None]:
        """Avatars keyed by the linked account — two columns, one round trip.

        For faces beside names already in hand (a chat transcript, a presence
        list); an account without a player is simply absent.
        """
        if not auth_user_ids:
            return {}
        rows = await session.execute(
            sa.select(models.User.auth_user_id, models.User.avatar_url).where(
                models.User.auth_user_id.in_(set(auth_user_ids))
            )
        )
        return {row.auth_user_id: row.avatar_url for row in rows}

    # The one entity token that selects the unified `user.social_accounts` relationship.
    IDENTITY_ENTITY_TOKENS: ClassVar[tuple[str, ...]] = ("social_accounts",)

    @staticmethod
    def identity_options(in_entities: Sequence[str], child: _AbstractLoad | None = None) -> list[_AbstractLoad]:
        """Eager-load option for `.get(..., options=...)` when any identity entity token was requested."""
        if any(name in in_entities for name in UserRepository.IDENTITY_ENTITY_TOKENS):
            return [join_entity(child, models.User.social_accounts)]
        return []


class SocialAccountRepository(BaseRepository[models.SocialAccount]):
    """Unified player social identities (battlenet/discord/twitch/boosty/…)."""

    def __init__(self) -> None:
        super().__init__(models.SocialAccount)

    async def list_by_user(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        providers: Sequence[str] | None = None,
    ) -> Sequence[models.SocialAccount]:
        query = self.select().where(models.SocialAccount.user_id == user_id)
        if providers:
            query = query.where(models.SocialAccount.provider.in_(list(providers)))
        query = query.order_by(
            models.SocialAccount.provider,
            models.SocialAccount.is_primary.desc(),
            models.SocialAccount.id,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def list_by_provider(
        self,
        session: AsyncSession,
        provider: str,
        *,
        ids: Collection[int] | None = None,
    ) -> Sequence[models.SocialAccount]:
        """Every account of one provider, or only the given ones of it."""
        query = self.select().where(models.SocialAccount.provider == provider)
        if ids is not None:
            query = query.where(models.SocialAccount.id.in_(list(ids)))
        result = await session.execute(query.order_by(models.SocialAccount.id))
        return result.unique().scalars().all()

    async def get_by_provider_subject(
        self,
        session: AsyncSession,
        *,
        provider: str,
        provider_user_id: str,
    ) -> models.SocialAccount | None:
        return await self.get_by(session, provider=provider, provider_user_id=provider_user_id)

    async def find_by_handle(
        self,
        session: AsyncSession,
        *,
        provider: str,
        username_normalized: str,
        user_id: int | None = None,
    ) -> models.SocialAccount | None:
        filters: dict[str, object] = {
            "provider": provider,
            "username_normalized": username_normalized,
        }
        if user_id is not None:
            filters["user_id"] = user_id
        return await self.get_by(session, **filters)

    async def get_owned(
        self,
        session: AsyncSession,
        *,
        account_id: int,
        user_id: int,
    ) -> models.SocialAccount | None:
        """One account, but only if ``user_id`` owns it.

        Ownership is part of the lookup rather than a check the caller does
        after: every mutation of a social identity is scoped to its player, and
        a fetch-then-compare leaves room for a caller to forget the compare.
        """
        return await self.get_by(session, id=account_id, user_id=user_id)

    async def has_any_for_provider(self, session: AsyncSession, *, user_id: int, provider: str) -> bool:
        """Whether the player already carries an account for this provider.

        Decides ``is_primary`` on insert: the first account of a provider is
        the primary one.
        """
        return await self.exists(session, user_id=user_id, provider=provider)

    async def find_handle_clash(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        provider: str,
        username_normalized: str,
        exclude_id: int,
    ) -> int | None:
        """Id of the player's OTHER account already holding this handle, if any."""
        return await session.scalar(
            sa.select(models.SocialAccount.id).where(
                models.SocialAccount.user_id == user_id,
                models.SocialAccount.provider == provider,
                models.SocialAccount.username_normalized == username_normalized,
                models.SocialAccount.id != exclude_id,
            )
        )

    async def oldest_for_provider(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        provider: str,
    ) -> models.SocialAccount | None:
        """The player's longest-held account for a provider — the primary heir."""
        result = await session.execute(
            self.select()
            .where(models.SocialAccount.user_id == user_id, models.SocialAccount.provider == provider)
            .order_by(models.SocialAccount.created_at, models.SocialAccount.id)
            .limit(1)
        )
        return result.scalars().first()

    async def clear_primary_except(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        provider: str,
        keep_id: int,
    ) -> None:
        """Demote every other primary of this (player, provider).

        A set-based update, not a read-then-write loop: "at most one primary"
        is the invariant, and doing it in one statement means no window where
        two rows claim it.
        """
        await session.execute(
            sa.update(models.SocialAccount)
            .where(
                models.SocialAccount.user_id == user_id,
                models.SocialAccount.provider == provider,
                models.SocialAccount.id != keep_id,
                models.SocialAccount.is_primary.is_(True),
            )
            .values(is_primary=False)
        )

    async def list_handles(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        provider: str,
    ) -> Sequence[str]:
        """Raw handles a player carries for one provider (ownership matching)."""
        result = await session.execute(
            sa.select(models.SocialAccount.username).where(
                models.SocialAccount.user_id == user_id,
                models.SocialAccount.provider == provider,
            )
        )
        return result.scalars().all()

    async def find_player_by_subject(
        self,
        session: AsyncSession,
        *,
        provider: str,
        provider_user_id: str,
    ) -> models.User | None:
        """The player pinned to this exact, OAuth-proven provider subject."""
        result = await session.execute(
            sa.select(models.User)
            .join(models.SocialAccount, models.SocialAccount.user_id == models.User.id)
            .where(
                models.SocialAccount.provider == provider,
                models.SocialAccount.provider_user_id == provider_user_id,
            )
        )
        return result.unique().scalars().first()

    async def find_players_by_handle(
        self,
        session: AsyncSession,
        *,
        provider: str,
        username_normalized: str,
    ) -> Sequence[models.User]:
        """Every player carrying this normalized handle for the provider."""
        result = await session.execute(
            sa.select(models.User)
            .join(models.SocialAccount, models.SocialAccount.user_id == models.User.id)
            .where(
                models.SocialAccount.provider == provider,
                models.SocialAccount.username_normalized == username_normalized,
            )
        )
        return result.unique().scalars().all()

    async def release_foreign_subject(
        self,
        session: AsyncSession,
        *,
        provider: str,
        provider_user_id: str,
        keep_user_id: int,
    ) -> int:
        """Drop the verified mark + subject pin from every OTHER player holding
        this provider subject. Returns the number of rows released."""
        result = await session.execute(
            sa.update(models.SocialAccount)
            .where(
                models.SocialAccount.provider == provider,
                models.SocialAccount.provider_user_id == provider_user_id,
                models.SocialAccount.user_id != keep_user_id,
            )
            .values(is_verified=False, provider_user_id=None)
        )
        return result.rowcount or 0

    async def unverify_for_player(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        provider: str | None = None,
        provider_user_id: str | None = None,
    ) -> int:
        """Clear ``is_verified``/``provider_user_id`` for a player's accounts.

        The handle row itself is kept (re-verify by re-linking). Narrowed to one
        provider and/or one subject when given; otherwise every verified account
        of the player is released (self-delete).
        """
        query = sa.update(models.SocialAccount).where(
            models.SocialAccount.user_id == user_id,
            models.SocialAccount.is_verified.is_(True),
        )
        if provider is not None:
            query = query.where(models.SocialAccount.provider == provider)
        if provider_user_id is not None:
            query = query.where(models.SocialAccount.provider_user_id == provider_user_id)
        result = await session.execute(query.values(is_verified=False, provider_user_id=None))
        return result.rowcount or 0


class SocialAccountVisibilityRepository(BaseRepository[models.SocialAccountVisibility]):
    def __init__(self) -> None:
        super().__init__(models.SocialAccountVisibility)

    async def get_for_scope(
        self,
        session: AsyncSession,
        *,
        account_id: int,
        workspace_id: int | None,
    ) -> models.SocialAccountVisibility | None:
        """The row for one (account, scope). ``workspace_id=None`` is the global
        scope and matches ``IS NULL``, not "any workspace"."""
        return await self.get_by(session, account_id=account_id, workspace_id=workspace_id)


class AuthUserRepository(BaseRepository[models.AuthUser]):
    def __init__(self) -> None:
        super().__init__(models.AuthUser)

    @staticmethod
    def rbac_options(*, include_player: bool = False) -> list[_AbstractLoad]:
        """Loader options for a user whose RBAC is about to be read.

        ``AuthUser.roles`` is already ``lazy="selectin"``; the permissions behind
        each role are not, so they are the one thing that must be requested here
        or every ``role.permissions`` access would lazy-load (and blow up under
        AsyncSession). ``oauth_connections`` is also ``lazy="selectin"`` but no
        identity flow reads the relationship — every OAuth lookup goes through
        ``OAuthConnectionRepository`` — so it is suppressed to keep one extra
        round trip off every user load, including the per-request token path.
        """
        options: list[_AbstractLoad] = [
            selectinload(models.AuthUser.roles).selectinload(models.Role.permissions),
            noload(models.AuthUser.oauth_connections),
        ]
        if include_player:
            options.append(selectinload(models.AuthUser.player))
        return options

    @staticmethod
    def identity_options(*, include_player: bool = False) -> list[_AbstractLoad]:
        """Loader options for a user whose RBAC comes from cache, not the row.

        Skips role/permission hydration entirely — the caller already holds the
        cached RBAC payload — so the load is a single row fetch instead of the
        row plus two collection round trips.
        """
        options: list[_AbstractLoad] = [
            noload(models.AuthUser.roles),
            noload(models.AuthUser.oauth_connections),
        ]
        if include_player:
            options.append(selectinload(models.AuthUser.player))
        return options

    async def get_with_rbac(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        include_player: bool = False,
    ) -> models.AuthUser | None:
        return await self.get(session, user_id, options=self.rbac_options(include_player=include_player))

    async def get_identity(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        include_player: bool = False,
    ) -> models.AuthUser | None:
        return await self.get(session, user_id, options=self.identity_options(include_player=include_player))

    async def get_identity_by_email(self, session: AsyncSession, email: str) -> models.AuthUser | None:
        return await self.get_by(session, options=self.identity_options(), email=email)

    async def get_with_roles(self, session: AsyncSession, user_id: int) -> models.AuthUser | None:
        return await self.get(session, user_id, options=[selectinload(models.AuthUser.roles)])

    async def email_or_username_taken(self, session: AsyncSession, *, email: str, username: str) -> bool:
        """One query for both registration collisions.

        The caller reports a single neutral message for either hit (no account
        enumeration), so there is nothing to gain from knowing which matched.
        """
        return (
            await session.scalar(
                sa.select(sa.literal(True))
                .select_from(models.AuthUser)
                .where(
                    sa.or_(
                        models.AuthUser.email == email,
                        sa.func.lower(models.AuthUser.username) == username.lower(),
                    )
                )
                .limit(1)
            )
        ) is True

    async def email_taken(self, session: AsyncSession, email: str, *, exclude_user_id: int | None = None) -> bool:
        query = sa.select(sa.literal(True)).select_from(models.AuthUser).where(models.AuthUser.email == email).limit(1)
        if exclude_user_id is not None:
            query = query.where(models.AuthUser.id != exclude_user_id)
        return (await session.scalar(query)) is True

    async def username_taken(self, session: AsyncSession, username: str, *, exclude_user_id: int) -> bool:
        """Case-insensitive: ``Anak`` and ``anak`` are the same name to a reader."""
        query = (
            sa.select(sa.literal(True))
            .select_from(models.AuthUser)
            .where(
                sa.func.lower(models.AuthUser.username) == username.lower(),
                models.AuthUser.id != exclude_user_id,
            )
            .limit(1)
        )
        return (await session.scalar(query)) is True

    async def usernames_with_prefix(self, session: AsyncSession, prefix: str) -> set[str]:
        """Every taken username starting with ``prefix``, lowercased.

        Lets the OAuth signup pick a free ``name``/``name1``/``name2`` suffix in
        one round trip instead of probing the table once per candidate. Matched
        case-insensitively, like every other username collision check.
        """
        result = await session.execute(
            sa.select(sa.func.lower(models.AuthUser.username)).where(models.AuthUser.username.ilike(f"{prefix}%"))
        )
        return set(result.scalars().all())

    async def list_with_rbac(
        self,
        session: AsyncSession,
        params: PaginationSortParams,
        *,
        search: str | None = None,
        role_id: int | None = None,
        exclude_role_id: Sequence[int] | None = None,
        is_active: bool | None = None,
        is_superuser: bool | None = None,
        include_player: bool = False,
        member_of_workspace_id: int | None = None,
    ) -> tuple[Sequence[models.AuthUser], int]:
        """``member_of_workspace_id`` keeps only that workspace's active members (removed and observed-only
        rows are not members), reached through the player each account is linked to."""
        filters: list[sa.ColumnElement[bool]] = []
        if search:
            term = f"%{search}%"
            filters.append(
                sa.or_(
                    models.AuthUser.email.ilike(term),
                    models.AuthUser.username.ilike(term),
                    models.AuthUser.first_name.ilike(term),
                    models.AuthUser.last_name.ilike(term),
                )
            )
        if role_id is not None:
            filters.append(models.AuthUser.roles.any(models.Role.id == role_id))
        if exclude_role_id:
            filters.append(user_lacks_roles(models.AuthUser.id, exclude_role_id))
        if is_active is not None:
            filters.append(models.AuthUser.is_active == is_active)
        if is_superuser is not None:
            filters.append(models.AuthUser.is_superuser == is_superuser)
        if member_of_workspace_id is not None:
            filters.append(
                models.AuthUser.id.in_(
                    sa.select(models.User.auth_user_id)
                    .join(models.WorkspaceMember, models.WorkspaceMember.player_id == models.User.id)
                    .where(
                        models.WorkspaceMember.workspace_id == member_of_workspace_id,
                        models.WorkspaceMember.removed_at.is_(None),
                        models.WorkspaceMember.observed_only.is_(False),
                    )
                )
            )

        return await self.list(
            session,
            params,
            options=self.rbac_options(include_player=include_player),
            filters=filters,
        )

    async def lookup(
        self, session: AsyncSession, params: PaginationSortParams, *, search: str
    ) -> tuple[Sequence[models.AuthUser], int]:
        """Accounts whose username contains ``search`` (wildcards escaped) or whose email IS ``search``.

        Identity-only rows with their player (the avatar): the caller shows who someone is, nothing more.
        """
        return await self.list(
            session,
            params,
            options=self.identity_options(include_player=True),
            filters=[
                sa.or_(
                    models.AuthUser.username.icontains(search, autoescape=True),
                    sa.func.lower(models.AuthUser.email) == search.lower(),
                )
            ],
        )

    async def lock(self, session: AsyncSession, user_id: int) -> None:
        """``SELECT … FOR UPDATE`` on the account row, until the transaction ends.

        Serializes writers that count an account's children before removing one (its last sign-in method);
        reads only the id, so no loaded instance is refreshed underneath the caller.
        """
        await session.execute(sa.select(models.AuthUser.id).where(models.AuthUser.id == user_id).with_for_update())


class RefreshTokenRepository(BaseRepository[models.RefreshToken]):
    """Refresh tokens, and the logical sessions they aggregate into.

    Revocation is expressed as set-based ``UPDATE ... RETURNING session_id``:
    one statement that both flips the rows and reports which session ids need
    their access tokens blacklisted. The ORM alternative (SELECT the rows, flip
    each attribute, flush) costs a round trip plus one UPDATE per row on the
    logout path for no gain — nothing here needs the hydrated objects.

    Every revocation first locks the owning ``auth.user`` row, the lock a
    rotation takes too (it loads the owner ``FOR UPDATE`` before consuming its
    token). A revoking UPDATE that started before a concurrent rotation
    committed would otherwise scan a snapshot without the successor token and
    leave it live: a logout that does not log out.
    """

    def __init__(self) -> None:
        super().__init__(models.RefreshToken)

    @staticmethod
    def _is_live(now: datetime) -> sa.ColumnElement[bool]:
        return sa.and_(models.RefreshToken.is_revoked.is_(False), models.RefreshToken.expires_at > now)

    @staticmethod
    def _status(now: datetime) -> sa.ColumnElement[str]:
        """A token's session status, the one ``SessionService`` reports."""
        return sa.case(
            (models.RefreshToken.is_revoked.is_(True), "revoked"),
            (models.RefreshToken.expires_at <= now, "expired"),
            else_="active",
        )

    async def _lock_owner(self, session: AsyncSession, user_id: int) -> None:
        await session.execute(sa.select(models.AuthUser.id).where(models.AuthUser.id == user_id).with_for_update())

    async def latest_for_user(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        now: datetime,
        history_limit: int,
    ) -> Sequence[models.RefreshToken]:
        """The newest token of each of a user's sessions: every live session plus the
        ``history_limit`` most recent ended ones; live first, then newest sign-in first."""
        latest = (
            sa.select(
                models.RefreshToken.id,
                models.RefreshToken.session_started_at,
                models.RefreshToken.created_at,
                self._is_live(now).label("live"),
            )
            .where(models.RefreshToken.user_id == user_id)
            .distinct(models.RefreshToken.session_id)
            .order_by(models.RefreshToken.session_id, models.RefreshToken.created_at.desc())
            .subquery()
        )
        ranked = sa.select(
            latest.c.id,
            latest.c.live,
            sa.func.row_number()
            .over(partition_by=latest.c.live, order_by=(latest.c.session_started_at.desc(), latest.c.created_at.desc()))
            .label("rank"),
        ).subquery()
        result = await session.execute(
            sa.select(models.RefreshToken)
            .join(ranked, ranked.c.id == models.RefreshToken.id)
            .where(sa.or_(ranked.c.live, ranked.c.rank <= history_limit))
            .order_by(
                ranked.c.live.desc(),
                models.RefreshToken.session_started_at.desc(),
                models.RefreshToken.created_at.desc(),
            )
        )
        return result.scalars().all()

    async def latest_in_session(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        session_id: UUID,
    ) -> models.RefreshToken | None:
        """The newest token of one of the user's sessions; its state is the session's."""
        return await session.scalar(
            sa.select(models.RefreshToken)
            .where(models.RefreshToken.user_id == user_id, models.RefreshToken.session_id == session_id)
            .order_by(models.RefreshToken.created_at.desc())
            .limit(1)
        )

    async def get_by_hashes(
        self,
        session: AsyncSession,
        hashes: Sequence[str],
    ) -> models.RefreshToken | None:
        """Any record matching one of the accepted hashes of a raw token."""
        result = await session.execute(
            sa.select(models.RefreshToken).where(models.RefreshToken.token.in_(list(hashes)))
        )
        return result.scalar_one_or_none()

    async def get_active_by_hashes(
        self,
        session: AsyncSession,
        hashes: Sequence[str],
        *,
        now: datetime,
    ) -> models.RefreshToken | None:
        result = await session.execute(
            sa.select(models.RefreshToken)
            .where(models.RefreshToken.token.in_(list(hashes)))
            .where(models.RefreshToken.is_revoked.is_(False))
            .where(models.RefreshToken.expires_at > now)
        )
        return result.scalar_one_or_none()

    async def get_grace_candidate(
        self,
        session: AsyncSession,
        hashes: Sequence[str],
        *,
        now: datetime,
        grace_seconds: int,
    ) -> models.RefreshToken | None:
        """A just-rotated token still inside the rotation-grace window.

        The "session family is still alive" condition is an EXISTS correlated on
        the candidate row, so the whole decision is one statement rather than a
        fetch followed by a liveness probe.
        """
        if grace_seconds <= 0:
            return None

        sibling = sa.orm.aliased(models.RefreshToken)
        alive = (
            sa.select(sa.literal(1))
            .select_from(sibling)
            .where(
                sibling.user_id == models.RefreshToken.user_id,
                sibling.session_id == models.RefreshToken.session_id,
                sibling.is_revoked.is_(False),
            )
            .exists()
        )
        result = await session.execute(
            sa.select(models.RefreshToken)
            .where(models.RefreshToken.token.in_(list(hashes)))
            .where(models.RefreshToken.is_revoked.is_(True))
            .where(models.RefreshToken.expires_at > now)
            .where(models.RefreshToken.revoked_at > now - timedelta(seconds=grace_seconds))
            .where(models.RefreshToken.session_id.is_not(None))
            .where(alive)
        )
        return result.scalar_one_or_none()

    async def revoke_by_hashes(
        self,
        session: AsyncSession,
        hashes: Sequence[str],
        *,
        now: datetime,
    ) -> bool:
        """Revoke one token by its hash. True only when THIS statement revoked it.

        False for an unknown token and for one already revoked -- including by a
        concurrent transaction this UPDATE waited on, so of two racing rotations
        exactly one consumes the token.
        """
        revoked = await session.execute(
            sa.update(models.RefreshToken)
            .where(models.RefreshToken.token.in_(list(hashes)))
            .where(models.RefreshToken.is_revoked.is_(False))
            .values(is_revoked=True, revoked_at=now)
            .returning(models.RefreshToken.id)
        )
        return revoked.scalars().first() is not None

    async def revoke_session(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        session_id: UUID,
        now: datetime,
    ) -> int:
        """Revoke every live token of one logical session; returns the count."""
        await self._lock_owner(session, user_id)
        result = await session.execute(
            sa.update(models.RefreshToken)
            .where(models.RefreshToken.user_id == user_id)
            .where(models.RefreshToken.session_id == session_id)
            .where(models.RefreshToken.is_revoked.is_(False))
            .values(is_revoked=True, revoked_at=now)
            .returning(models.RefreshToken.id)
        )
        return len(result.scalars().all())

    async def revoke_all_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        now: datetime,
        keep_session_id: UUID | None = None,
    ) -> tuple[int, set[str]]:
        """Revoke every live token of a user, except ``keep_session_id``'s.

        Returns ``(count, session_ids)`` — the ids whose access tokens the caller
        must blacklist, harvested from the same statement.
        """
        await self._lock_owner(session, user_id)
        query = (
            sa.update(models.RefreshToken)
            .where(models.RefreshToken.user_id == user_id)
            .where(models.RefreshToken.is_revoked.is_(False))
            .values(is_revoked=True, revoked_at=now)
            .returning(models.RefreshToken.session_id)
        )
        if keep_session_id is not None:
            query = query.where(models.RefreshToken.session_id != keep_session_id)
        result = await session.execute(query)
        rows = result.scalars().all()
        return len(rows), {str(sid) for sid in rows if sid is not None}

    async def revoke_client_family(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        user_agent: str | None,
        ip_address: str | None,
        now: datetime,
    ) -> tuple[int, set[str]]:
        """Revoke a user's live tokens for one browser (or one network, when no
        user-agent is known). Returns ``(count, session_ids)``.

        Scoping by user-agent first keeps different browsers on the same device
        independent; IP is only the fallback when the UA is unavailable.
        """
        if user_agent is not None:
            client_filter = models.RefreshToken.user_agent == user_agent
        elif ip_address is not None:
            client_filter = models.RefreshToken.ip_address == ip_address
        else:
            return await self.revoke_all_for_user(session, user_id=user_id, now=now)

        await self._lock_owner(session, user_id)
        result = await session.execute(
            sa.update(models.RefreshToken)
            .where(models.RefreshToken.user_id == user_id)
            .where(models.RefreshToken.is_revoked.is_(False))
            .where(client_filter)
            .values(is_revoked=True, revoked_at=now)
            .returning(models.RefreshToken.session_id)
        )
        rows = result.scalars().all()
        return len(rows), {str(sid) for sid in rows if sid is not None}

    async def latest_per_session(
        self,
        session: AsyncSession,
        params: PaginationSortParams,
        *,
        now: datetime,
        user_id: int | None = None,
        search: str | None = None,
        status: str | None = None,
    ) -> tuple[Sequence[models.RefreshToken], int]:
        """One page of logical sessions — the newest token of each — with their owners, and the total.

        Rotation writes a new token row on every refresh, so the token count
        dwarfs the session count; collapsing with ``DISTINCT ON``, filtering,
        sorting and paging in SQL is what keeps the admin session inventory from
        streaming the whole table into Python. ``user_id`` is constant within a
        session, so scoping it before the DISTINCT ON is safe and keeps the
        ``(session_id)`` index selective. ``params.sort``: ``login_at``,
        ``expires_at``, ``status``, anything else ``last_seen_at``.
        """
        latest_ids = (
            sa.select(models.RefreshToken.id)
            .distinct(models.RefreshToken.session_id)
            .order_by(models.RefreshToken.session_id, models.RefreshToken.created_at.desc())
        )
        if user_id is not None:
            latest_ids = latest_ids.where(models.RefreshToken.user_id == user_id)

        status_column = self._status(now)
        query = sa.select(models.RefreshToken).where(models.RefreshToken.id.in_(latest_ids.scalar_subquery()))
        if search:
            term = f"%{search}%"
            query = query.join(models.AuthUser, models.AuthUser.id == models.RefreshToken.user_id).where(
                sa.or_(
                    models.AuthUser.email.ilike(term),
                    models.AuthUser.username.ilike(term),
                    models.RefreshToken.user_agent.ilike(term),
                    models.RefreshToken.ip_address.ilike(term),
                )
            )
        if status is not None:
            query = query.where(status_column == status)

        total = await session.scalar(sa.select(sa.func.count()).select_from(query.subquery()))
        sort_column = {
            "login_at": models.RefreshToken.session_started_at,
            "expires_at": models.RefreshToken.expires_at,
            "status": status_column,
        }.get(params.sort, models.RefreshToken.created_at)
        descending = SortOrder(params.order) is SortOrder.DESC
        query = query.options(selectinload(models.RefreshToken.user)).order_by(
            *(column.desc() if descending else column.asc() for column in (sort_column, models.RefreshToken.id))
        )
        result = await session.execute(params.apply_pagination(query))
        return result.scalars().all(), int(total or 0)

    async def delete_expired_before(self, session: AsyncSession, cutoff: datetime, *, limit: int) -> int:
        """Drop up to ``limit`` tokens whose ``expires_at`` is before ``cutoff``; returns the count.

        Rotation inserts a row per refresh and revocation only flags it, so
        without this the table grows forever (84k of 87k rows revoked or expired
        on a production restore). Nothing authenticates against an expired row;
        the session lists only lose history older than the cutoff. Bounded so a
        backlog is deleted in short transactions, each an ``expires_at`` index range.
        """
        batch = sa.select(models.RefreshToken.id).where(models.RefreshToken.expires_at < cutoff).limit(limit)
        result = await session.execute(
            sa.delete(models.RefreshToken).where(models.RefreshToken.id.in_(batch.scalar_subquery()))
        )
        return int(result.rowcount or 0)


class OAuthConnectionRepository(BaseRepository[models.OAuthConnection]):
    def __init__(self) -> None:
        super().__init__(models.OAuthConnection)

    async def list_by_user(
        self,
        session: AsyncSession,
        auth_user_id: int,
    ) -> Sequence[models.OAuthConnection]:
        result = await session.execute(
            sa.select(models.OAuthConnection).where(models.OAuthConnection.auth_user_id == auth_user_id)
        )
        return result.scalars().all()

    async def list_by_user_providers(
        self,
        session: AsyncSession,
        *,
        auth_user_id: int,
        providers: Sequence[str],
    ) -> Sequence[models.OAuthConnection]:
        result = await session.execute(
            sa.select(models.OAuthConnection).where(
                models.OAuthConnection.auth_user_id == auth_user_id,
                models.OAuthConnection.provider.in_(list(providers)),
            )
        )
        return result.scalars().all()

    async def get_by_provider_subject(
        self,
        session: AsyncSession,
        *,
        provider: str,
        provider_user_id: str,
    ) -> models.OAuthConnection | None:
        return await self.get_by(session, provider=provider, provider_user_id=provider_user_id)

    async def get_with_auth_user(
        self,
        session: AsyncSession,
        connection_id: int,
    ) -> models.OAuthConnection | None:
        return await self.get(session, connection_id, options=[selectinload(models.OAuthConnection.auth_user)])

    async def count_for_user(self, session: AsyncSession, auth_user_id: int) -> int:
        return await self.count(session, filters=[models.OAuthConnection.auth_user_id == auth_user_id])

    async def lock_unsealed_tokens(
        self, session: AsyncSession, *, kept_providers: Collection[str], limit: int
    ) -> Sequence[models.OAuthConnection]:
        """Up to ``limit`` connections storing a token they should not: a ``kept_providers`` token not yet sealed
        (no ``secretbox`` prefix), or any token of another provider.

        Row-locked, skipping rows another transaction holds, so concurrent callers split the work.
        """
        conn = models.OAuthConnection

        def in_clear(column: Any) -> sa.ColumnElement[bool]:
            return sa.and_(column.is_not(None), sa.not_(column.startswith(secretbox.PREFIX)))

        result = await session.scalars(
            self.select()
            .where(
                sa.or_(
                    sa.and_(
                        conn.provider.in_(list(kept_providers)),
                        sa.or_(in_clear(conn.access_token), in_clear(conn.refresh_token)),
                    ),
                    sa.and_(
                        conn.provider.not_in(list(kept_providers)),
                        sa.or_(conn.access_token.is_not(None), conn.refresh_token.is_not(None)),
                    ),
                )
            )
            .order_by(conn.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return result.all()

    async def delete_for_provider(
        self,
        session: AsyncSession,
        *,
        auth_user_id: int,
        provider: str,
        provider_user_id: str | None = None,
    ) -> int:
        query = sa.delete(models.OAuthConnection).where(
            models.OAuthConnection.auth_user_id == auth_user_id,
            models.OAuthConnection.provider == provider,
        )
        if provider_user_id is not None:
            query = query.where(models.OAuthConnection.provider_user_id == provider_user_id)
        result = await session.execute(query)
        return result.rowcount or 0

    async def auth_user_ids_for_handles(
        self,
        session: AsyncSession,
        handles: Sequence[tuple[str, str]],
    ) -> set[int]:
        """Auth users reachable from ``(provider, lowercased username)`` pairs.

        One statement for the whole candidate set: the caller only needs to know
        whether the pairs converge on exactly one auth user, and probing them one
        by one made that a query per social account.
        """
        if not handles:
            return set()
        conditions = [
            sa.and_(
                models.OAuthConnection.provider == provider,
                sa.func.lower(models.OAuthConnection.username) == username,
            )
            for provider, username in handles
        ]
        result = await session.execute(
            sa.select(models.OAuthConnection.auth_user_id).distinct().where(sa.or_(*conditions))
        )
        return {row for row in result.scalars().all() if row is not None}

    async def list_admin(
        self,
        session: AsyncSession,
        params: PaginationSortParams,
        *,
        provider: str | None = None,
        auth_user_id: int | None = None,
        search: str | None = None,
    ) -> tuple[Sequence[models.OAuthConnection], int]:
        filters: list[sa.ColumnElement[bool]] = []
        if provider:
            filters.append(models.OAuthConnection.provider == provider)
        if auth_user_id is not None:
            filters.append(models.OAuthConnection.auth_user_id == auth_user_id)
        if search:
            term = f"%{search}%"
            filters.append(
                sa.or_(
                    models.OAuthConnection.username.ilike(term),
                    models.OAuthConnection.email.ilike(term),
                    models.OAuthConnection.display_name.ilike(term),
                    models.OAuthConnection.provider_user_id.ilike(term),
                )
            )
        return await self.list(
            session,
            params,
            options=[selectinload(models.OAuthConnection.auth_user)],
            filters=filters,
        )


class UserPermissionDenyRepository(BaseRepository[models.UserPermissionDeny]):
    """Per-user negative RBAC (``auth.user_permission_deny``)."""

    def __init__(self) -> None:
        super().__init__(models.UserPermissionDeny)

    @staticmethod
    def workspace_scope(workspace_id: int | None) -> sa.ColumnElement[bool]:
        """NULL-safe equality filter for the deny's workspace scope.

        Mirrors the ``COALESCE(workspace_id, 0)`` unique-index semantics: a global
        deny (``workspace_id IS NULL``) and a deny scoped to a concrete workspace
        are distinct scopes and must never be conflated by a plain ``==`` (which
        never matches NULL).
        """
        if workspace_id is None:
            return models.UserPermissionDeny.workspace_id.is_(None)
        return models.UserPermissionDeny.workspace_id == workspace_id

    async def list_with_permissions(
        self,
        session: AsyncSession,
        user_id: int,
    ) -> Sequence[tuple[models.Permission, int | None]]:
        result = await session.execute(
            sa.select(models.Permission, models.UserPermissionDeny.workspace_id)
            .join(models.UserPermissionDeny, models.UserPermissionDeny.permission_id == models.Permission.id)
            .where(models.UserPermissionDeny.user_id == user_id)
            .order_by(models.Permission.name, models.UserPermissionDeny.workspace_id)
        )
        return result.all()

    async def list_denied_triples(
        self,
        session: AsyncSession,
        user_id: int,
    ) -> list[dict[str, Any]]:
        """``(resource, action, workspace_id)`` triples for the token payload."""
        result = await session.execute(
            sa.select(
                models.Permission.resource,
                models.Permission.action,
                models.UserPermissionDeny.workspace_id,
            )
            .join(models.UserPermissionDeny, models.UserPermissionDeny.permission_id == models.Permission.id)
            .where(models.UserPermissionDeny.user_id == user_id)
        )
        return [
            {"resource": resource, "action": action, "workspace_id": workspace_id}
            for resource, action, workspace_id in result.all()
        ]

    async def get_scoped(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        permission_id: int,
        workspace_id: int | None,
    ) -> models.UserPermissionDeny | None:
        return await session.scalar(
            self.select().where(
                models.UserPermissionDeny.user_id == user_id,
                models.UserPermissionDeny.permission_id == permission_id,
                self.workspace_scope(workspace_id),
            )
        )

    async def delete_scoped(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        permission_id: int,
        workspace_id: int | None,
    ) -> int:
        result = await session.execute(
            sa.delete(models.UserPermissionDeny).where(
                models.UserPermissionDeny.user_id == user_id,
                models.UserPermissionDeny.permission_id == permission_id,
                self.workspace_scope(workspace_id),
            )
        )
        return result.rowcount or 0

    async def user_ids_for_permission(self, session: AsyncSession, permission_id: int) -> Sequence[int]:
        """Users holding any deny (global or scoped) on ``permission_id``."""
        return (
            await session.scalars(
                sa.select(models.UserPermissionDeny.user_id)
                .where(models.UserPermissionDeny.permission_id == permission_id)
                .distinct()
            )
        ).all()


class UserRoleRepository:
    """The ``auth.user_roles`` association table.

    Has no mapped model of its own, so it does not extend ``BaseRepository``;
    role grants are written as plain inserts to keep AsyncSession clear of
    relationship lazy-loads.
    """

    async def assign(self, session: AsyncSession, *, user_id: int, role_id: int) -> None:
        await session.execute(sa.insert(models.user_roles).values(user_id=user_id, role_id=role_id))

    async def user_ids_for_role(self, session: AsyncSession, role_id: int) -> Sequence[int]:
        result = await session.execute(
            sa.select(models.user_roles.c.user_id).where(models.user_roles.c.role_id == role_id)
        )
        return result.scalars().all()

    async def count_for_role(self, session: AsyncSession, role_id: int) -> int:
        return int(
            await session.scalar(
                sa.select(sa.func.count(models.user_roles.c.user_id)).where(models.user_roles.c.role_id == role_id)
            )
            or 0
        )

    async def grant_missing_workspace_member_role(self, session: AsyncSession, workspace_id: int) -> int:
        """Grant the baseline ``player`` role to every auth-linked member of
        ``workspace_id`` whose auth user currently holds no role there.

        One set-based statement, and idempotent: the ``NOT EXISTS`` guard only
        touches role-less members, so re-running grants nothing and never
        duplicates. Raw SQL because the join walks three schemas
        (``workspace_member`` -> ``players.user`` -> ``auth.roles``) into an
        association table with no mapped class; ``workspace_id`` is bound, not
        interpolated. Returns the number of grants inserted and stages the
        RBAC-change event for those users in the same transaction. The caller
        must have ensured the workspace's system roles exist.
        """
        from shared.rbac.bootstrap import stage_rbac_change

        result = await session.execute(
            sa.text(
                """
            INSERT INTO auth.user_roles (user_id, role_id)
            SELECT DISTINCT pu.auth_user_id, r.id
            FROM workspace_member wm
            JOIN players."user" pu ON pu.id = wm.player_id AND pu.auth_user_id IS NOT NULL
            JOIN auth.roles r ON r.workspace_id = wm.workspace_id AND r.name = 'player'
            WHERE wm.workspace_id = :workspace_id
              AND wm.removed_at IS NULL
              AND wm.observed_only IS FALSE
              AND NOT EXISTS (
                SELECT 1 FROM auth.user_roles ur
                JOIN auth.roles r2 ON r2.id = ur.role_id
                WHERE ur.user_id = pu.auth_user_id AND r2.workspace_id = wm.workspace_id
              )
            RETURNING user_id
            """
            ),
            {"workspace_id": workspace_id},
        )
        granted = list(result.scalars())
        await stage_rbac_change(session, granted, change="roles_changed", workspace_id=workspace_id)
        return len(granted)

    async def revoke_workspace_roles(self, session: AsyncSession, *, user_id: int, workspace_id: int) -> None:
        """Drop every grant this auth user holds for ``workspace_id``'s roles.

        Set-based: membership removal must not leave orphaned grants behind, and
        the grant count is unbounded (system roles plus any custom ones), so
        loading them to delete one by one buys nothing. Global roles are
        untouched — the subquery is scoped to roles owned by this workspace.
        """
        await session.execute(
            sa.delete(models.user_roles).where(
                models.user_roles.c.user_id == user_id,
                models.user_roles.c.role_id.in_(
                    sa.select(models.Role.id).where(models.Role.workspace_id == workspace_id)
                ),
            )
        )


class ApiKeyRepository(BaseRepository[models.ApiKey]):
    def __init__(self) -> None:
        super().__init__(models.ApiKey)

    async def list_for_user_workspace(
        self,
        session: AsyncSession,
        *,
        auth_user_id: int,
        workspace_id: int,
    ) -> Sequence[models.ApiKey]:
        result = await session.execute(
            sa.select(models.ApiKey)
            .where(models.ApiKey.auth_user_id == auth_user_id, models.ApiKey.workspace_id == workspace_id)
            .order_by(models.ApiKey.created_at.desc(), models.ApiKey.id.desc())
        )
        return result.scalars().all()

    async def list_page(
        self,
        session: AsyncSession,
        params: PaginationSortParams,
        *,
        workspace_id: int,
        search: str | None = None,
    ) -> tuple[Sequence[models.ApiKey], int]:
        filters: list[sa.ColumnElement[bool]] = [models.ApiKey.workspace_id == workspace_id]
        if search:
            filters.append(models.ApiKey.name.ilike(f"%{search}%"))
        return await self.list(
            session,
            params,
            filters=filters,
            options=[selectinload(models.ApiKey.user)],
        )

    async def status_counts(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        now: datetime,
    ) -> dict[str, int]:
        """Tallies by derived status (``active``/``expired``/``revoked``)."""
        status_expr = sa.case(
            (models.ApiKey.revoked_at.isnot(None), "revoked"),
            (
                sa.and_(models.ApiKey.expires_at.isnot(None), models.ApiKey.expires_at <= now),
                "expired",
            ),
            else_="active",
        )
        rows = (
            await session.execute(
                sa.select(status_expr, sa.func.count(models.ApiKey.id))
                .where(models.ApiKey.workspace_id == workspace_id)
                .group_by(status_expr)
            )
        ).all()
        return {str(label): int(count) for label, count in rows}

    async def get_with_owner(self, session: AsyncSession, api_key_id: int) -> models.ApiKey | None:
        return await self.get(session, api_key_id, options=[selectinload(models.ApiKey.user)])

    async def get_by_public_id(
        self,
        session: AsyncSession,
        public_id: str,
    ) -> models.ApiKey | None:
        result = await session.execute(
            sa.select(models.ApiKey)
            .where(models.ApiKey.public_id == public_id)
            .options(
                # No owner row: the key's authority is the owner's RBAC payload,
                # resolved cache-first by id (``auth_user_id``) and loaded only on
                # a miss, after the generation that fences the cache fill.
                noload(models.ApiKey.user),
                joinedload(models.ApiKey.workspace),
                selectinload(models.ApiKey.scopes),
            )
        )
        return result.scalar_one_or_none()


class UserMergeAuditRepository(BaseRepository[models.UserMergeAudit]):
    """``players.user_merge_audit`` — the append-only trail of profile merges."""

    def __init__(self) -> None:
        super().__init__(models.UserMergeAudit)
