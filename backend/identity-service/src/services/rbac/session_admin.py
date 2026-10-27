from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import pagination
from src import schemas
from src.services.rbac_policy import RbacPolicy, rbac_policy
from src.services.sessions import SessionService, sessions


class SessionAdminService:
    """The superuser session inventory across every auth account."""

    def __init__(
        self,
        *,
        policy: RbacPolicy = rbac_policy,
        session_reader: SessionService = sessions,
    ) -> None:
        self._policy = policy
        self._sessions = session_reader

    async def list_auth_sessions(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        params: schemas.SessionListParams,
    ) -> dict:
        """List logical auth sessions across all users (superuser only, paginated).

        Aggregation, status filter, sort and pagination all run in SQL;
        ``total`` reflects the filtered set.
        """
        self._policy.require_superuser(current_user)
        summaries, total = await self._sessions.list_all_sessions(
            session,
            params,
            user_id=params.user_id,
            search=params.search,
            status=params.status,
        )
        return pagination.paginated_dict(
            [schemas.AdminSessionRead.model_validate(summary) for summary in summaries], total, params
        )


session_admin = SessionAdminService()
