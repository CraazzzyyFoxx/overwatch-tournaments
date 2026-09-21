"""What a registrant may change about their OWN registration, and when.

Three sources, resolved into one answer:

1. **The form schema decides per question.** ``FormField.editable`` is the
   organizer's switch, and it is CLOSED by default -- a question is frozen at
   submit unless somebody opened it in the builder. That is why this resolves an
   ALLOWLIST (``writable_keys``) rather than a deny list: a question this server
   does not recognise, or a schema written before the flag existed, is locked.
2. **The system floors three keys**, whatever the schema says, because changing
   them after the fact silently re-points something the organizer already acted
   on -- see :func:`_floor`.
3. **One exception goes the other way**: a question the row has never answered is
   writable regardless of the flag. Without it, adding a question to a form would
   leave every existing registrant in a ``form_version_stale`` state they cannot
   clear, which with a closed default is the normal case rather than an edge one.

Pure and session-free, for the same reason ``is_registration_open`` is: the read
path calls it per row while serializing, and the write path calls it again to
enforce. Both must get the same answer, and the read path cannot afford a query.

The ORGANIZER's edit (``lifecycle.update_registration_profile``) is never gated
by any of this.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from shared.domain.forms import FormSchema
from shared.services.registration_window import is_registration_late
from src import models
from src.services.registration._common import is_included_in_balancer
from src.services.registration.answers import answer_service
from src.services.registration.windows import is_registration_open

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


def submitted_late(
    registration: models.BalancerRegistration,
    tournament: models.Tournament,
) -> bool:
    """Whether this row was signed up AFTER the registration window's ``ends_at``.

    Recomputed from ``submitted_at`` rather than stored: the schedule and the
    timestamp are both already here, and a column would be a second copy of an
    answer that can be derived exactly.

    The same predicate the sign-up path uses, evaluated at the moment the row was
    written -- so "late" means the same thing when the flag is imposed and when
    the edit path refuses to let go of it.
    """
    if registration.submitted_at is None:
        return False
    return is_registration_late(
        tournament.status,
        tournament.phase_schedule,
        now=registration.submitted_at,
    )


def _floor(
    registration: models.BalancerRegistration,
    tournament: models.Tournament,
) -> frozenset[str]:
    """Keys the organizer cannot open, and why.

    ``battle_tag`` once the row has been reviewed: it is the row's identity
    anchor -- a partial unique index per tournament, the ``workspace_member`` →
    ``player_id`` resolution and every inherited rank layer read through it.

    ``roles`` once the row is in the balancer pool or on a registered team: the
    balancer/draft has already consumed them, and on a team the slot is the
    captain's decision, not the member's.

    ``reserve`` on a late sign-up: the flag was imposed by the schedule, so
    unticking it would be a one-click promotion into the main field.
    """
    locked: set[str] = set()
    if registration.reviewed_at is not None:
        locked.add("battle_tag")
    if is_included_in_balancer(registration) or registration.registration_team_id is not None:
        locked.add("roles")
    if submitted_late(registration, tournament):
        locked.add("reserve")
    return frozenset(locked)


def _answered_keys(registration: models.BalancerRegistration) -> frozenset[str]:
    """The questions this row has an answer for.

    ``answers_of`` covers the answer COLUMNS, the identity rows and the custom
    document, but not the two builtins with storage of their own: the BattleTag
    lives in two columns of its own and ``roles`` in a child table. Without them
    a frozen ``battle_tag`` would read as "never answered" -- and therefore
    writable -- on every registration ever made.

    ``__dict__`` for ``roles`` for the same reason the serializers use it: the
    relationship is never lazy-loadable in async code, so a caller that did not
    eager-load it has no roles to report rather than a ``MissingGreenlet``.
    """
    answered = set(answer_service.answers_of(registration))
    if registration.battle_tag:
        answered.add("battle_tag")
    if registration.__dict__.get("roles"):
        answered.add("roles")
    return frozenset(answered)


def self_edit_policy(
    registration: models.BalancerRegistration,
    tournament: models.Tournament,
    schema: FormSchema,
    *,
    now: datetime | None = None,
) -> SelfEditPolicy:
    """The registrant's own edit rights for ``registration``.

    ``schema`` is the form's CURRENT schema, never the version the row was
    submitted against: the PATCH route validates against the current version and
    refuses a stale ``form_version_id``, so permissions must come from the same
    document -- otherwise an organizer freezing a question would leave everyone
    who registered earlier still editing it under their own older version.
    """
    unanswered = frozenset(field.key for field in schema.fields()) - _answered_keys(registration)
    writable = (schema.editable_keys() | unanswered) - _floor(registration, tournament)

    if registration.deleted_at is not None or registration.status not in _EDITABLE_STATUSES:
        return SelfEditPolicy(False, "status_locked", frozenset())
    if registration.checked_in:
        # Check-in freezes the entry the organizer is about to balance.
        return SelfEditPolicy(False, "checked_in", frozenset())
    if not is_registration_open(tournament, now=now):
        return SelfEditPolicy(False, "window_closed", frozenset())
    if not writable:
        # The whole-form kill switch, for free: a form where the organizer opened
        # nothing simply has nothing to edit.
        return SelfEditPolicy(False, "nothing_editable", frozenset())
    return SelfEditPolicy(True, None, writable)
