"""Subscription provider-config and workspace-requirement CRUD.

Both tables are written with ``INSERT ... ON CONFLICT DO UPDATE`` against a *named*
constraint, and both reads that follow an upsert must pass ``populate_existing=True``:
the upsert changes the row behind the ORM's back, so a plain SELECT would be served
from the identity map and return the pre-upsert JSON blob.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository.base import BaseRepository

PROVIDER_CONFIG_CONSTRAINT = "uq_subscription_config_workspace_provider"
REQUIREMENT_CONSTRAINT = "uq_subscription_requirement_workspace_name"


class SubscriptionProviderConfigRepository(BaseRepository[models.SubscriptionProviderConfig]):
    def __init__(self) -> None:
        super().__init__(models.SubscriptionProviderConfig)

    async def list_for_workspace(
        self, session: AsyncSession, workspace_id: int
    ) -> Sequence[models.SubscriptionProviderConfig]:
        result = await session.execute(
            self.select().where(models.SubscriptionProviderConfig.workspace_id == workspace_id)
        )
        return result.scalars().all()

    async def list_with_guild(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        providers: Sequence[str],
    ) -> Sequence[tuple[Any, bool, dict[str, Any] | None, str | None]]:
        """Provider rows plus the workspace Discord guild, one statement."""
        if not providers:
            return ()
        cfg = models.SubscriptionProviderConfig
        rows = await session.execute(
            sa.select(cfg.provider, cfg.enabled, cfg.config_json, models.Workspace.discord_guild_id)
            .join(models.Workspace, models.Workspace.id == cfg.workspace_id)
            .where(cfg.workspace_id == workspace_id, cfg.provider.in_(list(providers)))
        )
        return rows.all()

    async def get_for_provider(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        provider: Any,
        populate_existing: bool = False,
    ) -> models.SubscriptionProviderConfig | None:
        query = self.select().where(
            models.SubscriptionProviderConfig.workspace_id == workspace_id,
            models.SubscriptionProviderConfig.provider == provider,
        )
        if populate_existing:
            query = query.execution_options(populate_existing=True)
        result = await session.execute(query)
        return result.scalars().one_or_none()

    async def upsert(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        provider: Any,
        enabled: bool,
        config_json: dict[str, Any],
    ) -> None:
        statement = pg_insert(models.SubscriptionProviderConfig).values(
            workspace_id=workspace_id,
            provider=provider,
            enabled=enabled,
            config_json=config_json,
        )
        await session.execute(
            statement.on_conflict_do_update(
                constraint=PROVIDER_CONFIG_CONSTRAINT,
                set_={
                    "enabled": statement.excluded.enabled,
                    "config_json": statement.excluded.config_json,
                    "updated_at": sa.func.now(),
                },
            )
        )


class WorkspaceSubscriptionRequirementRepository(BaseRepository[models.WorkspaceSubscriptionRequirement]):
    def __init__(self) -> None:
        super().__init__(models.WorkspaceSubscriptionRequirement)

    async def get_default_blob(self, session: AsyncSession, workspace_id: int) -> dict[str, Any]:
        """The workspace's default rule as a raw blob, or ``{}`` when it has none."""
        requirement = models.WorkspaceSubscriptionRequirement
        blob = await session.scalar(
            sa.select(requirement.requirement_json).where(
                requirement.workspace_id == workspace_id,
                requirement.is_default.is_(True),
            )
        )
        return dict(blob) if blob else {}

    async def upsert_default(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        name: str,
        requirement_json: dict[str, Any],
    ) -> None:
        """Replace the workspace's default rule.

        Conflicts on ``(workspace_id, name)`` rather than on the partial "one default
        per workspace" index: the named constraint is the stable target.
        """
        statement = pg_insert(models.WorkspaceSubscriptionRequirement).values(
            workspace_id=workspace_id,
            name=name,
            requirement_json=requirement_json,
            is_default=True,
        )
        await session.execute(
            statement.on_conflict_do_update(
                constraint=REQUIREMENT_CONSTRAINT,
                set_={
                    "requirement_json": statement.excluded.requirement_json,
                    "is_default": statement.excluded.is_default,
                    "updated_at": sa.func.now(),
                },
            )
        )


ENTITLEMENT_CONSTRAINT = "uq_subscription_entitlement_scope"


class SubscriptionEntitlementRepository(BaseRepository[models.SubscriptionEntitlement]):
    def __init__(self) -> None:
        super().__init__(models.SubscriptionEntitlement)

    async def list_for_users(
        self,
        session: AsyncSession,
        *,
        workspace_id: int,
        auth_user_ids: Sequence[int],
        providers: Sequence[str],
    ) -> Sequence[models.SubscriptionEntitlement]:
        if not auth_user_ids or not providers:
            return ()
        result = await session.scalars(
            self.select().where(
                models.SubscriptionEntitlement.workspace_id == workspace_id,
                models.SubscriptionEntitlement.auth_user_id.in_(list(auth_user_ids)),
                models.SubscriptionEntitlement.provider.in_(list(providers)),
            )
        )
        return result.all()

    async def upsert_rows(self, session: AsyncSession, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            return
        stmt = pg_insert(models.SubscriptionEntitlement).values(list(rows))
        await session.execute(
            stmt.on_conflict_do_update(
                constraint=ENTITLEMENT_CONSTRAINT,
                set_={
                    "state": stmt.excluded.state,
                    "tier_rank": stmt.excluded.tier_rank,
                    "tier_label": stmt.excluded.tier_label,
                    "source": stmt.excluded.source,
                    "checked_at": stmt.excluded.checked_at,
                    "expires_at": stmt.excluded.expires_at,
                    "evidence_json": stmt.excluded.evidence_json,
                    "updated_at": sa.func.now(),
                },
            )
        )


class SubscriptionCheckLogRepository(BaseRepository[models.SubscriptionCheckLog]):
    def __init__(self) -> None:
        super().__init__(models.SubscriptionCheckLog)

    def add(self, session: AsyncSession, row: models.SubscriptionCheckLog) -> models.SubscriptionCheckLog:
        """Stage one journal row. No flush — rides the caller's transaction."""
        session.add(row)
        return row



__all__ = (
    "ENTITLEMENT_CONSTRAINT",
    "PROVIDER_CONFIG_CONSTRAINT",
    "REQUIREMENT_CONSTRAINT",
    "SubscriptionCheckLogRepository",
    "SubscriptionEntitlementRepository",
    "SubscriptionProviderConfigRepository",
    "WorkspaceSubscriptionRequirementRepository",
)
