"""Turn a delivery event into one Discord message -- or into a recorded skip.

Two flows, one shape: decide whether this event still deserves a message, claim
the right to send it in the ledger, then enqueue the bot command in the *same*
transaction as the claim. That order is the whole design: the ledger row and
the outbox command commit together, so there is no state where the platform
believes it sent something it did not, and a redelivered event (the outbox is
at-least-once) finds the claim taken and sends nothing.

Both methods answer with a status string rather than a bool or an exception.
Skips are normal -- no Discord linked, the group switched off, no channel
configured -- and the consumer turns the answer into the metric label that
tells "nothing to do" apart from "something broke". Only a genuine fault
raises, and the existing consumer semantics send that to the DLQ.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from shared import models
from shared.messaging.config import DISCORD_COMMANDS_QUEUE
from shared.messaging.outbox import enqueue_outbox_event
from shared.repository.notification import (
    NotificationDeliveryRepository,
    NotificationPreferenceRepository,
    NotificationRepository,
    NotificationWorkspaceConfigRepository,
)
from shared.schemas.events import DiscordCommandEvent, NotificationBroadcastEvent, NotificationCreatedEvent
from shared.services.notifications import wants_discord_dm
from shared.services.subscriptions.strategies import load_provider_user_ids
from src.core import config
from src.domain.notification_render import render_discord

__all__ = ("NotificationDeliveryService", "notification_delivery_service")

#: ``ponytail:`` D11 -- DMs are rendered in Russian for everyone. The server
#: does not know a user's language (only the browser's ``NEXT_LOCALE`` cookie
#: does), and storing it belongs to the email issue, where a locale is
#: mandatory rather than a nicety.
_DM_LOCALE = "ru"


class NotificationDeliveryService:
    def __init__(self) -> None:
        self._notifications = NotificationRepository()
        self._deliveries = NotificationDeliveryRepository()
        self._preferences = NotificationPreferenceRepository()
        self._configs = NotificationWorkspaceConfigRepository()

    async def deliver_personal(self, session: Any, event: NotificationCreatedEvent) -> str:
        """DM the recipient of one personal notification row.

        The row is re-read rather than carried in the event on purpose: an
        operator can retire a notification between the write and the drain, and
        ``expires_at`` is the only thing that says so.
        """
        row = await self._notifications.get(session, event.notification_id)
        if row is None or row.recipient_auth_user_id is None or _expired(row.expires_at):
            return "skipped_missing"

        stored = await self._preferences.stored_discord_dm(session, row.recipient_auth_user_id)
        if not wants_discord_dm(stored, row.kind):
            return "skipped_pref_off"

        payload = row.payload_json or {}
        tournament_id = payload.get("tournament_id")
        if isinstance(tournament_id, int):
            # Read now, not at write time: the organizer's switch also stops a
            # DM still waiting in the outbox. A deleted tournament mutes nothing.
            dms_enabled = (
                await session.execute(
                    sa.select(models.Tournament.discord_dms_enabled).where(models.Tournament.id == tournament_id)
                )
            ).scalar_one_or_none()
            if dms_enabled is False:
                return "skipped_tournament_muted"

        linked = await load_provider_user_ids(
            session,
            auth_user_ids=[row.recipient_auth_user_id],
            oauth_provider="discord",
        )
        # Earliest-linked account wins when somebody connected several.
        targets = linked.get(row.recipient_auth_user_id) or []
        if not targets:
            return "skipped_no_discord"
        target = targets[0]

        claimed = await self._deliveries.claim(
            session,
            channel="discord_dm",
            target=target,
            dedupe_key=f"notification:{row.id}",
            kind=row.kind,
            notification_id=row.id,
            workspace_id=row.source_workspace_id,
        )
        if not claimed:
            return "duplicate"

        workspace_name, image_url = await _branding(session, row.source_workspace_id, payload)
        card = render_discord(
            row.kind,
            payload,
            locale=_DM_LOCALE,
            site_url=config.settings.public_site_url,
            workspace_name=workspace_name,
            image_url=image_url,
            personal=True,
        )
        await enqueue_outbox_event(
            session,
            DiscordCommandEvent(
                action="send_dm",
                discord_user_id=int(target),
                card=card,
                allow_mentions=False,
            ),
            exchange="",
            routing_key=DISCORD_COMMANDS_QUEUE.name,
        )
        await session.commit()
        return "sent"

    async def deliver_broadcast(self, session: Any, event: NotificationBroadcastEvent) -> str:
        """Post one event to the workspace's notification channel.

        A workspace that never opened the settings screen has no row and
        therefore no channel: broadcasts for it are dropped, not queued. The
        producer does not know (and must not have to know) whether anybody is
        listening.
        """
        stored = await self._configs.for_workspace(session, event.workspace_id)
        if stored is None or stored.discord_channel_id is None or event.kind not in (stored.broadcast_kinds or []):
            return "skipped_no_config"

        channel_id = int(stored.discord_channel_id)
        claimed = await self._deliveries.claim(
            session,
            channel="discord_channel",
            target=str(channel_id),
            dedupe_key=f"{event.kind}:{event.dedupe_key}",
            kind=event.kind,
            workspace_id=event.workspace_id,
        )
        if not claimed:
            return "duplicate"

        workspace_name, image_url = await _branding(session, event.workspace_id, event.payload)
        card = render_discord(
            event.kind,
            event.payload,
            locale=stored.locale,
            site_url=config.settings.public_site_url,
            workspace_name=workspace_name,
            image_url=image_url,
        )
        await enqueue_outbox_event(
            session,
            DiscordCommandEvent(
                action="post_message",
                channel_id=channel_id,
                card=card,
                allow_mentions=False,
            ),
            exchange="",
            routing_key=DISCORD_COMMANDS_QUEUE.name,
        )
        await session.commit()
        return "sent"


async def _branding(
    session: Any, workspace_id: int | None, payload: Mapping[str, Any]
) -> tuple[str | None, str | None]:
    """The organizer's name, and the card's picture: tournament logo, else workspace icon.

    Read at delivery rather than snapshotted into the payload, so the card shows
    the organizer's current branding; a row deleted since just leaves it plain.
    """
    name = icon = logo = None
    if workspace_id is not None:
        row = (
            await session.execute(
                sa.select(models.Workspace.name, models.Workspace.icon_url).where(models.Workspace.id == workspace_id)
            )
        ).first()
        if row is not None:
            name, icon = row
    tournament_id = payload.get("tournament_id")
    if isinstance(tournament_id, int):
        logo = (
            await session.execute(sa.select(models.Tournament.logo_url).where(models.Tournament.id == tournament_id))
        ).scalar_one_or_none()
    return name, logo or icon


def _expired(expires_at: datetime | None) -> bool:
    """Retired before the DM went out. Naive values are read as UTC."""
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


notification_delivery_service = NotificationDeliveryService()
