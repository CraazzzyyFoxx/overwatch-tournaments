"""Refresh-token lifecycle and the logical sessions they aggregate into."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared.repository import RefreshTokenRepository
from src import models
from src.core import config
from src.services.security import TokenCodec, token_codec
from src.services.session_cache import SessionCache, session_cache

__all__ = [
    "DEFAULT_USER_SESSION_HISTORY_LIMIT",
    "RefreshTokenService",
    "SessionService",
    "SessionStatus",
    "refresh_tokens",
    "sessions",
]

settings = config.settings

SessionStatus = Literal["active", "revoked", "expired"]
DEFAULT_USER_SESSION_HISTORY_LIMIT = 20


class RefreshTokenService:
    """Issues, looks up and revokes refresh tokens; owns session blacklisting."""

    def __init__(
        self,
        *,
        codec: TokenCodec = token_codec,
        cache: SessionCache = session_cache,
        tokens: RefreshTokenRepository | None = None,
        config: Any = settings,
    ) -> None:
        self._codec = codec
        self._cache = cache
        self._tokens = tokens or RefreshTokenRepository()
        self._config = config

    async def issue(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        token: str,
        session_id: UUID | None = None,
        session_started_at: datetime | None = None,
        user_agent: str | None = None,
        ip_address: str | None = None,
        request: Any | None = None,
        commit: bool = True,
    ) -> models.RefreshToken:
        """Store a refresh token.

        Client metadata may be supplied explicitly (used by the headless RPC
        flows, where the gateway forwards the original UA/IP) or extracted from
        a request (the legacy HTTP path); the explicit values win.
        """
        expires_at = datetime.now(UTC) + timedelta(days=self._config.REFRESH_TOKEN_EXPIRE_DAYS)
        if session_id is None or session_started_at is None:
            generated_session_id, generated_started_at = self._codec.new_session()
            session_id = session_id or generated_session_id
            session_started_at = session_started_at or generated_started_at

        req_user_agent, req_ip_address = self._codec.client_metadata(request)

        refresh_token = models.RefreshToken(
            token=self._codec.hash_refresh_token(token),
            user_id=user_id,
            session_id=session_id,
            session_started_at=session_started_at,
            expires_at=expires_at,
            user_agent=user_agent or req_user_agent,
            ip_address=ip_address or req_ip_address,
        )
        session.add(refresh_token)
        if commit:
            await session.commit()
        return refresh_token

    async def get_record(self, session: AsyncSession, token: str) -> models.RefreshToken | None:
        """Any record for the raw token, revoked or not."""
        return await self._tokens.get_by_hashes(session, self._codec.refresh_token_hashes(token))

    async def get_active_record(self, session: AsyncSession, token: str) -> models.RefreshToken | None:
        """The record for the raw token, only while it is live."""
        return await self._tokens.get_active_by_hashes(
            session,
            self._codec.refresh_token_hashes(token),
            now=datetime.now(UTC),
        )

    async def get_grace_record(self, session: AsyncSession, token: str) -> models.RefreshToken | None:
        """Return a just-rotated token that may be rotated once more, else None.

        A client whose rotation response never arrived — the network path changed
        mid-flight, i.e. the classic VPN toggle — is left holding the token the
        server already revoked. Replaying it looks exactly like a stolen-token
        replay, so it is honoured only when ALL of these hold:

        * it was revoked within ``REFRESH_ROTATION_GRACE_SECONDS`` (a lost
          response is retried within seconds; a hoarded stolen token is not),
        * it has not expired,
        * its session family is still alive — an explicit logout or session
          revoke leaves no active token, so this can never resurrect a session
          the user closed.

        Outside that window reuse stays fatal: the caller falls through to
        ``handle_reuse``, which revokes the whole session family.
        """
        return await self._tokens.get_grace_candidate(
            session,
            self._codec.refresh_token_hashes(token),
            now=datetime.now(UTC),
            grace_seconds=max(int(self._config.REFRESH_ROTATION_GRACE_SECONDS), 0),
        )

    async def revoke_token(self, session: AsyncSession, token: str, *, commit: bool = True) -> bool:
        """Revoke one refresh token. False only when the token is unknown."""
        existed = await self._tokens.revoke_by_hashes(
            session,
            self._codec.refresh_token_hashes(token),
            now=datetime.now(UTC),
        )
        if commit:
            await session.commit()
        return existed

    async def revoke_session(
        self,
        session: AsyncSession,
        user_id: int,
        session_id: UUID,
        *,
        commit: bool = True,
        blacklist: bool = True,
    ) -> int:
        """Revoke active tokens for a logical session family.

        ``blacklist=False`` skips banning the ``sid`` claim, for the one caller
        that retires a session's refresh tokens while KEEPING the session alive:
        the rotation-grace replay, which immediately mints a fresh pair under the
        same ``sid``. Banning it there would kill the token just issued.
        """
        count = await self._tokens.revoke_session(
            session,
            user_id=user_id,
            session_id=session_id,
            now=datetime.now(UTC),
        )
        if commit:
            await session.commit()
        if blacklist:
            # Block any still-valid access token carrying this sid until it expires.
            await self._cache.blacklist_session(str(session_id), self._codec.access_token_ttl_seconds)
        return count

    async def revoke_client_family(
        self,
        session: AsyncSession,
        user_id: int,
        user_agent: str | None,
        ip_address: str | None,
        *,
        commit: bool = True,
    ) -> int:
        """Revoke active tokens for the same browser session.

        We scope by browser user-agent first so different browsers on the same
        device keep working independently. IP is only used as a fallback when
        user-agent data is unavailable.
        """
        count, session_ids = await self._tokens.revoke_client_family(
            session,
            user_id=user_id,
            user_agent=user_agent,
            ip_address=ip_address,
            now=datetime.now(UTC),
        )
        if commit:
            await session.commit()
        await self._cache.blacklist_sessions(session_ids, self._codec.access_token_ttl_seconds)
        return count

    async def revoke_all(self, session: AsyncSession, user_id: int, *, commit: bool = True) -> int:
        """Revoke every refresh token of a user."""
        count, session_ids = await self._tokens.revoke_all_for_user(
            session,
            user_id=user_id,
            now=datetime.now(UTC),
        )
        if commit:
            await session.commit()
        await self._cache.blacklist_sessions(session_ids, self._codec.access_token_ttl_seconds)
        return count

    async def handle_reuse(self, session: AsyncSession, token: str) -> None:
        """Contain a replayed refresh token that is no longer live.

        Revocation is scoped as narrowly as the stored record allows so one
        stale tab does not log the user out everywhere.
        """
        reused = await self._tokens.get_by_hashes(session, self._codec.refresh_token_hashes(token))
        if reused is None:
            return

        # WARNING, not ERROR: reuse is an expected consequence of ordinary
        # client behaviour (a stale tab replaying a rotated token, a mobile
        # app resuming from background) and is fully handled right below by
        # revoking the affected session. As an ERROR it opened a Sentry issue
        # per occurrence with nothing to fix. Alert on the rate of this
        # message instead, which is what actually indicates token theft.
        logger.bind(user_id=str(reused.user_id)).warning(
            "Refresh token reuse detected; revoking only the matching browser session"
        )

        session_id = getattr(reused, "session_id", None)
        user_agent = getattr(reused, "user_agent", None)
        ip_address = getattr(reused, "ip_address", None)

        if session_id is not None:
            await self.revoke_session(session, reused.user_id, session_id)
        elif user_agent or ip_address:
            await self.revoke_client_family(session, reused.user_id, user_agent, ip_address)
        else:
            await self.revoke_all(session, reused.user_id)

    async def purge_expired(self, session: AsyncSession, *, retention: timedelta) -> int:
        """Delete tokens that expired more than ``retention`` ago; returns the count.

        Well past the rotation grace and the token lifetime, so no live or
        replayed token can match a deleted row. The session lists keep their
        history for ``retention`` after a session's last token expired.
        """
        return await self._tokens.delete_expired_before(session, datetime.now(UTC) - retention)


class SessionService:
    """Aggregates refresh tokens into the logical sessions the UI shows."""

    def __init__(self, *, tokens: RefreshTokenRepository | None = None) -> None:
        self._tokens = tokens or RefreshTokenRepository()

    @staticmethod
    def _limit_user_session_history(
        summaries: Sequence[dict],
        *,
        history_limit: int = DEFAULT_USER_SESSION_HISTORY_LIMIT,
    ) -> list[dict]:
        if history_limit < 0:
            history_limit = 0

        active_sessions = [summary for summary in summaries if summary["status"] == "active"]
        historical_sessions = [summary for summary in summaries if summary["status"] != "active"]

        return [*active_sessions, *historical_sessions[:history_limit]]

    @staticmethod
    def _session_status(token: models.RefreshToken, now: datetime) -> SessionStatus:
        if token.is_revoked:
            return "revoked"
        if token.expires_at <= now:
            return "expired"
        return "active"

    @staticmethod
    def _summaries_from_tokens(
        tokens: Sequence[models.RefreshToken],
        *,
        current_session_id: str | None = None,
        include_user: bool = False,
    ) -> list[dict]:
        now = datetime.now(UTC)
        latest_by_session: dict[str, models.RefreshToken] = {}

        for token in tokens:
            session_id = str(token.session_id)
            current = latest_by_session.get(session_id)
            if current is None or token.created_at > current.created_at:
                latest_by_session[session_id] = token

        summaries: list[dict] = []
        for session_id, latest_token in latest_by_session.items():
            summary = {
                "session_id": session_id,
                "status": SessionService._session_status(latest_token, now),
                "login_at": latest_token.session_started_at,
                "last_seen_at": latest_token.created_at,
                "expires_at": latest_token.expires_at,
                "revoked_at": latest_token.revoked_at if latest_token.is_revoked else None,
                "user_agent": latest_token.user_agent,
                "ip_address": latest_token.ip_address,
                "is_current": current_session_id is not None and current_session_id == session_id,
            }

            if include_user:
                user = latest_token.user
                summary.update(
                    {
                        "user_id": latest_token.user_id,
                        "email": user.email if user is not None else None,
                        "username": user.username if user is not None else None,
                    }
                )

            summaries.append(summary)

        summaries.sort(
            key=lambda item: (
                item["status"] == "active",
                item["login_at"] or datetime.min.replace(tzinfo=UTC),
                item["last_seen_at"] or datetime.min.replace(tzinfo=UTC),
            ),
            reverse=True,
        )
        return summaries

    async def list_user_sessions(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        current_session_id: str | None = None,
        history_limit: int = DEFAULT_USER_SESSION_HISTORY_LIMIT,
    ) -> list[dict]:
        tokens = await self._tokens.list_by_user(session, user_id)
        summaries = self._summaries_from_tokens(tokens, current_session_id=current_session_id)
        return self._limit_user_session_history(summaries, history_limit=history_limit)

    async def get_user_session(
        self,
        session: AsyncSession,
        user_id: int,
        session_id: UUID,
        *,
        current_session_id: str | None = None,
    ) -> dict | None:
        tokens = await self._tokens.list_by_user_session(session, user_id=user_id, session_id=session_id)
        if not tokens:
            return None
        summaries = self._summaries_from_tokens(tokens, current_session_id=current_session_id)
        return summaries[0] if summaries else None

    async def list_all_sessions(
        self,
        session: AsyncSession,
        *,
        user_id: int | None = None,
        search: str | None = None,
        status: SessionStatus | None = None,
    ) -> list[dict]:
        # One row per logical session, collapsed in SQL: rotation makes the
        # token count dwarf the session count, so aggregating in Python meant
        # streaming the whole table.
        tokens = await self._tokens.latest_per_session(session, user_id=user_id, search=search)
        summaries = self._summaries_from_tokens(tokens, include_user=True)
        if status is not None:
            summaries = [summary for summary in summaries if summary["status"] == status]
        return summaries


refresh_tokens = RefreshTokenService()
sessions = SessionService()
