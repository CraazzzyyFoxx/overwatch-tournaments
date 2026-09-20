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

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import normalize_social_handle, oauth_handle, social_provider_for_oauth
from shared.repository import (
    AuthUserRepository,
    OAuthConnectionRepository,
    SocialAccountRepository,
    UserRepository,
)
from shared.services import social_identity
from src import models, schemas
from src.services.auth_users import AuthUserService, auth_users
from src.services.oauth_providers import OAuthProviderRegistry, oauth_providers


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
    ) -> None:
        self.providers = providers
        self.accounts = accounts
        self.users = users
        self.connections = connections
        self.socials = socials
        self.players = players

    async def handle_callback(
        self, session: AsyncSession, provider_name: str, code: str
    ) -> tuple[models.AuthUser, dict[str, Any]]:
        """
        Handle OAuth callback for any provider
        Returns (auth_user, token_data)
        """
        provider = self.providers.get(provider_name)

        # Exchange code for token
        token_data = await provider.exchange_code(code)

        # Get user info from provider
        oauth_user_info = await provider.get_user_info(token_data["access_token"])

        # Find or create user
        auth_user = await self.find_or_create_user(session, oauth_user_info, token_data)

        return auth_user, token_data

    async def _find_player_by_provider_record(
        self,
        session: AsyncSession,
        oauth_info: schemas.OAuthUserInfo,
    ) -> models.User | None:
        """
        Find the player (players.user) via the unified ``social_account`` table
        WITHOUT requiring an AuthUser link. Returns None if not found.

        FAIL-CLOSED (review H3): only a cryptographically-confirmed match on the
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
        """
        Fallback lookup: scan OAuthConnections for any social accounts attached to
        this player (Discord, Twitch, BattleTag). Used when the player has no
        ``auth_user_id`` set yet (e.g. created via legacy code path that omitted
        the link). Returns None if none or more than one distinct AuthUser is found.
        """
        accounts = await self.socials.list_by_user(session, player.id)
        handles: list[tuple[str, str]] = [(account.provider, account.username.lower()) for account in accounts]
        if not handles:
            return None

        # One statement for the whole candidate set: the decision below only needs
        # to know whether the handles converge on a single auth user, so probing
        # them one at a time cost a query per social account for no extra signal.
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

    @staticmethod
    def _link_player_if_unowned(player: models.User, auth_user: models.AuthUser) -> bool:
        """Set ``player.auth_user_id = auth_user.id`` iff the player has no owner yet.

        A player already linked to a *different* auth user is left untouched —
        that is a conflict for the admin user-merge tool to resolve, never
        something to silently overwrite here. Returns True if the link was set.
        """
        if player.auth_user_id is None:
            player.auth_user_id = auth_user.id
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

    @staticmethod
    def _oauth_handle(oauth_info: schemas.OAuthUserInfo) -> str:
        """The provider's canonical handle to store as the verified social username."""
        return oauth_handle(
            oauth_info.provider.value,
            oauth_info.username,
            oauth_info.raw_data,
        )

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
        and the identity is attached to THIS auth user's own player. Without
        that release the leftover captured the verification instead: the link
        reported success while the linking user's profile gained nothing, with
        no error anywhere to explain it.
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

        try:
            await social_identity.upsert_social_account(
                session,
                user_id=player.id,
                provider=provider,
                username=self._oauth_handle(oauth_info),
                provider_user_id=oauth_info.provider_user_id,
                is_verified=True,
            )
        except social_identity.SocialHandleConflict:
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
        normalized = normalize_social_handle(provider, self._oauth_handle(oauth_info))
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
        """
        Returns (auth_user, matched_player).
        - auth_user  — existing AuthUser to reuse (may be None)
        - matched_player — player found in provider table (may be None if no match)

        If matched_player is returned without auth_user, the caller should create
        a new AuthUser and set ``matched_player.auth_user_id`` to link them.

        matched_player is resolved first by verified ``provider_user_id`` and, if
        that misses, by the verified handle of an UNOWNED player
        (``_find_unowned_player_by_handle``) — the relaxed path that stops
        first-login duplicates for players who already exist as a shadow identity
        but were never OAuth-verified.

        FAIL-CLOSED (review C1/C2): a matching email is NEVER used to reuse an
        existing account. Email is not proof that the OAuth caller owns the
        account (emails can be changed without verification, and some providers
        return an email with no verified flag), so reusing an account by email
        enabled full account takeover. Reuse is therefore anchored only on the
        cryptographically-confirmed ``provider_user_id`` — either an existing
        ``OAuthConnection`` (handled by the caller) or a player already pinned to
        this exact provider subject. Anything else is treated as a NEW user; a
        real owner links additional providers via the authenticated link flow.
        """
        # Provider-subject player lookup (provider_user_id only — see method doc).
        player = await self._find_player_by_provider_record(session, oauth_info)
        if player is None:
            # Relaxed reconciliation (requested): no verified provider_user_id
            # yet, so fall back to an UNOWNED player already carrying this
            # provider's handle (their shadow tournament identity). Returned as
            # matched_player (auth_user=None) so the caller creates the AuthUser,
            # links the player, and pins the now-verified provider_user_id via
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
        # above; this only backfills the auth_user_id link for legacy players
        # created before the link was auto-populated on first login.
        auth_user = await self._find_auth_user_via_oauth_connections(session, player)
        # Return player regardless of whether auth_user is found, so the caller
        # can set matched_player.auth_user_id when building a new AuthUser.
        return auth_user, player

    async def _free_username(self, session: AsyncSession, base_username: str) -> str:
        """First free ``base``, ``base1``, ``base2``, … for a new OAuth signup.

        The taken set is fetched once and the suffix is picked in memory: probing
        the table per candidate cost a query per collision, and a popular handle
        collides repeatedly.
        """
        taken = await self.users.usernames_with_prefix(session, base_username)
        username = base_username
        counter = 1
        while username in taken:
            username = f"{base_username}{counter}"
            counter += 1
        return username

    async def find_or_create_user(
        self, session: AsyncSession, oauth_info: schemas.OAuthUserInfo, token_data: dict[str, Any]
    ) -> models.AuthUser:
        """
        Find existing user by OAuth connection or create new user
        """
        # Check if OAuth connection already exists
        oauth_conn = await self.connections.get_by_provider_subject(
            session, provider=oauth_info.provider.value, provider_user_id=oauth_info.provider_user_id
        )

        if oauth_conn:
            # Update OAuth connection info
            oauth_conn.username = oauth_info.username
            oauth_conn.display_name = oauth_info.display_name
            oauth_conn.avatar_url = oauth_info.avatar_url
            oauth_conn.email = oauth_info.email
            oauth_conn.access_token = token_data["access_token"]
            oauth_conn.refresh_token = token_data.get("refresh_token")

            if "expires_in" in token_data:
                oauth_conn.token_expires_at = datetime.now(UTC) + timedelta(seconds=token_data["expires_in"])

            oauth_conn.provider_data = oauth_info.raw_data

            await session.commit()
            await session.refresh(oauth_conn)

            # Get associated auth user
            auth_user = await self.users.get(session, oauth_conn.auth_user_id)

            # Keep primary avatar in sync (used by /me)
            if oauth_info.avatar_url and auth_user.avatar_url != oauth_info.avatar_url:
                auth_user.avatar_url = oauth_info.avatar_url
                await session.commit()
                await session.refresh(auth_user)

            await self._attach_verified_social_account(session, auth_user, oauth_info)
            logger.info(f"Existing {oauth_info.provider} user logged in: {oauth_info.username}")
            return auth_user

        auth_user, matched_player = await self._find_existing_auth_user(session, oauth_info)

        # If an existing auth user was found via OAuth-connection fallback,
        # backfill the missing players.user.auth_user_id link so future lookups
        # use the fast path and don't need the fallback scan again.
        if auth_user is not None and matched_player is not None:
            if self._link_player_if_unowned(matched_player, auth_user):
                try:
                    await session.flush()
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

        # Create new user if doesn't exist
        if not auth_user:
            username = await self._free_username(session, oauth_info.username)

            auth_user = models.AuthUser(
                email=oauth_info.email or f"{oauth_info.provider_user_id}@{oauth_info.provider.value}.oauth",
                username=username,
                hashed_password=None,  # OAuth users don't have password
                first_name=oauth_info.display_name,
                avatar_url=oauth_info.avatar_url,
                is_verified=bool(oauth_info.raw_data.get("verified")),
            )
            session.add(auth_user)
            try:
                await session.flush()  # Get the user ID

                await self.accounts.assign_default_role(session, auth_user.id)

                # If the player record was found but had no auth_user_id link yet,
                # set the link now so future OAuth logins (via other providers)
                # can find this AuthUser through the same player.
                linked = False
                if matched_player is not None:
                    linked = self._link_player_if_unowned(matched_player, auth_user)
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

            logger.info(f"New user created via {oauth_info.provider}: {username}")

        # Create OAuth connection
        oauth_conn = models.OAuthConnection(
            auth_user_id=auth_user.id,
            provider=oauth_info.provider.value,
            provider_user_id=oauth_info.provider_user_id,
            email=oauth_info.email,
            username=oauth_info.username,
            display_name=oauth_info.display_name,
            avatar_url=oauth_info.avatar_url,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            provider_data=oauth_info.raw_data,
            token_expires_at=datetime.now(UTC) + timedelta(seconds=token_data["expires_in"])
            if "expires_in" in token_data
            else None,
        )

        session.add(oauth_conn)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This OAuth account is already linked",
            ) from exc
        await session.refresh(auth_user)

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
        # Check if this OAuth account is already linked to another user
        existing_conn = await self.connections.get_by_provider_subject(
            session, provider=oauth_info.provider.value, provider_user_id=oauth_info.provider_user_id
        )

        # A user may link MULTIPLE accounts of the same provider (e.g. two
        # battle.net) — each a distinct verified social identity. We only block
        # re-linking the *same* external account to a *different* user (below).

        if existing_conn:
            if existing_conn.auth_user_id == auth_user.id:
                # Already linked to this user, just update tokens
                existing_conn.access_token = token_data["access_token"]
                existing_conn.refresh_token = token_data.get("refresh_token")

                if "expires_in" in token_data:
                    existing_conn.token_expires_at = datetime.now(UTC) + timedelta(seconds=token_data["expires_in"])

                await session.commit()
                await session.refresh(existing_conn)
                return existing_conn
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"This {oauth_info.provider.value.title()} account ({self._oauth_handle(oauth_info)}) is "
                    "already linked to a different account here. Sign in with it to reach that account, "
                    "delete the account in Account settings, then link it again."
                ),
            )

        # Create new OAuth connection
        oauth_conn = models.OAuthConnection(
            auth_user_id=auth_user.id,
            provider=oauth_info.provider.value,
            provider_user_id=oauth_info.provider_user_id,
            email=oauth_info.email,
            username=oauth_info.username,
            display_name=oauth_info.display_name,
            avatar_url=oauth_info.avatar_url,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            provider_data=oauth_info.raw_data,
        )

        if "expires_in" in token_data:
            oauth_conn.token_expires_at = datetime.now(UTC) + timedelta(seconds=token_data["expires_in"])

        session.add(oauth_conn)
        await session.commit()
        await session.refresh(oauth_conn)

        logger.success(f"{oauth_info.provider.value.title()} account linked to user {auth_user.username}")

        await self._attach_verified_social_account(session, auth_user, oauth_info, claim_subject=True)
        return oauth_conn


oauth_accounts = OAuthAccountService()
