"""The ``notification_delivery`` subscriber: one queue, two event types.

Both ``notification.created`` and ``notification.broadcast`` bind to the same
queue (routing key ``notification.*``) because they are the same job -- get a
message to Discord -- and one queue is one place to look when the DLQ fills.

Errors propagate: ``observe_message_processing`` re-raises, FastStream rejects
without requeue and the message lands in ``notification_delivery.dlq``.
``ponytail:`` no retry policy, the DLQ is drained by hand; add one when a
transient failure mode actually shows up there.
"""

from __future__ import annotations

from typing import Any

from faststream.rabbit import Channel, RabbitMessage

from shared.messaging.config import NOTIFICATION_DELIVERY_QUEUE, NOTIFICATIONS_EXCHANGE
from shared.observability import observe_message_processing
from shared.schemas.events import NotificationBroadcastEvent, NotificationCreatedEvent
from src.core import db
from src.services.notification_delivery.service import notification_delivery_service

__all__ = ("register",)

# Isolated channel, like the invalidation consumer's: a check-in fan-out of
# hundreds of DMs must not sit in front of the RPC traffic's QoS window.
_DELIVERY_CHANNEL = Channel(prefetch_count=4)


def register(broker: Any, logger: Any) -> None:
    # `msg` MUST be annotated RabbitMessage -- with a looser annotation
    # FastStream treats it as another payload field and every message fails
    # validation straight into the DLQ.
    @broker.subscriber(NOTIFICATION_DELIVERY_QUEUE, exchange=NOTIFICATIONS_EXCHANGE, channel=_DELIVERY_CHANNEL)
    async def deliver_notification(data: dict[str, Any], msg: RabbitMessage) -> None:
        async with observe_message_processing(
            queue=NOTIFICATION_DELIVERY_QUEUE,
            handler="deliver_notification",
            message=msg,
            logger=logger,
        ) as context:
            event_type = data.get("event_type")
            async with db.async_session_maker() as session:
                if event_type == "notification.created":
                    status = await notification_delivery_service.deliver_personal(
                        session, NotificationCreatedEvent.model_validate(data)
                    )
                elif event_type == "notification.broadcast":
                    status = await notification_delivery_service.deliver_broadcast(
                        session, NotificationBroadcastEvent.model_validate(data)
                    )
                else:
                    # The queue binds ``notification.*``; a third routing key
                    # would arrive here before its handler exists.
                    status = "skipped_unknown_event"
            if status != "sent":
                # The status is the metric label and the log line: a skip is a
                # normal outcome that still has to be countable.
                context.set_status(status)
                context.logger.bind(status=status).info(f"Notification delivery {status}")
