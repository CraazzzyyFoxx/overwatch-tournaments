"""Subscription Collection Service.

Periodically queries active/open tournaments that require subscriptions, collects
the auth_user_ids of registered participants, and runs SubscriptionResolver to check
and update their entitlements in Postgres.

Each resolved attempt also appends a row to ``subscriptions.check_log`` (via the
resolver's log sink), which is what makes the collection history visible in the
admin Subscription-collection tab.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import SubscriptionCollectionSource
from shared.services.registration_window import registration_open_clause
from shared.services.subscriptions import parse_requirement
from shared.services.subscriptions.wiring import build_resolver
from src.core.broker import optional_broker
from src.domain.subscription_collection import TournamentTarget, _chunked

__all__ = (
    "SubscriptionCollectionService",
    "TournamentTarget",
    "collect_subscriptions_for_active_tournaments",
    "find_tournaments_requiring_subscriptions",
    "load_auth_user_ids_for_tournament",
    "subscription_collection_service",
)


class SubscriptionCollectionService:
    """Sweeps active tournaments and refreshes participant subscription verdicts."""

    async def find_tournaments_requiring_subscriptions(
        self, session: AsyncSession, *, workspace_id: int | None = None
    ) -> list[TournamentTarget]:
        """Active, open tournaments whose registration form enforces a subscription.

        ``require_subscription`` is the per-tournament toggle; the rule itself belongs to
        the workspace. The join to ``subscriptions.requirement`` is deliberately **inner**:
        a workspace with no rule has nothing to collect, which is exactly the row the old
        per-form code dropped afterwards via ``if not requirement.requirements``. A rule
        that parses to nothing enforceable, or fails to parse at all, is still dropped
        below -- an empty blob is reachable through the workspace editor too.

        ``workspace_id`` narrows the sweep to one tenant, which is how a
        workspace-scoped admin triggers a re-check without touching anybody else's
        tournaments.
        """
        stmt = (
            sa.select(
                models.Tournament.id,
                models.Tournament.workspace_id,
                models.WorkspaceSubscriptionRequirement.requirement_json,
            )
            .join(
                models.BalancerRegistrationForm,
                models.Tournament.id == models.BalancerRegistrationForm.tournament_id,
            )
            .join(
                models.WorkspaceSubscriptionRequirement,
                sa.and_(
                    models.WorkspaceSubscriptionRequirement.workspace_id == models.Tournament.workspace_id,
                    models.WorkspaceSubscriptionRequirement.is_default.is_(True),
                ),
            )
            .where(
                models.Tournament.is_finished.is_(False),
                models.BalancerRegistrationForm.require_subscription.is_(True),
                # Openness is the REGISTRATION schedule window now, not a form flag.
                registration_open_clause(),
            )
        )
        if workspace_id is not None:
            stmt = stmt.where(models.Tournament.workspace_id == workspace_id)
        targets: list[TournamentTarget] = []
        for tournament_id, target_workspace_id, blob in (await session.execute(stmt)).all():
            try:
                requirement = parse_requirement(blob)
            except ValueError:
                logger.warning(
                    "Skipping subscription collection for tournament_id={}: malformed requirement",
                    tournament_id,
                )
                continue
            if not requirement.requirements:
                continue
            targets.append(
                TournamentTarget(
                    tournament_id=tournament_id,
                    workspace_id=target_workspace_id,
                    providers=tuple(requirement.providers),
                )
            )
        return targets

    async def load_auth_user_ids_for_tournament(self, session: AsyncSession, tournament_id: int) -> list[int]:
        """Get all auth_user_ids for registered participants in a tournament."""
        stmt = (
            sa.select(models.User.auth_user_id)
            .select_from(models.BalancerRegistration)
            .join(
                models.WorkspaceMember,
                models.BalancerRegistration.workspace_member_id == models.WorkspaceMember.id,
            )
            .join(models.User, models.WorkspaceMember.player_id == models.User.id)
            .where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.deleted_at.is_(None),
                models.BalancerRegistration.status != "withdrawn",
                models.User.auth_user_id.isnot(None),
            )
            .distinct()
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.all() if row[0] is not None]

    async def collect_subscriptions_for_active_tournaments(
        self,
        session: AsyncSession,
        *,
        workspace_id: int | None = None,
        discord_bot_token: str | None = None,
        twitch_client_id: str | None = None,
        broker: Any | None = None,
        proxy: str | None = None,
        batch_size: int = 50,
        source: str = SubscriptionCollectionSource.scheduled,
    ) -> int:
        """Sweep every tournament that gates on a subscription, refreshing verdicts.

        Commits per batch. Without a commit nothing survives the session -- neither the
        entitlement upserts nor the history rows — and a single long transaction over
        every participant of every open tournament would hold locks for the whole
        sweep. Committing per batch also means a provider outage halfway through keeps
        the work already done.

        ``workspace_id`` limits the sweep to one workspace's tournaments (the manual
        admin trigger passes the caller's authorization scope); the scheduled tick
        omits it and sweeps everything.

        Returns the total number of users processed.
        """
        targets = await find_tournaments_requiring_subscriptions(session, workspace_id=workspace_id)
        if not targets:
            return 0

        # Optional: with a broker the Discord roles for a whole batch come back in one
        # RPC; without one the strategy falls back to per-user Discord REST.
        active_broker = optional_broker(broker)

        resolver = build_resolver(
            session,
            discord_bot_token=discord_bot_token,
            twitch_client_id=twitch_client_id,
            broker=active_broker,
            proxy=proxy,
        )

        total_processed = 0

        for target in targets:
            auth_user_ids = await load_auth_user_ids_for_tournament(session, target.tournament_id)
            if not auth_user_ids:
                continue

            for batch in _chunked(auth_user_ids, max(1, batch_size)):
                try:
                    results = await resolver.resolve(
                        workspace_id=target.workspace_id,
                        auth_user_ids=batch,
                        providers=list(target.providers),
                        force_refresh=True,
                        source=source,
                    )
                    await session.commit()
                    total_processed += len(results)
                except Exception as exc:
                    # One tournament's provider trouble must not abort the sweep. The
                    # rollback is what lets the next batch reuse the session.
                    await session.rollback()
                    logger.error(
                        "Error processing subscription collection for tournament_id={}: {}",
                        target.tournament_id,
                        exc,
                    )
                    break

            logger.info(
                "Collected subscriptions for tournament_id={}, workspace_id={}, users_count={}",
                target.tournament_id,
                target.workspace_id,
                len(auth_user_ids),
            )

        return total_processed


subscription_collection_service = SubscriptionCollectionService()
find_tournaments_requiring_subscriptions = subscription_collection_service.find_tournaments_requiring_subscriptions
load_auth_user_ids_for_tournament = subscription_collection_service.load_auth_user_ids_for_tournament
collect_subscriptions_for_active_tournaments = (
    subscription_collection_service.collect_subscriptions_for_active_tournaments
)
