"""Shared write/lookup helpers for the unified ``players.social_account`` table.

Single source of truth for mutating player social identities so every writer
(admin CRUD, CSV/Sheets import, registration, parser log import, OAuth) applies
identical normalization, ``is_primary`` selection, global-visibility seeding and
uniqueness handling. Reads of the grouped legacy shape still happen in each
service's ``to_pydantic``; this module owns the writes.

Transaction-neutral: mutates the session and flushes; the caller commits.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.social import normalize_social_handle

__all__ = (
    "list_social_accounts",
    "get_social_account",
    "find_by_handle",
    "find_player_id_by_handle",
    "upsert_social_account",
    "update_social_account",
    "delete_social_account",
    "set_primary",
    "set_visibility",
    "SocialHandleConflict",
)


class SocialHandleConflict(Exception):
    """Raised when an upsert/update would collide with another account of the
    same (user, provider, normalized handle)."""


async def list_social_accounts(
    session: AsyncSession,
    user_id: int,
    *,
    providers: Sequence[str] | None = None,
) -> Sequence[models.SocialAccount]:
    query = sa.select(models.SocialAccount).where(models.SocialAccount.user_id == user_id)
    if providers:
        query = query.where(models.SocialAccount.provider.in_(list(providers)))
    query = query.order_by(
        models.SocialAccount.provider,
        models.SocialAccount.is_primary.desc(),
        models.SocialAccount.id,
    )
    return (await session.execute(query)).scalars().all()


async def get_social_account(session: AsyncSession, account_id: int) -> models.SocialAccount | None:
    return (
        await session.execute(sa.select(models.SocialAccount).where(models.SocialAccount.id == account_id))
    ).scalar_one_or_none()


async def find_by_handle(
    session: AsyncSession,
    *,
    provider: str,
    username: str,
    user_id: int | None = None,
) -> models.SocialAccount | None:
    """Find an account by (provider, normalized handle), optionally scoped to a user."""
    normalized = normalize_social_handle(provider, username)
    query = sa.select(models.SocialAccount).where(
        models.SocialAccount.provider == provider,
        models.SocialAccount.username_normalized == normalized,
    )
    if user_id is not None:
        query = query.where(models.SocialAccount.user_id == user_id)
    return (await session.execute(query)).scalars().first()


async def find_player_id_by_handle(session: AsyncSession, *, provider: str, username: str) -> int | None:
    """Resolve the owning player id from a provider handle (replaces legacy-table lookups)."""
    account = await find_by_handle(session, provider=provider, username=username)
    return account.user_id if account is not None else None


async def _has_any_for_provider(session: AsyncSession, user_id: int, provider: str) -> bool:
    count = (
        await session.execute(
            sa.select(sa.func.count())
            .select_from(models.SocialAccount)
            .where(models.SocialAccount.user_id == user_id, models.SocialAccount.provider == provider)
        )
    ).scalar_one()
    return count > 0


async def _ensure_global_visibility(session: AsyncSession, account_id: int) -> None:
    exists = (
        await session.execute(
            sa.select(sa.literal(True))
            .select_from(models.SocialAccountVisibility)
            .where(
                models.SocialAccountVisibility.account_id == account_id,
                models.SocialAccountVisibility.workspace_id.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(models.SocialAccountVisibility(account_id=account_id, workspace_id=None))
        await session.flush()


async def upsert_social_account(
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
    """
    normalized = normalize_social_handle(provider, username)
    account = await find_by_handle(session, provider=provider, username=username, user_id=user_id)

    if account is None:
        is_first = not await _has_any_for_provider(session, user_id, provider)
        account = models.SocialAccount(
            user_id=user_id,
            provider=provider,
            username=username,
            username_normalized=normalized,
            url=url,
            provider_user_id=provider_user_id,
            is_verified=bool(is_verified) if is_verified is not None else False,
            is_primary=is_first,
        )
        session.add(account)
        await session.flush()
    else:
        account.username = username  # refresh display casing
        if url is not None:
            account.url = url
        if provider_user_id is not None:
            account.provider_user_id = provider_user_id
        if is_verified is not None:
            account.is_verified = is_verified
        await session.flush()

    if ensure_global_visibility:
        await _ensure_global_visibility(session, account.id)
    return account


