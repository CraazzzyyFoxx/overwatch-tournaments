from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.repository import RefreshTokenRepository
from src import models

SessionStatus = Literal["active", "revoked", "expired"]
DEFAULT_USER_SESSION_HISTORY_LIMIT = 20
_refresh_token_repo = RefreshTokenRepository()


class SessionService:
    """Helpers for listing and aggregating logical auth sessions."""

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

    @staticmethod
    async def list_user_sessions(
        session: AsyncSession,
        user_id: int,
        *,
        current_session_id: str | None = None,
        history_limit: int = DEFAULT_USER_SESSION_HISTORY_LIMIT,
    ) -> list[dict]:
        tokens = await _refresh_token_repo.list_by_user(session, user_id)
        summaries = SessionService._summaries_from_tokens(tokens, current_session_id=current_session_id)
        return SessionService._limit_user_session_history(summaries, history_limit=history_limit)

    @staticmethod
    async def get_user_session(
        session: AsyncSession,
        user_id: int,
        session_id: UUID,
        *,
        current_session_id: str | None = None,
    ) -> dict | None:
        tokens = await _refresh_token_repo.list_by_user_session(
            session,
            user_id=user_id,
            session_id=session_id,
        )
        if not tokens:
            return None
        summaries = SessionService._summaries_from_tokens(tokens, current_session_id=current_session_id)
        return summaries[0] if summaries else None

    @staticmethod
    async def list_all_sessions(
        session: AsyncSession,
        *,
        user_id: int | None = None,
        search: str | None = None,
        status: SessionStatus | None = None,
    ) -> list[dict]:
        # Collapse refresh-token rotation into one row per logical session
        # directly in SQL (the latest token per ``session_id``) instead of
        # streaming the ENTIRE auth.refresh_token table into Python and
        # aggregating there. Rotation writes a new token row on every refresh,
        # so token count dwarfs session count; the old full-table load was the
        # bottleneck behind the slow admin session inventory.
        #
        # ``user_id`` is constant within a session, so scoping it before the
        # DISTINCT ON is safe and keeps the (session_id) index selective.
        latest_ids = (
            select(models.RefreshToken.id)
            .distinct(models.RefreshToken.session_id)
            .order_by(models.RefreshToken.session_id, models.RefreshToken.created_at.desc())
        )
        if user_id is not None:
            latest_ids = latest_ids.where(models.RefreshToken.user_id == user_id)

        query = (
            select(models.RefreshToken)
            .options(selectinload(models.RefreshToken.user))
            .where(models.RefreshToken.id.in_(latest_ids.scalar_subquery()))
        )

        if search:
            term = f"%{search}%"
            # Match against the session's latest token + its owner (email and
            # username are user-level and constant across a session; user_agent
            # and ip_address reflect the session's current client).
            query = query.join(models.AuthUser, models.AuthUser.id == models.RefreshToken.user_id).where(
                or_(
                    models.AuthUser.email.ilike(term),
                    models.AuthUser.username.ilike(term),
                    models.RefreshToken.user_agent.ilike(term),
                    models.RefreshToken.ip_address.ilike(term),
                )
            )

        result = await session.execute(query)
        tokens = result.scalars().all()
        summaries = SessionService._summaries_from_tokens(tokens, include_user=True)
        if status is not None:
            summaries = [summary for summary in summaries if summary["status"] == status]
        return summaries
