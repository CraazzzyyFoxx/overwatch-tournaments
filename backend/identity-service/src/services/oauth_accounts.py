"""Matching a proven provider identity to a site account.

The security-critical half of OAuth. A completed code exchange proves exactly
one thing: the caller controls ``(provider, provider_user_id)``. Everything
this module does is decide what that single fact may unlock, and the answer is
deliberately narrow -- see ``_find_existing_auth_user`` for why an email match
is never enough, and ``_link_player_if_unowned`` for why an owned player is
never reassigned.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core import secretbox
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider, normalize_social_handle, social_provider_for_oauth
from shared.repository import (
    AuthUserRepository,
    OAuthConnectionRepository,
    SocialAccountRepository,
    UserRepository,
)
from shared.services.social_identity import SocialHandleConflict
from shared.services.social_identity import social_identity_service as socials_writer
from src import schemas
from src.core.config import settings
from src.schemas.auth import suggest_username
from src.services.auth_users import AuthUserService, auth_users
from src.services.oauth_providers import OAuthProviderRegistry, oauth_providers
from src.services.session_cache import SessionCache, session_cache

#: The only providers whose tokens are kept, sealed at rest (``shared.core.secretbox``): Discord's lists the user's
#: guilds (``oauth.discord_guilds``), Twitch's checks their subscriptions (``shared.services.subscriptions``). Every
#: other provider's token is used once, at sign-in, and never stored.
SEALED_TOKEN_PROVIDERS = frozenset({"discord", "twitch"})


def _token_expires_at(token_data: dict[str, Any]) -> datetime | None:
    if "expires_in" not in token_data:
        return None
    return datetime.now(UTC) + timedelta(seconds=token_data["expires_in"])


def _stored_token(provider: str, token: str | None) -> str | None:
    """What ``auth.oauth_connections`` keeps of ``token``: sealed for a kept provider, nothing otherwise."""
    if token is None or provider not in SEALED_TOKEN_PROVIDERS:
        return None
    return secretbox.encrypt(token, secretbox.load_key(settings.oauth_token_encryption_key))


def _store_tokens(conn: models.OAuthConnection, provider: str, token_data: dict[str, Any]) -> None:
    conn.access_token = _stored_token(provider, token_data["access_token"])
    conn.refresh_token = _stored_token(provider, token_data.get("refresh_token"))
    if (expires_at := _token_expires_at(token_data)) is not None:
        conn.token_expires_at = expires_at


def _seal_if_clear(value: str | None, key: bytes) -> str | None:
    return value if value is None or value.startswith(secretbox.PREFIX) else secretbox.encrypt(value, key)


def open_token(stored: str | None) -> str | None:
    """A stored provider token in clear; None when absent or it no longer opens (key changed: only a re-link helps)."""
    if not stored:
        return None
    try:
        return secretbox.decrypt(stored, secretbox.load_key(settings.oauth_token_encryption_key))
    except ValueError as exc:
        logger.error(f"Stored OAuth token is unusable: {exc}")
        return None


def _new_connection(
    auth_user: models.AuthUser, oauth_info: schemas.OAuthUserInfo, token_data: dict[str, Any]
) -> models.OAuthConnection:
    conn = models.OAuthConnection(
        auth_user_id=auth_user.id,
        provider=oauth_info.provider.value,
        provider_user_id=oauth_info.provider_user_id,
        email=oauth_info.email,
        username=oauth_info.username,
        display_name=oauth_info.display_name,
        avatar_url=oauth_info.avatar_url,
        provider_data=oauth_info.raw_data,
    )
    _store_tokens(conn, oauth_info.provider.value, token_data)
    return conn


class OAuthAccountService:
    """Matches a proven provider identity to a site account, or creates one."""

    def __init__(
        self,
        *,
        providers: OAuthProviderRegistry = oauth_providers,
        accounts: AuthUserService = auth_users,
        users: AuthUserRepository = AuthUserRepository(),
        connections: OAuthConnectionRepository = OAuthConnectionRepository(),
        socials: SocialAccountRepository = SocialAccountRepository(),
        players: UserRepository = UserRepository(),
        cache: SessionCache = session_cache,
    ) -> None:
        self.providers = providers
        self.accounts = accounts
        self.users = users
        self.connections = connections
        self.socials = socials
        self.players = players
        self.cache = cache

    def token_key(self) -> bytes | None:
        """``OAUTH_TOKEN_ENCRYPTION_KEY``, or None when it is unset and no kept provider is offered.

        Raises ``RuntimeError`` when Discord or Twitch is offered without a valid key: identity refuses to start
        rather than fail every such sign-in.
        """
        try:
            return secretbox.load_key(settings.oauth_token_encryption_key)
        except ValueError as exc:
            if any(self.providers.is_enabled(provider) for provider in SEALED_TOKEN_PROVIDERS):
                raise RuntimeError(
                    f"OAUTH_TOKEN_ENCRYPTION_KEY is required while Discord or Twitch OAuth is enabled: {exc}"
                ) from exc
            return None

    async def seal_stored_tokens(self, session: AsyncSession, *, batch_size: int = 500) -> int:
        """Startup job: seal the Discord/Twitch tokens still stored in clear, drop every other provider's.

        Idempotent and safe on several replicas at once: each batch row-locks what it rewrites (skipping rows
        another transaction holds) and commits, and a rewritten row never matches again. Returns the rows changed.
        """
        key = self.token_key()
        if key is None:
            logger.warning("OAUTH_TOKEN_ENCRYPTION_KEY is unset: stored OAuth tokens left as they are")
            return 0
        changed = 0
        while rows := await self.connections.lock_unsealed_tokens(
            session, kept_providers=SEALED_TOKEN_PROVIDERS, limit=batch_size
        ):
            for conn in rows:
                if conn.provider in SEALED_TOKEN_PROVIDERS:
                    conn.access_token = _seal_if_clear(conn.access_token, key)
                    conn.refresh_token = _seal_if_clear(conn.refresh_token, key)
                else:
                    conn.access_token = conn.refresh_token = None
            await session.commit()
            changed += len(rows)
        if changed:
            logger.info(f"Stored OAuth tokens sealed or dropped: {changed} connections")
        return changed

    async def handle_callback(
        self, session: AsyncSession, provider_name: str, code: str, *, state: str, code_verifier: str
    ) -> tuple[models.AuthUser, dict[str, Any]]:
        """Exchange ``code`` with the provider and resolve the account: ``(auth_user, token_data)``."""
        provider = self.providers.get(provider_name)
        token_data = await provider.exchange_code(code, state=state, code_verifier=code_verifier)
        oauth_user_info = await provider.get_user_info(token_data["access_token"])
        auth_user = await self.find_or_create_user(session, oauth_user_info, token_data)

        return auth_user, token_data

    async def _find_player_by_provider_record(
        self,
        session: AsyncSession,
        oauth_info: schemas.OAuthUserInfo,
    ) -> models.User | None:
        """Find the player (players.user) via the unified ``social_account`` table
        WITHOUT requiring an AuthUser link. Returns None if not found.

        FAIL-CLOSED: only a cryptographically-confirmed match on the
        provider's ``provider_user_id`` links a player automatically. Matching by
        a free-text handle (Discord ``global_name`` / battletag / twitch login) is
        deliberately NOT done here — those fields are attacker-controllable, so a
        handle collision must never auto-assign someone else's turnier identity
        (``player.auth_user_id``) or mark a social account verified. Handle-based
        association is only available through the explicit, ownership-checked
        player-link flow (``players``).
        """
        provider = social_provider_for_oauth(oauth_info.provider.value)
        if provider is None:
            return None

        # Definitive: a social account already pinned to this exact OAuth subject
        # (provider_user_id proven by a completed OAuth exchange).
        subject_match = await self.socials.find_player_by_subject(
            session, provider=provider, provider_user_id=oauth_info.provider_user_id
        )
        if subject_match is not None:
            logger.info(
                "Found player by verified provider_user_id",
                provider=provider,
                player_id=subject_match.id,
                provider_user_id=oauth_info.provider_user_id,
            )
        return subject_match

    async def _find_auth_user_for_player(
        self,
        session: AsyncSession,
        player: models.User,
    ) -> models.AuthUser | None:
        """Return the AuthUser linked to this player via ``players.user.auth_user_id``, or None."""
        if player.auth_user_id is None:
            return None

        auth_user = await self.users.get(session, player.auth_user_id)
        if auth_user is not None:
            logger.info(
                "Matched existing auth user by player link",
                auth_user_id=auth_user.id,
                player_id=player.id,
            )
        return auth_user

    async def _find_auth_user_via_oauth_connections(
        self,
        session: AsyncSession,
        player: models.User,
    ) -> models.AuthUser | None:
        """Fallback lookup: scan OAuthConnections for any social accounts attached to
        this player (Discord, Twitch, BattleTag), for a player with no
        ``auth_user_id`` set yet. Returns None if none or more than one distinct
        AuthUser is found.
        """
        accounts = await self.socials.list_by_user(session, player.id)
        handles: list[tuple[str, str]] = [(account.provider, account.username.lower()) for account in accounts]
        if not handles:
            return None

        # One statement for the whole candidate set: the decision below only needs
        # to know whether the handles converge on a single auth user.
        auth_user_ids = await self.connections.auth_user_ids_for_handles(session, handles)

        if len(auth_user_ids) == 1:
            auth_user = await self.users.get(session, next(iter(auth_user_ids)))
            if auth_user is not None:
                logger.info(
                    "Matched existing auth user via OAuth connection for player",
                    auth_user_id=auth_user.id,
                    player_id=player.id,
                )
            return auth_user

        if len(auth_user_ids) > 1:
            logger.warning(
                "Ambiguous OAuth connection match for player; skipping automatic linking",
                player_id=player.id,
                auth_user_ids=sorted(auth_user_ids),
            )
        return None

    async def _link_player_if_unowned(
        self, session: AsyncSession, player: models.User, auth_user: models.AuthUser
    ) -> bool:
        """Link ``player`` to ``auth_user`` iff the player has no owner yet.

        A player already linked to a *different* auth user is left untouched —
        that is a conflict for the admin user-merge tool to resolve, never
        something to silently overwrite here. Returns True if the link was set.
        The link is flushed, so a concurrent claim surfaces here as ``IntegrityError``.
        """
        if player.auth_user_id is None:
            await self.players.link_auth_user(session, player, auth_user.id)
            return True
        if player.auth_user_id != auth_user.id:
            logger.warning(
                "Player already linked to a different auth user; leaving unchanged "
                "(conflict for a later merge to resolve)",
                auth_user_id=auth_user.id,
                player_id=player.id,
                existing_auth_user_id=player.auth_user_id,
            )
        return False

    async def _fill_player_avatar(
        self, session: AsyncSession, auth_user_id: int, avatar_url: str | None, *, replaces: str | None = None
    ) -> bool:
        """Show the provider's avatar on the account's player unless the user chose their own.

        Only an empty avatar, or the one this provider itself set before (``replaces``), is filled: a custom upload
        is never overwritten. Returns True when the avatar changed; committing is the caller's.
        """
        if not avatar_url:
            return False
        player = await self.players.get_by_auth_user_id(session, auth_user_id)
        if player is None or player.avatar_url == avatar_url or player.avatar_url not in (None, replaces):
            return False
        await self.players.set_avatar(session, auth_user_id=auth_user_id, avatar_url=avatar_url)
        return True

    async def _attach_verified_social_account(
        self,
        session: AsyncSession,
        auth_user: models.AuthUser,
        oauth_info: schemas.OAuthUserInfo,
        *,
        claim_subject: bool = False,
    ) -> None:
        """Mark the player's social identity for this provider as OAuth-verified.

        Targets the player owning the handle (or, failing that, the auth user's
        linked player). No-op when the auth user has no linked player yet.

        ``claim_subject=True`` is the explicit link flow (``link_to_user``),
        which has already rejected the only case where another account can
        legitimately hold this provider subject: a surviving ``OAuthConnection``
        on a different auth user. Any pin of the subject left on another player
        is therefore unprovable leftover -- a deleted account, an admin unlink,
        a profile merge -- while the caller just cryptographically proved
        ownership of it. So the leftover is released (verified mark and pin
        cleared, handle row kept, exactly as the flow layer's ``unlink`` does)
        and the identity is attached to THIS auth user's own player.
        """
        provider = social_provider_for_oauth(oauth_info.provider.value)
        if provider is None:
            return

        if claim_subject:
            player = await self.players.get_by_auth_user_id(session, auth_user.id)
            if player is None:
                return
            released = await self.socials.release_foreign_subject(
                session,
                provider=provider,
                provider_user_id=oauth_info.provider_user_id,
                keep_user_id=player.id,
            )
            if released:
                logger.info(
                    "Released stale {} verification from another player on explicit link",
                    provider,
                    player_id=player.id,
                    released=released,
                )
        else:
            player = await self._find_player_by_provider_record(session, oauth_info)
            if player is None:
                player = await self.players.get_by_auth_user_id(session, auth_user.id)
                if player is None:
                    return

        # Steam's handle is a bare account id: keep the persona name beside it. ``display_name`` falls back to the
        # handle itself when the profile fetch failed, which is no name at all.
        steam_name = (
            oauth_info.display_name
            if provider == SocialProvider.STEAM and oauth_info.display_name != oauth_info.handle
            else None
        )
        try:
            await socials_writer.upsert(
                session,
                user_id=player.id,
                provider=provider,
                username=oauth_info.handle,
                provider_user_id=oauth_info.provider_user_id,
                is_verified=True,
                display_name=steam_name,
            )
        except SocialHandleConflict:
            # LOGIN path: this provider_user_id is verified on a different player
            # (a shared/reassigned OAuth account). Marking verification is
            # best-effort here -- the login itself must not fail over it. Under
            # ``claim_subject`` the release above already cleared every foreign
            # pin, so this is unreachable defence rather than a real outcome.
            logger.warning(
                "OAuth verify skipped: {} account already linked to another player",
                provider,
                player_id=player.id,
            )
            await session.rollback()
            return
        await session.commit()

    async def _find_unowned_player_by_handle(
        self,
        session: AsyncSession,
        oauth_info: schemas.OAuthUserInfo,
    ) -> models.User | None:
        """Match an UNOWNED player (``players.user.auth_user_id IS NULL``) by the
        provider's verified handle, so a first-time OAuth login reconciles onto
        the player's existing shadow tournament identity instead of spawning a
        duplicate that an admin then has to merge by hand.

        The handle here is the real username/battletag of the account that just
        completed the OAuth exchange, so for THIS provider it is a trustworthy
        ownership signal. This is the deliberately-relaxed complement to
        ``_find_player_by_provider_record`` (which requires a prior
        ``provider_user_id``). It stays conservative: it never touches a player
        already owned by another auth account (that is a merge conflict), and it
        refuses to guess when more than one player carries the same handle.
        """
        provider = social_provider_for_oauth(oauth_info.provider.value)
        if provider is None:
            return None
        normalized = normalize_social_handle(provider, oauth_info.handle)
        if not normalized:
            return None

        players = await self.socials.find_players_by_handle(session, provider=provider, username_normalized=normalized)
        if len(players) == 1 and players[0].auth_user_id is None:
            logger.info(
                "Reconciled OAuth login onto existing unowned player by handle",
                provider=provider,
                player_id=players[0].id,
            )
            return players[0]
        if len(players) > 1:
            logger.warning(
                "Ambiguous unowned-player match for OAuth handle; not auto-linking",
                provider=provider,
            )
        return None

    async def _find_existing_auth_user(
        self,
        session: AsyncSession,
        oauth_info: schemas.OAuthUserInfo,
    ) -> tuple[models.AuthUser | None, models.User | None]:
        """Returns (auth_user, matched_player).

        - auth_user  — existing AuthUser to reuse (may be None)
        - matched_player — player found in provider table (may be None if no match)

        If matched_player is returned without auth_user, the caller should create
        a new AuthUser and set ``matched_player.auth_user_id`` to link them.

        matched_player is resolved first by verified ``provider_user_id`` and, if
        that misses, by the verified handle of an UNOWNED player
        (``_find_unowned_player_by_handle``) — the relaxed path that stops
        first-login duplicates for players who already exist as a shadow identity
        but were never OAuth-verified.

        FAIL-CLOSED: a matching email alone NEVER reuses an existing account.
        Email is not proof that the OAuth caller owns the account (emails can be
        changed without verification, and some providers return an email with no
        verified flag), so reuse by email would be a full account takeover. Reuse
        is therefore anchored only on the
        cryptographically-confirmed ``provider_user_id`` — either an existing
        ``OAuthConnection`` (handled by the caller) or a player already pinned to
        this exact provider subject. Anything else is treated as a NEW user; a
        real owner links additional providers via the authenticated link flow.
        """
        player = await self._find_player_by_provider_record(session, oauth_info)
        if player is None:
            # Relaxed reconciliation: no verified provider_user_id yet, so fall
            # back to an UNOWNED player already carrying this provider's handle
            # (their shadow tournament identity). Returned as matched_player
            # (auth_user=None) so the caller creates the AuthUser, links the
            # player, and pins the now-verified provider_user_id via
            # _attach_verified_social_account — next login uses the fast path.
            player = await self._find_unowned_player_by_handle(session, oauth_info)
            if player is None:
                return None, None
            return None, player

        # Primary: players.user.auth_user_id direct link.
        auth_user = await self._find_auth_user_for_player(session, player)
        if auth_user is not None:
            return auth_user, player

        # Fallback: scan OAuthConnections for the player's other social accounts.
        # Safe because the anchor `player` is itself confirmed by provider_user_id
        # above; this only backfills a missing auth_user_id link.
        auth_user = await self._find_auth_user_via_oauth_connections(session, player)
        # Return player regardless of whether auth_user is found, so the caller
        # can set matched_player.auth_user_id when building a new AuthUser.
        return auth_user, player

    async def _free_username(self, session: AsyncSession, base_username: str) -> str:
        """First free ``base``, ``base1``, ``base2``, … for a new OAuth signup.

        The taken set is fetched once and the suffix is picked in memory: probing
        the table per candidate cost a query per collision, and a popular handle
        collides repeatedly. Case-insensitive, like every username collision.
        """
        taken = await self.users.usernames_with_prefix(session, base_username)
        username = base_username
        counter = 1
        while username.lower() in taken:
            username = f"{base_username}{counter}"
            counter += 1
        return username

    async def find_or_create_user(
        self, session: AsyncSession, oauth_info: schemas.OAuthUserInfo, token_data: dict[str, Any]
    ) -> models.AuthUser:
        """Find the existing user by OAuth connection, or create a new one."""
        oauth_conn = await self.connections.get_by_provider_subject(
            session, provider=oauth_info.provider.value, provider_user_id=oauth_info.provider_user_id
        )

        if oauth_conn:
            previous_avatar_url = oauth_conn.avatar_url
            oauth_conn.username = oauth_info.username
            oauth_conn.display_name = oauth_info.display_name
            oauth_conn.avatar_url = oauth_info.avatar_url
            oauth_conn.email = oauth_info.email
            _store_tokens(oauth_conn, oauth_info.provider.value, token_data)
            oauth_conn.provider_data = oauth_info.raw_data

            await session.commit()
            await session.refresh(oauth_conn)

            auth_user = await self.users.get(session, oauth_conn.auth_user_id)

            if await self._fill_player_avatar(
                session, auth_user.id, oauth_info.avatar_url, replaces=previous_avatar_url
            ):
                await session.commit()

            await self._attach_verified_social_account(session, auth_user, oauth_info)
            logger.info(f"Existing {oauth_info.provider} user logged in: {oauth_info.username}")
            return auth_user

        auth_user, matched_player = await self._find_existing_auth_user(session, oauth_info)

        # If an existing auth user was found via OAuth-connection fallback,
        # backfill the missing players.user.auth_user_id link so future lookups
        # use the fast path and don't need the fallback scan again.
        backfilled = False
        if auth_user is not None and matched_player is not None:
            try:
                if backfilled := await self._link_player_if_unowned(session, matched_player, auth_user):
                    logger.info(
                        "Backfilled players.user.auth_user_id link for existing auth user",
                        auth_user_id=auth_user.id,
                        player_id=matched_player.id,
                    )
            except IntegrityError:
                await session.rollback()
                logger.warning(
                    "Race condition backfilling player auth_user_id link; ignoring",
                    auth_user_id=auth_user.id,
                    player_id=matched_player.id,
                )

        if not auth_user:
            # One rule for every provider: the name people see there (Discord
            # global name, BattleTag without "#1234", Twitch display name), not
            # whichever raw handle that provider happens to call "username".
            username = await self._free_username(
                session,
                suggest_username(oauth_info.display_name, suggest_username(oauth_info.username, "player")),
            )

            auth_user = models.AuthUser(
                email=oauth_info.email or f"{oauth_info.provider_user_id}@{oauth_info.provider.value}.oauth",
                username=username,
                hashed_password=None,
                first_name=oauth_info.display_name,
                is_verified=bool(oauth_info.raw_data.get("verified")),
            )
            try:
                await self.users.create(session, auth_user)

                await self.accounts.assign_default_role(session, auth_user.id)

                # If the player record was found but had no auth_user_id link yet,
                # set the link now so future OAuth logins (via other providers)
                # can find this AuthUser through the same player.
                linked = False
                if matched_player is not None:
                    linked = await self._link_player_if_unowned(session, matched_player, auth_user)
                    if linked:
                        logger.info(
                            "Linked new auth user to existing player",
                            auth_user_id=auth_user.id,
                            player_id=matched_player.id,
                        )

                if not linked:
                    # Either no existing player matched by social account, or the
                    # matched player is already owned by a different auth user
                    # (never steal that link — see `_link_player_if_unowned`).
                    # Either way this brand-new auth user still needs its own
                    # bare players.user identity backbone. No battletag yet;
                    # reconciled later at registration.
                    await self.accounts.ensure_player(session, auth_user)
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "OAuth email already belongs to an existing account. "
                        "Sign in first and link this OAuth provider from account settings."
                    ),
                ) from exc
            await self._fill_player_avatar(session, auth_user.id, oauth_info.avatar_url)

            logger.info(f"New user created via {oauth_info.provider}: {username}")

        try:
            await self.connections.create(session, _new_connection(auth_user, oauth_info, token_data))
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This OAuth account is already linked",
            ) from exc
        await session.refresh(auth_user)
        if backfilled:
            # The account just gained the player's workspace memberships.
            await self.cache.invalidate_rbac(auth_user.id)

        logger.success(f"{oauth_info.provider.value.title()} account linked to user: {auth_user.username}")

        await self._attach_verified_social_account(session, auth_user, oauth_info)
        return auth_user

    async def link_to_user(
        self,
        session: AsyncSession,
        auth_user: models.AuthUser,
        oauth_info: schemas.OAuthUserInfo,
        token_data: dict[str, Any],
    ) -> models.OAuthConnection:
        """Attach a proven provider identity to an already-authenticated account.

        Idempotent for a re-link of the SAME provider account to the SAME
        account (tokens are refreshed). Rejected with 409 only when a surviving
        connection for this exact provider subject belongs to a DIFFERENT
        account -- the detail spells out the way out, because there is no
        self-service way to break someone else's link from here: sign in with
        that provider (it lands on that other account), delete it in account
        settings, then link again.
        """
        existing_conn = await self.connections.get_by_provider_subject(
            session, provider=oauth_info.provider.value, provider_user_id=oauth_info.provider_user_id
        )

        # A user may link MULTIPLE accounts of the same provider (e.g. two
        # battle.net) — each a distinct verified social identity. Only re-linking
        # the *same* external account to a *different* user is blocked (below).
        if existing_conn:
            if existing_conn.auth_user_id == auth_user.id:
                _store_tokens(existing_conn, oauth_info.provider.value, token_data)
                await session.commit()
                await session.refresh(existing_conn)
                return existing_conn
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"This {oauth_info.provider.value.title()} account ({oauth_info.handle}) is "
                    "already linked to a different account here. Sign in with it to reach that account, "
                    "delete the account in Account settings, then link it again."
                ),
            )

        oauth_conn = await self.connections.create(session, _new_connection(auth_user, oauth_info, token_data))
        await session.commit()
        await session.refresh(oauth_conn)

        logger.success(f"{oauth_info.provider.value.title()} account linked to user {auth_user.username}")

        await self._attach_verified_social_account(session, auth_user, oauth_info, claim_subject=True)
        return oauth_conn


oauth_accounts = OAuthAccountService()
