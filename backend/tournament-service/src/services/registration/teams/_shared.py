"""Team-registration vocabularies and the pure rules every flow shares: rejection
codes, mutability, slot checks and invite diagnosis.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from shared import models
from shared.core.errors import ApiExc, ApiHTTPException
from shared.domain.roster_shape import RosterShape, RosterShapeError
from shared.domain.team_roster import RosterMember, RosterOccupancy

# ── vocabularies ─────────────────────────────────────────────────────────────

TEAM_FORMING = "forming"
TEAM_COMPLETE = "complete"
TEAM_REJECTED = "rejected"
TEAM_DISBANDED = "disbanded"
TEAM_STATUSES = (TEAM_FORMING, TEAM_COMPLETE, TEAM_REJECTED, TEAM_DISBANDED)
#: Statuses whose roster may still change. ``rejected``/``disbanded`` are terminal,
#: and an exported team is frozen by ``exported_team_id`` rather than by status —
#: its shape is already baked into ``tournament.player`` rows.
_MUTABLE_TEAM_STATUSES = frozenset({TEAM_FORMING, TEAM_COMPLETE})

INVITE_PENDING = "pending"
INVITE_ACCEPTED = "accepted"
INVITE_DECLINED = "declined"
INVITE_REVOKED = "revoked"

DEFAULT_INVITE_TTL = timedelta(days=7)

#: Statuses that release a roster slot. A withdrawn member frees their slot for a
#: replacement; a rejected registration was never on the roster.
_SLOT_RELEASING_STATUSES = frozenset({"withdrawn", "rejected"})


def _fail(status_code: int, code: str, msg: str) -> ApiHTTPException:
    """Build a rejection carrying a stable machine code.

    These surfaces are public and Russian-first, so the frontend maps
    ``code`` to a translated string. A bare ``detail`` string would be rendered
    verbatim in English.
    """
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(msg=msg, code=code)])


def _assert_mutable(team: models.RegistrationTeam) -> None:
    if team.exported_team_id is not None:
        raise _fail(409, "team_already_exported", "This team has already been exported to the tournament")
    if team.status not in _MUTABLE_TEAM_STATUSES:
        raise _fail(409, "team_not_forming", f"This team is {team.status} and can no longer be changed")


def _status_for(occupancy: RosterOccupancy) -> str:
    return TEAM_COMPLETE if occupancy.is_complete else TEAM_FORMING


def _apply_occupancy_status(team: models.RegistrationTeam, occupancy: RosterOccupancy) -> None:
    """Write forming/complete from occupancy, never over a terminal status.

    Admission is a separate column. Occupancy must not clobber rejected/disbanded,
    and must not invent a status the organizer's waitlist decision sits on top of.
    """
    if team.status in _MUTABLE_TEAM_STATUSES:
        team.status = _status_for(occupancy)


def _occupancy_of(
    shape: RosterShape,
    members: Sequence[models.Registration],
    invites: Sequence[models.RegistrationTeamInvite],
    *,
    max_substitutes: int,
    extra: RosterMember | None = None,
) -> RosterOccupancy:
    """Slot occupancy from already-read members and live invites."""
    accepted = [
        RosterMember(slot_code=m.team_slot_code or "", is_substitute=bool(m.is_substitute))
        for m in members
        if m.team_slot_code
    ]
    if extra is not None:
        accepted.append(extra)
    return RosterOccupancy(
        shape=shape,
        accepted=tuple(accepted),
        pending=tuple(RosterMember(slot_code=i.slot_code, is_substitute=bool(i.is_substitute)) for i in invites),
        max_substitutes=max_substitutes,
    )


def _check_slot(occupancy: RosterOccupancy, slot_code: str, *, is_substitute: bool, offering: bool) -> None:
    """Raise the right machine code for a slot that cannot take one more body."""
    try:
        allowed = (
            occupancy.can_offer(slot_code, is_substitute=is_substitute)
            if offering
            else occupancy.can_accept(slot_code, is_substitute=is_substitute)
        )
    except RosterShapeError as exc:
        # ``slot_not_in_shape``/``roster_slots_unknown_code`` — a client asking for
        # a slot this tournament's roster does not have. A 400, not a 409: nothing
        # about the team's state would make it succeed later.
        raise _fail(400, exc.code, str(exc)) from exc
    if allowed:
        return
    if is_substitute:
        raise _fail(409, "bench_full", "This team has no substitute places left")
    raise _fail(
        409,
        "slot_taken" if not offering else "slot_already_offered",
        f"The {slot_code} slot is not available on this team",
    )


def _diagnose_dead_invite(invite: models.RegistrationTeamInvite) -> ApiHTTPException:
    """Turn a rowcount-0 guard result into a distinct machine code.

    Called only *after* the guarded ``UPDATE`` has already decided, so this read
    cannot reintroduce the race it is explaining. Four situations with four
    different recourses would otherwise collapse into one opaque failure.
    """
    if invite.state == INVITE_ACCEPTED:
        return _fail(409, "invite_already_accepted", "This invite has already been accepted")
    if invite.state == INVITE_REVOKED:
        return _fail(409, "invite_revoked", "This invite was withdrawn by the captain")
    if invite.state == INVITE_DECLINED:
        return _fail(409, "invite_declined", "This invite was already declined")
    expires_at = invite.expires_at
    if expires_at is not None and expires_at <= datetime.now(UTC):
        return _fail(409, "invite_expired", "This invite has expired — ask the captain for a new one")
    # Pending, unexpired, and still rejected by the guard: the only remaining
    # explanation is a concurrent acceptance that committed between the guard and
    # this read.
    return _fail(409, "invite_already_accepted", "This invite has already been accepted")


def _withdraw_invite(
    invite: models.RegistrationTeamInvite,
    *,
    by: models.AuthUser,
    by_organizer: bool,
) -> None:
    """The state transition both revoke paths share.

    Extracted rather than parameterised with an ``as_organizer`` AUTHORIZATION
    flag: flag-driven authorization is how a privilege check gets skipped by a
    caller who passes the wrong default. The two gates stay in the two named entry
    points; ``by_organizer`` here is provenance, recorded by the caller that knows
    it, because inferring it later is impossible once captaincy has moved.
    """
    if invite.state != INVITE_PENDING:
        raise _diagnose_dead_invite(invite)
    invite.state = INVITE_REVOKED
    invite.revoked_by = by.id
    invite.revoked_at = datetime.now(UTC)
    invite.revoked_by_organizer = by_organizer


def _normalize_invite_token(token: str) -> str:
    """Strip EVERY whitespace character, not just the ends.

    A real token is a bare base64url string — it never legitimately contains
    whitespace anywhere. A stray leading/trailing/embedded space or newline is
    always corruption picked up while the link was pasted out of the `<code>`
    block that displays it, wrapped by a text field, or forwarded through a
    chat client. Removing it can therefore only rescue a mangled presentation;
    it can never turn one valid token into another.
    """
    return "".join(token.split())


def _free_agent_clause(tournament_id: int) -> list[sa.ColumnElement[bool]]:
    """The one definition of "free agent": a live registration on no team.

    Shared by the count and the list on purpose. Two copies would drift, and the
    failure is silent and specific — an organizer reading "3 players without a
    team" above a picker offering two of them cannot tell which number is lying.

    Withdrawn and rejected rows are excluded on the same rule the roster reader
    uses: they released their slot and are not waiting for anything.
    """
    return [
        models.Registration.tournament_id == tournament_id,
        models.Registration.registration_team_id.is_(None),
        models.Registration.deleted_at.is_(None),
        models.Registration.status.notin_(_SLOT_RELEASING_STATUSES),
    ]


def _assert_unlocked(team: models.RegistrationTeam) -> None:
    if team.roster_locked_at is not None:
        raise _fail(409, "roster_locked", "This team's roster is locked")
