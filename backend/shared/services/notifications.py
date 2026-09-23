"""The single way to append to a user's notification inbox.

Two invariants follow from ``notify()`` never committing:

1. A notification only exists if the mutation that caused it did. The helper
   runs *inside* the caller's transaction, before its ``session.commit()``, the
   same contract ``shared/services/audit.py:record_audit`` has. Notifying about
   a rolled-back invite is worse than not notifying at all.
2. The realtime signal rides that same transaction. ``notify()`` stages it
   through ``shared.services.realtime.emit``, which publishes from the
   session's ``after_commit`` -- so a rolled-back invite signals nothing, and
   no caller has to remember to fire anything afterwards.

No text is stored for system kinds. A row carries ``kind`` plus a
``payload_json`` snapshot of the named domain fields the frontend interpolates
into ``t("notifications.kinds.<kind>", payload)``, so a translation fix reaches
rows written a year ago and a deleted team still renders its name.
``announcement.published`` is the one kind whose payload *is* author-written
text, in every locale the audience requires.

De-duplication is opt-in per call: a producer that can name "the same event"
passes ``dedupe_key`` (``tournament:10``, ``encounter:5:<iso>``) and ``notify()``
returns the existing row for that kind, key and recipient instead of writing a
second one. Kinds with a legitimate repeat ("you were invited to that team
again") pass no key. The check is a SELECT over a non-unique index, not
``ON CONFLICT``: ``ponytail:`` two racing transactions can still write a rare
duplicate; a unique index + ``ON CONFLICT`` is the upgrade if that is observed.

Delivery outside the app rides the same transaction: a personal row enqueues a
``NotificationCreatedEvent`` in the outbox (app-service turns it into a Discord
DM), and ``broadcast()`` enqueues a channel post without writing any row.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.messaging.config import NOTIFICATIONS_EXCHANGE
from shared.messaging.outbox import enqueue_outbox_event
from shared.models.platform.notification import Notification
from shared.schemas.events import NotificationBroadcastEvent, NotificationCreatedEvent
from shared.services.realtime import DomainEvent, Resource, Scope, emit

__all__ = (
    "BROADCASTABLE_KINDS",
    "NOTIFICATION_CREATED_EVENT",
    "NOTIFICATION_GROUPS",
    "NOTIFICATION_KINDS",
    "NOTIFICATION_KIND_GROUPS",
    "SUPPORTED_LOCALES",
    "AnnouncementLocale",
    "AnnouncementPayload",
    "AnnouncementText",
    "Audience",
    "EncounterReportDisputedPayload",
    "EncounterScheduledPayload",
    "NotificationGroup",
    "RegistrationDecisionPayload",
    "TeamInviteAnsweredPayload",
    "TeamInviteReceivedPayload",
    "TeamRejectedPayload",
    "TeamRosterEventPayload",
    "TournamentPhaseOpenedPayload",
    "broadcast",
    "effective_discord_dm",
    "notify",
    "validate_notification_payload",
    "wants_discord_dm",
)

Audience = Literal["user", "workspace", "global"]

# The locales an announcement can be written in. Declared once, as the key type
# of ``AnnouncementPayload.locales``: adding a third locale here is the whole
# change, both the "which keys are accepted" and the "which are required for a
# global announcement" rules read from it.
AnnouncementLocale = Literal["ru", "en"]
SUPPORTED_LOCALES: tuple[AnnouncementLocale, ...] = get_args(AnnouncementLocale)

# The realtime event type the inbox client matches on to refetch.
NOTIFICATION_CREATED_EVENT = "notification.created"


class _Payload(BaseModel):
    """Snapshot schemas reject unknown fields on purpose.

    A producer that renames a field it passes would otherwise write a row the
    frontend renders with a hole in the sentence, and nothing would fail until
    a user looked at their inbox.
    """

    model_config = ConfigDict(extra="forbid")


class TeamInviteReceivedPayload(_Payload):
    team_id: int
    team_name: str
    tournament_id: int
    tournament_name: str
    slot_code: str
    is_substitute: bool
    invite_id: int


class TeamInviteAnsweredPayload(_Payload):
    team_id: int
    team_name: str
    #: Not rendered -- the team is pre-formation and has no page. Carried so
    #: delivery can honour the tournament's DM mute like every other kind.
    tournament_id: int
    invite_id: int
    answer: Literal["accepted", "declined"]
    responder_name: str


class RegistrationDecisionPayload(_Payload):
    """Shared by ``registration.approved`` and ``registration.rejected`` -- the
    decision is carried by the ``kind``, not by a field, so the frontend picks
    the message without branching on the payload."""

    tournament_id: int
    tournament_name: str
    registration_id: int


class EncounterReportDisputedPayload(_Payload):
    encounter_id: int
    tournament_id: int
    #: The series position the contradiction is about. A series may play one map
    #: twice, so the GAME identifies it; ``map_id``/``position`` are the labels
    #: the inbox renders.
    game_id: int
    position: int
    map_id: int


class TeamRosterEventPayload(_Payload):
    """Shared by ``team.kicked`` and ``team.disbanded`` — the kind is the verb."""

    team_id: int
    team_name: str
    tournament_id: int
    tournament_name: str


class TeamRejectedPayload(TeamRosterEventPayload):
    #: Empty when the organizer gave no written reason. The inbox still renders.
    reason: str = ""


class TournamentPhaseOpenedPayload(_Payload):
    """Shared by ``registration.opened`` and ``check_in.opened`` -- the kind is
    the phase. ``closes_at`` is the phase row's ``ends_at``; absent when the
    window has no end (or late registration lifts it)."""

    tournament_id: int
    tournament_name: str
    closes_at: datetime | None = None


class EncounterScheduledPayload(_Payload):
    encounter_id: int
    tournament_id: int
    tournament_name: str
    home_team_name: str
    away_team_name: str
    scheduled_at: datetime


class AnnouncementText(_Payload):
    title: str = Field(min_length=1, max_length=200)
    body: str | None = Field(default=None, max_length=4000)


class AnnouncementPayload(_Payload):
    """Operator-written text, one entry per locale it was written in.

    The locale rules depend on who will see the announcement, and ``audience``
    is an argument of ``notify()`` rather than a payload field, so it arrives
    through the validation context -- see ``validate_notification_payload``,
    which is the only sanctioned way to build this model. Constructing it
    directly skips the audience-dependent half of the rules.
    """

    locales: dict[AnnouncementLocale, AnnouncementText]
    default_locale: AnnouncementLocale
    href: str | None = Field(default=None, max_length=512)

    @field_validator("href")
    @classmethod
    def _href_is_safe(cls, value: str | None) -> str | None:
        """Operator text becomes an anchor target in the banner; a ``javascript:``
        or ``data:`` URL there is stored XSS against every visitor, and a
        protocol-relative ``//evil.com`` (or its ``/\\evil.com`` twin, which
        browsers normalise to the same thing) reads as a site path while landing
        on somebody else's domain -- an open redirect wearing the platform's own
        banner. A site path is a single slash followed by something that is not
        another separator.

        Whitespace is rejected outright, before that shape check, because a
        browser *deletes* tab/CR/LF from a URL before resolving it: ``/\\t/evil.com``
        would otherwise read as a one-slash site path here and navigate to
        ``//evil.com`` there. Nothing legitimate needs a raw space either -- a
        real URL carries ``%20``."""
        if value is None:
            return value
        if any(character.isspace() or ord(character) < 0x20 or ord(character) == 0x7F for character in value):
            raise ValueError("href must not contain whitespace or control characters")
        if value.startswith("https://"):
            return value
        if value.startswith("/") and value[1:2] not in ("/", "\\"):
            return value
        raise ValueError("href must be a site-relative path or an https:// URL")

    @model_validator(mode="after")
    def _locales_cover_the_audience(self, info: ValidationInfo) -> AnnouncementPayload:
        filled = set(self.locales)
        if not filled:
            raise ValueError("an announcement needs text in at least one locale")
        if self.default_locale not in filled:
            raise ValueError(f"default_locale {self.default_locale!r} has no text")
        audience = (info.context or {}).get("audience")
        if audience == "global":
            missing = [locale for locale in SUPPORTED_LOCALES if locale not in filled]
            if missing:
                raise ValueError(f"a platform-wide announcement needs every locale; missing: {', '.join(missing)}")
        return self


NOTIFICATION_KINDS: dict[str, type[BaseModel]] = {
    "team_invite.received": TeamInviteReceivedPayload,
    "team_invite.answered": TeamInviteAnsweredPayload,
    "registration.approved": RegistrationDecisionPayload,
    "registration.rejected": RegistrationDecisionPayload,
    "encounter.report_disputed": EncounterReportDisputedPayload,
    "announcement.published": AnnouncementPayload,
    "team.kicked": TeamRosterEventPayload,
    "team.disbanded": TeamRosterEventPayload,
    "team.rejected": TeamRejectedPayload,
    "registration.opened": TournamentPhaseOpenedPayload,
    "check_in.opened": TournamentPhaseOpenedPayload,
    "encounter.scheduled": EncounterScheduledPayload,
}

#: Kinds ``broadcast()`` may post to a workspace channel. Everything else is
#: either personal (a channel post would name one person's business) or an
#: announcement (operator text that already has its own banner).
BROADCASTABLE_KINDS: frozenset[str] = frozenset({"registration.opened", "check_in.opened", "encounter.scheduled"})

#: The three switches a user sees for Discord DMs. Groups rather than one
#: toggle per kind: twelve checkboxes is a settings page nobody reads.
NotificationGroup = Literal["tournament", "matches", "team"]
NOTIFICATION_GROUPS: tuple[NotificationGroup, ...] = get_args(NotificationGroup)

#: Every personal kind -> its DM group. ``registration.opened`` and
#: ``announcement.published`` are never personal, so they are absent: a kind
#: missing here is never DMed.
NOTIFICATION_KIND_GROUPS: dict[str, NotificationGroup] = {
    "check_in.opened": "tournament",
    "registration.approved": "tournament",
    "registration.rejected": "tournament",
    "encounter.scheduled": "matches",
    "encounter.report_disputed": "matches",
    "team_invite.received": "team",
    "team_invite.answered": "team",
    "team.kicked": "team",
    "team.disbanded": "team",
    "team.rejected": "team",
}


def effective_discord_dm(stored: Mapping[str, Any]) -> dict[NotificationGroup, bool]:
    """A user's DM switches with the defaults filled in (every group on).

    ``stored`` is ``notification_preference.discord_dm``: only what the user
    changed, so a group added later is on for everyone without a backfill.
    Unknown keys and non-bool values are ignored rather than trusted.
    """
    return {group: stored.get(group) is not False for group in NOTIFICATION_GROUPS}


def wants_discord_dm(stored: Mapping[str, Any], kind: str) -> bool:
    """Whether a personal row of ``kind`` should also reach the user's Discord DMs."""
    group = NOTIFICATION_KIND_GROUPS.get(kind)
    return group is not None and effective_discord_dm(stored)[group]


