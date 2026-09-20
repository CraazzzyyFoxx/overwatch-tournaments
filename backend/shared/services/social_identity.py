"""Policy for the unified ``players.social_account`` table.

Single source of truth for MUTATING player social identities, so every writer
(admin CRUD, CSV/Sheets import, registration, parser log import, OAuth) applies
identical normalization, ``is_primary`` selection, global-visibility seeding and
uniqueness handling.

This layer owns decisions only — which row to look up, what counts as a clash,
who inherits ``is_primary``, what proves a verification. Every statement it
needs comes from ``shared.repository`` (see ``backend/docs/repository-boundaries.md``);
there is no SQL here, and no thin pass-through either: a method exists because it
makes a decision the repository must not make.

Transaction-neutral: mutates the session and flushes; the caller commits.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.social import OAUTH_PROVIDERS, normalize_social_handle, oauth_handle_candidates
from shared.repository import (
    OAuthConnectionRepository,
    SocialAccountRepository,
    SocialAccountVisibilityRepository,
    UserRepository,
)

__all__ = (
    "SocialAccountNotOAuthLinked",
    "SocialHandleConflict",
    "SocialIdentityService",
    "social_identity_service",
)


class SocialHandleConflict(Exception):
    """Raised when an upsert/update would collide with another account of the
    same (user, provider, normalized handle)."""


class SocialAccountNotOAuthLinked(Exception):
    """Raised by :meth:`SocialIdentityService.verify` when no real OAuth
    connection backs the verification claim (see that method's docstring)."""


class SocialIdentityService:
    """Write policy for player social identities."""

    def __init__(
        self,
        accounts: SocialAccountRepository | None = None,
        visibilities: SocialAccountVisibilityRepository | None = None,
        connections: OAuthConnectionRepository | None = None,
        players: UserRepository | None = None,
    ) -> None:
        self.accounts = accounts or SocialAccountRepository()
        self.visibilities = visibilities or SocialAccountVisibilityRepository()
        self.connections = connections or OAuthConnectionRepository()
        self.players = players or UserRepository()

    # -- lookups -----------------------------------------------------------

    async def list_for_player(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        providers: Sequence[str] | None = None,
    ) -> Sequence[models.SocialAccount]:
        return await self.accounts.list_by_user(session, user_id, providers=providers)

    async def find_by_handle(
        self,
        session: AsyncSession,
        *,
        provider: str,
        username: str,
        user_id: int | None = None,
    ) -> models.SocialAccount | None:
        """Find an account by a RAW handle, optionally scoped to one player.

        Normalization happens here, not in the repository: what "the same
        handle" means is a provider rule from the catalog, and a repository that
        knew it would be a second place to keep it.
        """
        return await self.accounts.find_by_handle(
            session,
            provider=provider,
            username_normalized=normalize_social_handle(provider, username),
            user_id=user_id,
        )

    async def find_player_id_by_handle(self, session: AsyncSession, *, provider: str, username: str) -> int | None:
        """Resolve the owning player id from a provider handle."""
        account = await self.find_by_handle(session, provider=provider, username=username)
        return account.user_id if account is not None else None

    # -- writes ------------------------------------------------------------

    async def upsert(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        provider: str,
        username: str,
        url: str | None = None,
        provider_user_id: str | None = None,
        is_verified: bool | None = None,
        ensure_global_visibility: bool = True,
    ) -> models.SocialAccount:
        """Create or update a player's social identity (idempotent on (user, provider, handle)).

        The first account a user gets for a provider becomes ``is_primary``. A global
        visibility row is seeded on creation (shown on the profile by default) unless
        ``ensure_global_visibility`` is False. Only non-None optional fields overwrite
        existing values, so callers can update verification without clobbering data.

        When ``provider_user_id`` is given, the existing account is looked up by
        ``(provider, provider_user_id)`` first -- that pair is what
        ``uq_social_account_provider_subject`` actually enforces, and it is stable
        even when the display handle changes (Discord/Twitch usernames aren't).
        A handle-only lookup misses that rename and re-inserts, colliding on the
        constraint (Sentry OWT-TOURNAMENTS-20D: UniqueViolationError). Raises
        ``SocialHandleConflict`` if that ``provider_user_id`` is already linked to
        a *different* user -- silently retargeting someone else's account would be
        worse than the crash this replaces.
        """
        normalized = normalize_social_handle(provider, username)

        account = None
        if provider_user_id is not None:
            account = await self.accounts.get_by_provider_subject(
                session, provider=provider, provider_user_id=provider_user_id
            )
            if account is not None and account.user_id != user_id:
                raise SocialHandleConflict(f"{provider} account is already linked to a different user")
        if account is None:
            account = await self.accounts.find_by_handle(
                session, provider=provider, username_normalized=normalized, user_id=user_id
            )

        if account is None:
            is_first = not await self.accounts.has_any_for_provider(session, user_id=user_id, provider=provider)
            account = await self.accounts.create(
                session,
                models.SocialAccount(
                    user_id=user_id,
                    provider=provider,
                    username=username,
                    username_normalized=normalized,
                    url=url,
                    provider_user_id=provider_user_id,
                    is_verified=bool(is_verified) if is_verified is not None else False,
                    is_primary=is_first,
                ),
            )
        else:
            changes: dict[str, object] = {
                "username": username,  # refresh display casing
                "username_normalized": normalized,
            }
            if url is not None:
                changes["url"] = url
            if provider_user_id is not None:
                changes["provider_user_id"] = provider_user_id
            if is_verified is not None:
                changes["is_verified"] = is_verified
            await self.accounts.update_fields(session, account, changes)

        if ensure_global_visibility:
            await self.set_visibility(session, account_id=account.id, workspace_id=None, visible=True)
        return account

    async def update(
        self,
        session: AsyncSession,
        *,
        account_id: int,
        user_id: int,
        username: str | None = None,
        url: str | None = None,
    ) -> models.SocialAccount | None:
        """Update an account's display handle / url. Returns None if not found.

        Changing the handle recomputes ``username_normalized``; raises
        ``SocialHandleConflict`` if it would collide with another of the user's
        accounts for the same provider.
        """
        account = await self.accounts.get_owned(session, account_id=account_id, user_id=user_id)
        if account is None:
            return None

        changes: dict[str, object] = {}
        if username is not None:
            normalized = normalize_social_handle(account.provider, username)
            if normalized != account.username_normalized:
                clash = await self.accounts.find_handle_clash(
                    session,
                    user_id=user_id,
                    provider=account.provider,
                    username_normalized=normalized,
                    exclude_id=account_id,
                )
                if clash is not None:
                    raise SocialHandleConflict(f"{account.provider} handle '{username}' already exists for this user")
            changes["username"] = username
            changes["username_normalized"] = normalized
        if url is not None:
            changes["url"] = url
        return await self.accounts.update_fields(session, account, changes)

    async def delete(self, session: AsyncSession, *, account_id: int, user_id: int) -> models.SocialAccount | None:
        """Delete an account (visibility rows cascade). Promotes a new primary if needed.

        Returns the deleted account, or None if not found / not owned by ``user_id``.
        """
        account = await self.accounts.get_owned(session, account_id=account_id, user_id=user_id)
        if account is None:
            return None

        was_primary = account.is_primary
        provider = account.provider
        await self.accounts.delete(session, account)

        if was_primary:
            heir = await self.accounts.oldest_for_provider(session, user_id=user_id, provider=provider)
            if heir is not None:
                await self.accounts.update_fields(session, heir, {"is_primary": True})
        return account

    async def set_primary(self, session: AsyncSession, *, account_id: int, user_id: int) -> models.SocialAccount | None:
        """Make ``account_id`` the primary for its (user, provider); unset siblings."""
        account = await self.accounts.get_owned(session, account_id=account_id, user_id=user_id)
        if account is None:
            return None

        await self.accounts.clear_primary_except(
            session, user_id=user_id, provider=account.provider, keep_id=account_id
        )
        return await self.accounts.update_fields(session, account, {"is_primary": True})

    async def verify(self, session: AsyncSession, *, account_id: int, user_id: int) -> models.SocialAccount | None:
        """Manually mark an OAuth-eligible account verified -- but only when a real
        ``auth.oauth_connections`` row for the player's linked auth user actually
        proves this handle.

        Exists for accounts the automatic sync (``OAuthService._attach_verified_social_account``,
        identity-service) missed: it runs best-effort at login time and no-ops when
        the player isn't linked yet or the stored handle doesn't match the OAuth
        response verbatim, leaving a legitimately-owned account stuck unverified.
        This re-derives the same proof instead of trusting an admin's say-so
        blindly, so it can never fabricate a verification that OAuth never granted.

        Returns None if the account doesn't exist / isn't owned by ``user_id``.
        Already-verified accounts are returned unchanged (idempotent). Raises
        ``SocialAccountNotOAuthLinked`` (message describes the gap) when the
        provider can't be OAuth-verified, the player has no linked auth account, or
        none of its OAuth connections for this provider match the handle.
        """
        account = await self.accounts.get_owned(session, account_id=account_id, user_id=user_id)
        if account is None:
            return None
        if account.is_verified:
            return account

        if account.provider not in OAUTH_PROVIDERS:
            raise SocialAccountNotOAuthLinked(f"{account.provider} accounts cannot be OAuth-verified")

        player = await self.players.get(session, user_id)
        auth_user_id = player.auth_user_id if player is not None else None
        if auth_user_id is None:
            raise SocialAccountNotOAuthLinked("Player has no linked account; link an OAuth account first")

        connections = await self.connections.list_by_user_providers(
            session, auth_user_id=auth_user_id, providers=[account.provider]
        )
        match = next(
            (
                conn
                for conn in connections
                if account.username_normalized
                in oauth_handle_candidates(
                    account.provider,
                    username=conn.username,
                    display_name=conn.display_name,
                    provider_data=conn.provider_data,
                )
            ),
            None,
        )
        if match is None:
            raise SocialAccountNotOAuthLinked(f"No linked {account.provider} OAuth connection matches this handle")

        return await self.accounts.update_fields(
            session, account, {"is_verified": True, "provider_user_id": match.provider_user_id}
        )

    async def set_visibility(
        self,
        session: AsyncSession,
        *,
        account_id: int,
        workspace_id: int | None,
        visible: bool,
    ) -> None:
        """Toggle visibility of an account in a scope (``workspace_id`` None = global).

        Presence of the row means visible; ``visible=False`` removes it.
        """
        existing = await self.visibilities.get_for_scope(session, account_id=account_id, workspace_id=workspace_id)
        if visible and existing is None:
            await self.visibilities.create(
                session, models.SocialAccountVisibility(account_id=account_id, workspace_id=workspace_id)
            )
        elif not visible and existing is not None:
            await self.visibilities.delete(session, existing)


social_identity_service = SocialIdentityService()
