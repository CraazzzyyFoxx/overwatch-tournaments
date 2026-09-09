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

``ponytail:`` no de-duplication in v1 -- a registration toggled
approved -> rejected -> approved notifies three times. The upgrade path is a
suppression window here in ``notify()`` (skip if the same recipient/kind/entity
was notified in the last N minutes), not a partial unique index, which would
also block the legitimate repeat ("you were invited to that team again").
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.platform.notification import Notification
from shared.services.realtime import DomainEvent, Resource, Scope, emit

__all__ = (
    "NOTIFICATION_CREATED_EVENT",
    "NOTIFICATION_KINDS",
    "SUPPORTED_LOCALES",
    "AnnouncementLocale",
    "AnnouncementPayload",
    "AnnouncementText",
    "Audience",
    "EncounterReportDisputedPayload",
    "RegistrationDecisionPayload",
    "TeamInviteAnsweredPayload",
    "TeamInviteReceivedPayload",
    "notify",
    "validate_notification_payload",
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
    map_id: int
    map_index: int


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
}


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
    """
    validated = validate_notification_payload(kind, payload, audience=audience)
    _check_audience(audience, recipient_auth_user_id, workspace_id)

    row = Notification(
        audience=audience,
        recipient_auth_user_id=recipient_auth_user_id,
        workspace_id=workspace_id,
        source_workspace_id=source_workspace_id if source_workspace_id is not None else workspace_id,
        kind=kind,
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
    return row