def validate_notification_payload(
    kind: str,
    payload: dict[str, Any],
    *,
    audience: Audience,
) -> BaseModel:
    """Parse one payload against its kind's schema, with the audience in context.

    The single place the announcement locale rules live: an RPC that validates
    an operator's draft before it is stored calls this with the audience the
    operator chose and reports the ``ValidationError`` as a 422, exactly as
    ``notify()`` does for the write itself.

    Raises ``ValueError`` for an unregistered kind and ``pydantic.ValidationError``
    for a payload the kind's schema rejects.
    """
    schema = NOTIFICATION_KINDS.get(kind)
    if schema is None:
        raise ValueError(f"unknown notification kind: {kind!r}")
    return schema.model_validate(payload, context={"audience": audience})


def _check_audience(
    audience: Audience,
    recipient_auth_user_id: int | None,
    workspace_id: int | None,
) -> None:
    """Fail the way the CHECK constraints would, but with a usable message.

    The database enforces this in both directions already; reaching it would
    surface as an ``IntegrityError`` on someone else's ``commit()``, far from
    the call that got it wrong.
    """
    if (audience == "user") != (recipient_auth_user_id is not None):
        raise ValueError("audience='user' requires a recipient_auth_user_id, and only it may have one")
    if (audience == "workspace") != (workspace_id is not None):
        raise ValueError("audience='workspace' requires a workspace_id, and only it may have one")


