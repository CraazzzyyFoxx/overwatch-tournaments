"""SQLAlchemy implementations of the subscription persistence boundaries.

Kept separate from ``entitlements`` so the resolver's decision table
stays importable and testable without a database.

Every read is a single statement covering all requested providers -- the resolver
promises the DB read does not fan out per provider, which is what keeps a list
view of hundreds of registrants cheap.

Two implementations, matching the resolver's two write boundaries:
``SqlEntitlementStore`` (current state, destructive upsert) and
``SqlCheckLogSink`` (append-only history).

``load_configs`` is the single place a ``ProviderConfigRow`` is born, and therefore
the single injection point for workspace-scoped values: it joins ``workspace`` to
source ``guild_id``, so the resolver keeps reading it out of ``config`` unchanged.

``load_requirement`` is the second such value, and the reason this file -- not the
call sites -- owns it: the admission rule is configured per workspace, so a gate
that only knows a tournament form should not also have to know which table the rule
lives in.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import SubscriptionCollectionSource
from shared.repository import (
    SubscriptionCheckLogRepository,
    SubscriptionEntitlementRepository,
    SubscriptionProviderConfigRepository,
    WorkspaceSubscriptionRequirementRepository,
)
from shared.services.subscriptions import SubscriptionVerdict
from shared.services.subscriptions.entitlements import ProviderConfigRow, StoredEntitlement

__all__ = ("SqlCheckLogSink", "SqlEntitlementStore")


def _entitlement_row(
    workspace_id: int,
    auth_user_id: int,
    provider: str,
    verdict: SubscriptionVerdict,
) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "auth_user_id": auth_user_id,
        "provider": provider,
        "state": verdict.state,
        "tier_rank": verdict.tier_rank,
        "tier_label": verdict.tier_label,
        "source": verdict.source,
        "checked_at": verdict.checked_at,
        "expires_at": verdict.expires_at,
        "evidence_json": verdict.evidence or {},
    }


class SqlEntitlementStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._configs = SubscriptionProviderConfigRepository()
        self._requirements = WorkspaceSubscriptionRequirementRepository()
        self._entitlements = SubscriptionEntitlementRepository()

    async def load_configs(self, workspace_id: int, providers: Sequence[str]) -> dict[str, ProviderConfigRow]:
        rows = await self._configs.list_with_guild(self._session, workspace_id=workspace_id, providers=providers)
        return {
            provider: ProviderConfigRow(
                provider=provider,
                enabled=bool(enabled),
                # The guild belongs to the workspace, never to the provider blob.
                config={**(config or {}), "guild_id": guild_id or ""},
            )
            for provider, enabled, config, guild_id in rows
        }

    async def load_requirement(self, workspace_id: int) -> dict[str, Any] | None:
        blob = await self._requirements.get_default_blob(self._session, workspace_id)
        return blob or None

    async def load_entitlements(
        self,
        workspace_id: int,
        auth_user_ids: Sequence[int],
        providers: Sequence[str],
    ) -> dict[tuple[int, str], StoredEntitlement]:
        rows = await self._entitlements.list_for_users(
            self._session,
            workspace_id=workspace_id,
            auth_user_ids=auth_user_ids,
            providers=providers,
        )
        return {
            (row.auth_user_id, row.provider): StoredEntitlement(
                state=row.state,
                tier_rank=row.tier_rank,
                tier_label=row.tier_label,
                source=row.source,
                checked_at=row.checked_at,
                expires_at=row.expires_at,
                evidence=dict(row.evidence_json or {}),
            )
            for row in rows
        }

    async def upsert(
        self,
        workspace_id: int,
        auth_user_id: int,
        provider: str,
        verdict: SubscriptionVerdict,
    ) -> None:
        await self._entitlements.upsert_rows(
            self._session, [_entitlement_row(workspace_id, auth_user_id, provider, verdict)]
        )

    async def upsert_many(
        self,
        workspace_id: int,
        provider: str,
        verdicts: Mapping[int, SubscriptionVerdict],
    ) -> None:
        if not verdicts:
            return
        rows = [
            _entitlement_row(workspace_id, auth_user_id, provider, verdict)
            for auth_user_id, verdict in verdicts.items()
        ]
        await self._entitlements.upsert_rows(self._session, rows)


class SqlCheckLogSink:
    """Appends check attempts to ``subscriptions.check_log``.

    ``add`` only — no flush, no commit. The row lands with whatever
    transaction the caller commits.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._logs = SubscriptionCheckLogRepository()

    async def log_check(
        self,
        *,
        workspace_id: int,
        auth_user_id: int,
        provider: str,
        state: str,
        source: str = SubscriptionCollectionSource.scheduled,
        verdict: SubscriptionVerdict | None = None,
        error: str | None = None,
    ) -> None:
        evidence = verdict.evidence if verdict is not None else None
        reason = evidence.get("reason") if isinstance(evidence, dict) else None
        self._logs.add(
            self._session,
            models.SubscriptionCheckLog(
                workspace_id=workspace_id,
                auth_user_id=auth_user_id,
                provider=provider,
                state=str(state),
                tier_rank=verdict.tier_rank if verdict is not None else None,
                tier_label=verdict.tier_label if verdict is not None else None,
                source=str(source),
                mechanism=verdict.source if verdict is not None else None,
                reason=str(reason)[:64] if reason else None,
                error=error[:2000] if error else None,
            ),
        )
