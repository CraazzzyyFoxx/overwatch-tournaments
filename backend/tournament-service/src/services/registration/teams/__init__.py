"""Team registration flows: create, invite, accept, and roster edits.

Three properties shape every method in this package.

**One registration per player, always.** A team member's registration is an
ordinary :class:`Registration` row with three extra columns set, so every
existing gate (self-register capability, subscription, open profile, verified
identity), every count and every reader keeps working untouched. That is why the
captain and invitee flows delegate to
:meth:`~src.services.registration.service.RegistrationService.write_public_registration`
rather than writing rows themselves.

**The slot check and the slot write are one transaction.** Every mutating flow
takes ``SELECT … FOR UPDATE`` on the team row *before* reading occupancy, and the
write lands before that lock is released. Without it two invitees accept the last
``damage`` slot and the roster silently overflows the shape, which the export would
then materialize as an over-sized team. Most flows lock exactly one team row.
Organizer placement of a player who already sits on another team is the
exception: both teams are locked in id order so two concurrent moves cannot
deadlock.

**A dead invite must say why it is dead.** The guarded ``UPDATE`` collapses
expired / revoked / already-accepted into one rowcount 0, and each case needs a
distinct machine code, so :func:`_diagnose_dead_invite` re-reads the row *for
reporting only* — after the guard has already decided, where it cannot reintroduce
the race.

Layout: ``_shared`` holds the vocabularies and pure rules, ``_core`` the base class
(repositories, row locks, roster loading, staff gates), and one mixin per flow
family — ``captain``, ``invites``, ``invitee``, ``roster``, ``organizer``,
``reads`` — which :class:`RegistrationTeamService` assembles below.
"""

from __future__ import annotations

from src.services.registration.teams._shared import (
    DEFAULT_INVITE_TTL,
    INVITE_ACCEPTED,
    INVITE_DECLINED,
    INVITE_PENDING,
    INVITE_REVOKED,
    TEAM_COMPLETE,
    TEAM_DISBANDED,
    TEAM_FORMING,
    TEAM_REJECTED,
    TEAM_STATUSES,
)
from src.services.registration.teams.captain import CaptainMixin
from src.services.registration.teams.invitee import InviteeMixin
from src.services.registration.teams.invites import InvitesMixin
from src.services.registration.teams.organizer import OrganizerMixin
from src.services.registration.teams.reads import ReadsMixin
from src.services.registration.teams.roster import RosterMixin

__all__ = (
    "DEFAULT_INVITE_TTL",
    "TEAM_STATUSES",
    "RegistrationTeamService",
    "teams_service",
)


class RegistrationTeamService(CaptainMixin, InvitesMixin, InviteeMixin, RosterMixin, OrganizerMixin, ReadsMixin):
    """Captain, invitee and organizer flows over ``registration_team``."""


teams_service = RegistrationTeamService()