async def notify(
    session: AsyncSession,
    *,
    kind: str,
    payload: dict[str, Any],
    audience: Audience = "user",
    recipient_auth_user_id: int | None = None,
    workspace_id: int | None = None,
    source_workspace_id: int | None = None,
    actor_auth_user_id: int | None = None,
    published_at: datetime | None = None,
    expires_at: datetime | None = None,
    dedupe_key: str | None = None,
) -> Notification:
    """Append one notification row. ``actor_auth_user_id=None`` means a machine actor.

    Never commits -- see the module docstring for the two invariants that follow
    from it, including why this must run before the flow's own ``commit()``.

    ``recipient_auth_user_id`` must be resolved server-side from the flow's own
    domain objects, never taken from a client-supplied id: it decides who can
    read the row.

    ``source_workspace_id`` is the tenant whose activity produced the row, and is
    what lets an operator find (and retire) the notifications their own
    tournaments emitted -- ``workspace_id`` cannot serve that purpose because a
    personal row is forbidden to carry one. A workspace announcement is its own
    source, so it defaults rather than making every caller repeat the id.

    ``dedupe_key`` names "the same event" for this kind: if a row with the same
    kind, key and recipient (or workspace) already exists -- retired or not --
    it is returned and nothing is written, signalled or delivered.

    A personal row is flushed (the delivery event needs its id) and enqueues a
    ``NotificationCreatedEvent`` in the outbox, so app-service can DM it.
    Workspace and global rows stay in the app: channel posts go through
    ``broadcast()``.
    """
    validated = validate_notification_payload(kind, payload, audience=audience)
    _check_audience(audience, recipient_auth_user_id, workspace_id)

    if dedupe_key is not None:
        existing = await _find_duplicate(
            session,
            kind=kind,
            dedupe_key=dedupe_key,
            audience=audience,
            recipient_auth_user_id=recipient_auth_user_id,
            workspace_id=workspace_id,
        )
        if existing is not None:
            return existing

    row = Notification(
        audience=audience,
        recipient_auth_user_id=recipient_auth_user_id,
        workspace_id=workspace_id,
        source_workspace_id=source_workspace_id if source_workspace_id is not None else workspace_id,
        kind=kind,
        dedupe_key=dedupe_key,
        # ``mode="json"`` so a datetime in a future payload lands as a string
        # JSONB can hold; absent optionals stay out of the snapshot instead of
        # storing a null the frontend would have to skip.
        payload_json=validated.model_dump(mode="json", exclude_none=True),
        actor_auth_user_id=actor_auth_user_id,
        expires_at=expires_at,
    )
    if published_at is not None:
        # Left unset otherwise, so the column's server default stamps it.
        row.published_at = published_at
    session.add(row)

    if recipient_auth_user_id is not None:
        # Only a personal row has an inbox to signal. A workspace or global
        # announcement is read from the banner query, which has no user-scoped
        # topic and no per-recipient staleness to announce.
        await emit(
            session,
            scope=Scope.user(recipient_auth_user_id),
            invalidates=[Resource.USER_NOTIFICATIONS],
            # Non-durable and payload-free: the inbox read is the authorized
            # channel, and a reconnecting client refetches it anyway, so a
            # replay cursor for "go refetch" would buy nothing.
            data=DomainEvent(
                domain="notifications",
                event_type=NOTIFICATION_CREATED_EVENT,
                durable=False,
            ),
            actor_user_id=actor_auth_user_id,
        )
        await session.flush()
        await enqueue_outbox_event(
            session,
            NotificationCreatedEvent(notification_id=row.id),
            exchange=NOTIFICATIONS_EXCHANGE,
            routing_key="notification.created",
        )
    return row


