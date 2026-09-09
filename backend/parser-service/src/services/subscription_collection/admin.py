"""Admin operations for subscription collection: health read, history, trigger.

Mirrors ``services/overwatch_rank/admin.py``. The one structural difference is
where "current state" comes from: rank keeps a dedicated ``battle_tag_state``
bookkeeping table, whereas subscriptions already have ``subscriptions.entitlement``
— one row per (workspace, user, provider) with ``state``/``checked_at`` — so this
module reads that instead of duplicating it.

Reads never commit; the trigger does.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import SubscriptionCheckState, SubscriptionCollectionSource
from shared.services import settings_provider
from shared.services.subscriptions import parse_requirement
from shared.services.subscriptions.wiring import build_resolver
from src import models
from src.core.broker import optional_broker

from . import service

__all__ = (
    "SubscriptionAdminService",
    "get_collection_stats",
    "get_user_collection_status",
    "list_check_log",
    "subscription_admin_service",
    "trigger_collection",
)

#: Outcomes that mean the check itself failed, as opposed to answering "no".
_FAILURE_STATES = (SubscriptionCheckState.error.value, SubscriptionCheckState.unknown.value)


def _now() -> datetime:
    return datetime.now(UTC)


class SubscriptionAdminService:
    """Admin health dashboard, check-log history, and manual re-check trigger."""

    async def get_collection_stats(self, session: AsyncSession, *, workspace_id: int | None = None) -> dict[str, Any]:
        """Assemble the admin health dashboard: DB aggregates + current config echo.

        Aggregates deliberately parallel the rank dashboard: population size and its
        state mix, distinct-user coverage over 24h/7d, the last successful check, and
        the last-24h outcome mix with an error rate.

        ``workspace_id`` narrows every aggregate to one tenant — the caller's
        authorization scope (see ``rpc/subscription.py``). The config echo stays
        global because the collector itself is: interval, batch size and the on/off
        switch are one setting for the whole deployment.
        """
        ent = models.SubscriptionEntitlement
        log = models.SubscriptionCheckLog
        now = _now()

        def _scoped(stmt: Any, column: Any) -> Any:
            return stmt if workspace_id is None else stmt.where(column == workspace_id)

        by_state = {
            str(state): int(count)
            for state, count in (
                await session.execute(
                    _scoped(sa.select(ent.state, sa.func.count()), ent.workspace_id).group_by(ent.state)
                )
            ).all()
        }
        by_provider = {
            str(provider): int(count)
            for provider, count in (
                await session.execute(
                    _scoped(sa.select(ent.provider, sa.func.count()), ent.workspace_id).group_by(ent.provider)
                )
            ).all()
        }
        total = int(await session.scalar(_scoped(sa.select(sa.func.count()).select_from(ent), ent.workspace_id)) or 0)
        tracked_users = int(
            await session.scalar(_scoped(sa.select(sa.func.count(sa.distinct(ent.auth_user_id))), ent.workspace_id))
            or 0
        )
        never_checked = int(
            await session.scalar(
                _scoped(sa.select(sa.func.count()).select_from(ent), ent.workspace_id).where(ent.checked_at.is_(None))
            )
            or 0
        )
        last_success_at = await session.scalar(
            _scoped(sa.select(sa.func.max(ent.checked_at)), ent.workspace_id).where(
                ent.state == SubscriptionCheckState.active.value
            )
        )
        last_check_at = await session.scalar(_scoped(sa.select(sa.func.max(log.created_at)), log.workspace_id))

        async def _coverage(delta: timedelta) -> int:
            return int(
                await session.scalar(
                    _scoped(sa.select(sa.func.count(sa.distinct(log.auth_user_id))), log.workspace_id).where(
                        log.created_at > now - delta
                    )
                )
                or 0
            )

        checks_24h = {
            str(state): int(count)
            for state, count in (
                await session.execute(
                    _scoped(sa.select(log.state, sa.func.count()), log.workspace_id)
                    .where(log.created_at > now - timedelta(hours=24))
                    .group_by(log.state)
                )
            ).all()
        }
        checks_total = sum(checks_24h.values())
        failures = sum(checks_24h.get(state, 0) for state in _FAILURE_STATES)

        cfg = await settings_provider.get_subscription_collection_config(session)
        targets = await service.find_tournaments_requiring_subscriptions(session, workspace_id=workspace_id)

        return {
            "total": total,
            "tracked_users": tracked_users,
            "never_checked": never_checked,
            "by_state": by_state,
            "by_provider": by_provider,
            "coverage_24h": await _coverage(timedelta(hours=24)),
            "coverage_7d": await _coverage(timedelta(days=7)),
            "last_success_at": last_success_at,
            "last_check_at": last_check_at,
            "checks_24h": checks_24h,
            "checks_24h_total": checks_total,
            "error_rate_24h": round(failures / checks_total, 4) if checks_total else 0.0,
            "active_tournaments": len(targets),
            "enabled": cfg.enabled,
            "interval_seconds": cfg.interval_seconds,
            "batch_size": cfg.batch_size,
        }

    async def list_check_log(
        self,
        session: AsyncSession,
        *,
        workspace_id: int | None = None,
        state: str | None = None,
        source: str | None = None,
        provider: str | None = None,
        user_id: int | None = None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Most-recent subscription check attempts (newest first), filterable + cursor-paged.

        Resolves the owning ``players.user`` id (LEFT JOIN — null when the auth account
        has no player profile) so a log row is clickable through to the player detail
        view, exactly as the rank fetch log is.

        ``user_id`` filters by that same domain player id rather than by
        ``auth_user_id``: it is the id every admin surface already holds, and scoping
        through the join keeps one identifier in play across the whole tab.

        ``workspace_id`` is the caller's authorization scope, not a user-supplied
        filter: a workspace-scoped admin must never page into another tenant's
        history.
        """
        log = models.SubscriptionCheckLog
        player = models.User
        query = (
            sa.select(log, player.id.label("user_id"), player.name.label("user_name"))
            .outerjoin(player, player.auth_user_id == log.auth_user_id)
            .order_by(log.id.desc())
        )
        if workspace_id is not None:
            query = query.where(log.workspace_id == workspace_id)
        if state:
            query = query.where(log.state == state)
        if source:
            query = query.where(log.source == source)
        if provider:
            query = query.where(log.provider == provider)
        if user_id is not None:
            query = query.where(player.id == user_id)
        if before_id is not None:
            query = query.where(log.id < before_id)
        query = query.limit(max(1, min(limit, 200)))
        rows = (await session.execute(query)).all()
        return [
            {
                "id": row.SubscriptionCheckLog.id,
                "workspace_id": row.SubscriptionCheckLog.workspace_id,
                "auth_user_id": row.SubscriptionCheckLog.auth_user_id,
                "user_id": row.user_id,
                "user_name": row.user_name,
                "provider": row.SubscriptionCheckLog.provider,
                "state": row.SubscriptionCheckLog.state,
                "tier_rank": row.SubscriptionCheckLog.tier_rank,
                "tier_label": row.SubscriptionCheckLog.tier_label,
                "source": row.SubscriptionCheckLog.source,
                "mechanism": row.SubscriptionCheckLog.mechanism,
                "reason": row.SubscriptionCheckLog.reason,
                "error": row.SubscriptionCheckLog.error,
                "created_at": row.SubscriptionCheckLog.created_at,
            }
            for row in rows
        ]

    async def _auth_user_id_for_player(self, session: AsyncSession, user_id: int) -> int | None:
        return await session.scalar(sa.select(models.User.auth_user_id).where(models.User.id == user_id))

    async def get_user_collection_status(
        self, session: AsyncSession, user_id: int, *, workspace_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Per-(workspace, provider) entitlement state for one player.

        Keyed by the domain ``players.user`` id — the same id the admin player search
        and the rank tab use — and resolved to ``auth_user_id`` here, because that is
        what the subscription tables key on. Returns ``[]`` for a player with no linked
        auth account, which the caller renders as "nothing to collect".

        ``workspace_id`` is the caller's authorization scope: a workspace-scoped admin
        sees this player's entitlement in their own workspace only, never the full
        cross-tenant list of workspaces the player belongs to.
        """
        auth_user_id = await _auth_user_id_for_player(session, user_id)
        if auth_user_id is None:
            return []

        ent = models.SubscriptionEntitlement
        ws = models.Workspace
        query = (
            sa.select(ent, ws.name.label("workspace_name"))
            .outerjoin(ws, ws.id == ent.workspace_id)
            .where(ent.auth_user_id == auth_user_id)
        )
        if workspace_id is not None:
            query = query.where(ent.workspace_id == workspace_id)
        rows = (await session.execute(query.order_by(ent.workspace_id.asc(), ent.provider.asc()))).all()

        return [
            {
                "workspace_id": row.SubscriptionEntitlement.workspace_id,
                "workspace_name": row.workspace_name,
                "provider": row.SubscriptionEntitlement.provider,
                "state": row.SubscriptionEntitlement.state,
                "tier_rank": row.SubscriptionEntitlement.tier_rank,
                "tier_label": row.SubscriptionEntitlement.tier_label,
                "source": row.SubscriptionEntitlement.source,
                "checked_at": row.SubscriptionEntitlement.checked_at,
                "expires_at": row.SubscriptionEntitlement.expires_at,
                "reason": (row.SubscriptionEntitlement.evidence_json or {}).get("reason"),
            }
            for row in rows
        ]

    async def _requirements_for_user(
        self, session: AsyncSession, auth_user_id: int
    ) -> list[tuple[int, tuple[str, ...]]]:
        """(workspace_id, providers) the player is actually registered under.

        A manual re-check only makes sense for tournaments whose form enforces a
        subscription AND where this player is a live registrant: resolving anything
        else would write entitlements for a rule nobody is being held to.

        The rule comes from the workspace, joined **inner** for the same reason as in
        ``service.find_tournaments_requiring_subscriptions``: a workspace with no rule
        holds nobody to anything, so there is nothing to re-check.
        """
        reg = models.BalancerRegistration
        member = models.WorkspaceMember
        player = models.User
        form = models.BalancerRegistrationForm
        req = models.WorkspaceSubscriptionRequirement
        rows = (
            await session.execute(
                sa.select(models.Tournament.workspace_id, req.requirement_json)
                .select_from(reg)
                .join(member, reg.workspace_member_id == member.id)
                .join(player, member.player_id == player.id)
                .join(models.Tournament, reg.tournament_id == models.Tournament.id)
                .join(form, form.tournament_id == models.Tournament.id)
                .join(
                    req,
                    sa.and_(req.workspace_id == models.Tournament.workspace_id, req.is_default.is_(True)),
                )
                .where(
                    player.auth_user_id == auth_user_id,
                    reg.deleted_at.is_(None),
                    reg.status != "withdrawn",
                    form.require_subscription.is_(True),
                )
            )
        ).all()

        merged: dict[int, set[str]] = {}
        for workspace_id, blob in rows:
            try:
                requirement = parse_requirement(blob)
            except ValueError:
                continue
            if requirement.requirements:
                merged.setdefault(workspace_id, set()).update(requirement.providers)
        return [(workspace_id, tuple(sorted(providers))) for workspace_id, providers in merged.items()]

    async def trigger_collection(
        self,
        session: AsyncSession,
        *,
        user_id: int | None = None,
        providers: Sequence[str] | None = None,
        workspace_id: int | None = None,
        discord_bot_token: str | None = None,
        twitch_client_id: str | None = None,
        broker: Any | None = None,
        proxy: str | None = None,
    ) -> int:
        """Force a live re-check for one player, or sweep every active tournament.

        Runs inline rather than enqueuing (as the rank trigger does): a subscription
        check is at most one provider call per requested provider, so a single player
        is bounded work, and the admin expects the table to be fresh when the dialog
        stops spinning.

        ``workspace_id`` is the caller's authorization scope: the sweep is limited to
        that workspace's tournaments, and a single-player re-check only touches the
        rules that workspace holds them to.

        Returns the number of (user, provider) checks performed.
        """
        active_broker = optional_broker(broker)

        if user_id is None:
            cfg = await settings_provider.get_subscription_collection_config(session)
            return await service.collect_subscriptions_for_active_tournaments(
                session,
                workspace_id=workspace_id,
                discord_bot_token=discord_bot_token,
                twitch_client_id=twitch_client_id,
                broker=active_broker,
                proxy=proxy,
                batch_size=cfg.batch_size,
                source=SubscriptionCollectionSource.manual,
            )

        auth_user_id = await _auth_user_id_for_player(session, user_id)
        if auth_user_id is None:
            return 0

        scopes = [
            scope
            for scope in await _requirements_for_user(session, auth_user_id)
            if workspace_id is None or scope[0] == workspace_id
        ]
        if not scopes:
            return 0

        wanted = set(providers) if providers else None
        resolver = build_resolver(
            session,
            discord_bot_token=discord_bot_token,
            twitch_client_id=twitch_client_id,
            broker=active_broker,
            proxy=proxy,
        )
        checked = 0
        for scope_workspace_id, scope_providers in scopes:
            targets = [p for p in scope_providers if wanted is None or p in wanted]
            if not targets:
                continue
            verdicts = await resolver.resolve(
                workspace_id=scope_workspace_id,
                auth_user_ids=[auth_user_id],
                providers=targets,
                force_refresh=True,
                source=SubscriptionCollectionSource.manual,
            )
            checked += len(verdicts.get(auth_user_id, {}))
        await session.commit()
        return checked


subscription_admin_service = SubscriptionAdminService()
get_collection_stats = subscription_admin_service.get_collection_stats
list_check_log = subscription_admin_service.list_check_log
_auth_user_id_for_player = subscription_admin_service._auth_user_id_for_player
get_user_collection_status = subscription_admin_service.get_user_collection_status
_requirements_for_user = subscription_admin_service._requirements_for_user
trigger_collection = subscription_admin_service.trigger_collection
