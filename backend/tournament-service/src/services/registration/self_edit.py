"""What a registrant may change about their OWN registration, and when.

Three sources, resolved into one answer:

1. **The form schema decides per question.** ``FormField.editable`` is the
   organizer's switch, and it is CLOSED by default -- a question is frozen at
   submit unless somebody opened it in the builder. That is why this resolves an
   ALLOWLIST (``writable_keys``) rather than a deny list: a question this server
   does not recognise, or a stored schema without the flag, is locked.
2. **The system floors three keys**, whatever the schema says, because changing
   them after the fact silently re-points something the organizer already acted
   on -- see :func:`_floor`.
3. **One exception goes the other way**: a question the row has never answered is
   writable regardless of the flag. Without it, adding a question to a form would
   leave every existing registrant in a ``form_version_stale`` state they cannot
   clear, which with a closed default is the normal case rather than an edge one.

Pure and session-free: the read path calls it per row while serializing, and the write path calls it again to
enforce. Both must get the same answer, and the read path cannot afford a query, so the sign-up window verdict of
the entry's node is an argument.

The ORGANIZER's edit (``lifecycle.update_registration_profile``) is never gated
by any of this.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from shared import models
from shared.core.social import GAME_PROVIDERS
from shared.domain.forms import FormSchema, identity_key
from shared.services.registration_window import is_sign_up_late
from src.services.registration._common import is_included_in_balancer
from src.services.registration.answers import answer_service

__all__ = ("SelfEditPolicy", "self_edit_policy")

#: A row in any other status is not a work in progress: ``withdrawn`` is over,
#: ``rejected``/``banned`` must not be edited back into shape, and a custom
#: status is the organizer's own bookkeeping.
_EDITABLE_STATUSES = frozenset({"pending", "approved"})


@dataclass(frozen=True, slots=True)
class SelfEditPolicy:
    can_edit: bool
    #: Machine code for the client to translate; ``None`` while editing is open.
    reason: str | None
    writable_keys: frozenset[str]


def submitted_late(entry: models.RegistrationEntry, schedule: Sequence[models.FlowNodeSchedule]) -> bool:
    """Whether this entry was signed up AFTER its node's ``open`` window ended.

    Recomputed from ``created_at`` rather than stored: the schedule and the timestamp are both already here, and a
    column would be a second copy of an answer that can be derived. The same predicate the sign-up path uses,
    evaluated at the moment the entry was written.

    shortcut: a sign-up taken in ``check_in`` before the ``open`` row's ``ends_at`` (extended afterwards) reads as on
    time; store the flag if that ever matters.
    """
    if entry.created_at is None:
        return False
    return is_sign_up_late("open", schedule, now=entry.created_at)


def _floor(
    registration: models.Registration,
    entry: models.RegistrationEntry,
) -> frozenset[str]:
    """Keys the organizer cannot open, and why.

    The GAME identity answers (``identity_battlenet``) once the row has been
    reviewed: that handle is the row's identity anchor -- uniqueness per
    tournament, the ``workspace_member`` → ``player_id`` resolution and every
    inherited rank layer read through it.

    ``roles`` once the row is in the balancer pool or on a registered team: the
    balancer/draft has already consumed them, and on a team the slot is the
    captain's decision, not the member's.

    Nothing locks ``reserve``: it is the registrant's own availability note, not
    a slot the schedule hands out.
    """
    locked: set[str] = set()
    if entry.reviewed_at is not None:
        locked.update(identity_key(provider) for provider in GAME_PROVIDERS)
    if is_included_in_balancer(entry) or registration.registration_team_id is not None:
        locked.add("roles")
    return frozenset(locked)


def _answered_keys(registration: models.Registration, entry: models.RegistrationEntry) -> frozenset[str]:
    """The questions this row has an answer for.

    ``answers_of`` covers the answer COLUMNS, the identity rows and the custom
    document, but not ``roles``, which lives in a child table. Without it a
    frozen ``roles`` would read as "never answered" -- and therefore writable --
    on every registration ever made.

    ``__dict__`` for ``roles`` for the same reason the serializers use it: the
    relationship is never lazy-loadable in async code, so a caller that did not
    eager-load it has no roles to report rather than a ``MissingGreenlet``.
    """
    answered = set(answer_service.answers_of(registration, entry))
    if registration.__dict__.get("roles"):
        answered.add("roles")
    return frozenset(answered)


def self_edit_policy(
    registration: models.Registration,
    entry: models.RegistrationEntry,
    sign_up_open: bool,
    schema: FormSchema,
) -> SelfEditPolicy:
    """The registrant's own edit rights for ``registration``.

    ``schema`` is the form's CURRENT schema, never the version the row was
    submitted against: the PATCH route validates against the current version and
    refuses a stale ``form_version_id``, so permissions must come from the same
    document -- otherwise an organizer freezing a question would leave everyone
    who registered earlier still editing it under their own older version.
    """
    unanswered = frozenset(field.key for field in schema.fields()) - _answered_keys(registration, entry)
    writable = (schema.editable_keys() | unanswered) - _floor(registration, entry)

    if registration.deleted_at is not None or entry.deleted_at is not None or entry.status not in _EDITABLE_STATUSES:
        return SelfEditPolicy(False, "status_locked", frozenset())
    if entry.checked_in:
        # Check-in freezes the entry the organizer is about to balance.
        return SelfEditPolicy(False, "checked_in", frozenset())
    if not sign_up_open:
        return SelfEditPolicy(False, "window_closed", frozenset())
    if not writable:
        # The whole-form kill switch, for free: a form where the organizer opened
        # nothing simply has nothing to edit.
        return SelfEditPolicy(False, "nothing_editable", frozenset())
    return SelfEditPolicy(True, None, writable)