async def _find_duplicate(
    session: AsyncSession,
    *,
    kind: str,
    dedupe_key: str,
    audience: Audience,
    recipient_auth_user_id: int | None,
    workspace_id: int | None,
) -> Notification | None:
    """The row ``notify()`` already wrote for this event and recipient, if any.

    No ``expires_at`` filter on purpose: an operator retiring the first row must
    not make the next repeat of the same event write a fresh one.
    """
    statement = select(Notification).where(
        Notification.kind == kind,
        Notification.dedupe_key == dedupe_key,
        Notification.audience == audience,
    )
    if audience == "user":
        statement = statement.where(Notification.recipient_auth_user_id == recipient_auth_user_id)
    elif audience == "workspace":
        statement = statement.where(Notification.workspace_id == workspace_id)
    return await session.scalar(statement.limit(1))


async def broadcast(
    session: AsyncSession,
    *,
    kind: str,
    payload: dict[str, Any],
    workspace_id: int,
    dedupe_key: str,
) -> None:
    """Queue one post to the workspace's notification channel. Never commits.

    Writes no notification row: whether and where it is posted is the
    workspace's delivery config, read by app-service when the event arrives.
    ``dedupe_key`` is the ledger key there, so repeating the call for the same
    event posts once.
    """
    if kind not in BROADCASTABLE_KINDS:
        raise ValueError(f"kind {kind!r} cannot be broadcast")
    validated = validate_notification_payload(kind, payload, audience="workspace")
    await enqueue_outbox_event(
        session,
        NotificationBroadcastEvent(
            workspace_id=workspace_id,
            kind=kind,
            payload=validated.model_dump(mode="json", exclude_none=True),
            dedupe_key=dedupe_key,
        ),
        exchange=NOTIFICATIONS_EXCHANGE,
        routing_key="notification.broadcast",
    )