async def update_social_account(
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
    account = (
        await session.execute(
            sa.select(models.SocialAccount).where(
                models.SocialAccount.id == account_id,
                models.SocialAccount.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        return None

    if username is not None:
        normalized = normalize_social_handle(account.provider, username)
        if normalized != account.username_normalized:
            clash = (
                await session.execute(
                    sa.select(models.SocialAccount.id).where(
                        models.SocialAccount.user_id == user_id,
                        models.SocialAccount.provider == account.provider,
                        models.SocialAccount.username_normalized == normalized,
                        models.SocialAccount.id != account_id,
                    )
                )
            ).scalar_one_or_none()
            if clash is not None:
                raise SocialHandleConflict(f"{account.provider} handle '{username}' already exists for this user")
        account.username = username
        account.username_normalized = normalized
    if url is not None:
        account.url = url
    await session.flush()
    return account


async def delete_social_account(session: AsyncSession, *, account_id: int, user_id: int) -> models.SocialAccount | None:
    """Delete an account (visibility rows cascade). Promotes a new primary if needed.

    Returns the deleted account, or None if not found / not owned by ``user_id``.
    """
    account = (
        await session.execute(
            sa.select(models.SocialAccount).where(
                models.SocialAccount.id == account_id,
                models.SocialAccount.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        return None

    was_primary = account.is_primary
    provider = account.provider
    await session.delete(account)
    await session.flush()

    if was_primary:
        # Promote the oldest remaining account for this (user, provider) to primary.
        replacement = (
            await session.execute(
                sa.select(models.SocialAccount)
                .where(
                    models.SocialAccount.user_id == user_id,
                    models.SocialAccount.provider == provider,
                )
                .order_by(models.SocialAccount.created_at, models.SocialAccount.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        if replacement is not None:
            replacement.is_primary = True
            await session.flush()
    return account


async def set_primary(session: AsyncSession, *, account_id: int, user_id: int) -> models.SocialAccount | None:
    """Make ``account_id`` the primary for its (user, provider); unset siblings."""
    account = (
        await session.execute(
            sa.select(models.SocialAccount).where(
                models.SocialAccount.id == account_id,
                models.SocialAccount.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        return None

    await session.execute(
        sa.update(models.SocialAccount)
        .where(
            models.SocialAccount.user_id == user_id,
            models.SocialAccount.provider == account.provider,
            models.SocialAccount.id != account_id,
            models.SocialAccount.is_primary.is_(True),
        )
        .values(is_primary=False)
    )
    account.is_primary = True
    await session.flush()
    return account


async def set_visibility(
    session: AsyncSession,
    *,
    account_id: int,
    workspace_id: int | None,
    visible: bool,
) -> None:
    """Toggle visibility of an account in a scope (``workspace_id`` None = global).

    Presence of the row means visible; ``visible=False`` removes it.
    """
    if workspace_id is None:
        scope_filter = models.SocialAccountVisibility.workspace_id.is_(None)
    else:
        scope_filter = models.SocialAccountVisibility.workspace_id == workspace_id

    existing = (
        await session.execute(
            sa.select(models.SocialAccountVisibility).where(
                models.SocialAccountVisibility.account_id == account_id,
                scope_filter,
            )
        )
    ).scalar_one_or_none()

    if visible and existing is None:
        session.add(models.SocialAccountVisibility(account_id=account_id, workspace_id=workspace_id))
        await session.flush()
    elif not visible and existing is not None:
        await session.delete(existing)
        await session.flush()
