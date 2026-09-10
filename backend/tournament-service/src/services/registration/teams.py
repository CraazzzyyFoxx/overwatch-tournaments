"""Team registration flows: create, invite, accept, and roster edits.

See ``docs/plans/2026-08-20-team-registration.md`` §4. Three properties shape
every method here.

**One registration per player, always.** A team member's registration is an
ordinary :class:`BalancerRegistration` row with three extra columns set, so every
existing gate (self-register capability, subscription, open profile, verified
identity), every count and every reader keeps working untouched. That is why the
captain and invitee flows delegate to
:meth:`~src.services.registration.service.RegistrationService.submit_public_registration`
rather than writing rows themselves.

**The slot check and the slot write are one transaction.** Every mutating flow
takes ``SELECT … FOR UPDATE`` on the team row *before* reading occupancy, and the
write lands before that lock is released. Without it two invitees accept the last
``dps`` slot and the roster silently overflows the shape, which the export would
then materialize as an over-sized team. Each flow locks exactly one team row, so
no lock-ordering discipline is needed.

**A dead invite must say why it is dead.** §3.3's guarded ``UPDATE`` collapses
expired / revoked / already-accepted into one rowcount 0. §12.1 requires a distinct
machine code per case, so :func:`_diagnose_dead_invite` re-reads the row *for
reporting only* — after the guard has already decided, where it cannot reintroduce
the race.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core.errors import ApiExc, ApiHTTPException
from shared.domain.invite_token import generate_invite_token, hash_invite_token
from shared.domain.roster_shape import RosterShape, RosterShapeError, resolve_roster_shape
from shared.domain.team_roster import RosterMember, RosterOccupancy
from shared.repository import (
    BalancerRegistrationRepository,
    BalancerRegistrationTeamInviteRepository,
    BalancerRegistrationTeamRepository,
    TournamentRepository,
)
from shared.services.notifications import notify
from shared.services.realtime import Resource, Scope, emit
from shared.services.roster_shape_access import get_tournament_roster_slots, get_workspace_roster_slots
from src import models
from src.schemas.registration import RegistrationCreate, RegistrationRead
from src.schemas.registration_team import (
    RegistrationFreeAgentRead,
    RegistrationTeamInviteHistoryEntry,
    RegistrationTeamInviteHistoryResponse,
    RegistrationTeamInviteOffer,
    RegistrationTeamInvitePreview,
    RegistrationTeamInviteRead,
    RegistrationTeamMemberRead,
    RegistrationTeamRead,
    serialize_invite,
    serialize_registration_team,
)
from src.services.registration.service import (
    RegistrationService,
    TeamPlacement,
    registration_service,
)
from src.services.registration.team_rate_limits import (
    TEAM_INVITE_TOTAL_CAP,
    assert_accept_attempt_allowed,
    assert_invite_attempt_allowed,
)
from src.services.registration.windows import is_registration_open

__all__ = (
    "DEFAULT_INVITE_TTL",
    "TEAM_STATUSES",
    "RegistrationTeamService",
    "teams_service",
)

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
#: replacement (decision 12); a rejected registration was never on the roster.
_SLOT_RELEASING_STATUSES = frozenset({"withdrawn", "rejected"})


def _fail(status_code: int, code: str, msg: str) -> ApiHTTPException:
    """Build a rejection carrying a stable machine code.

    §12.2: these surfaces are public and Russian-first, so the frontend maps
    ``code`` to a translated string. A bare ``detail`` string would be rendered
    verbatim in English.
    """
    return ApiHTTPException(status_code=status_code, detail=[ApiExc(msg=msg, code=code)])


def _assert_mutable(team: models.BalancerRegistrationTeam) -> None:
    if team.exported_team_id is not None:
        raise _fail(409, "team_already_exported", "This team has already been exported to the tournament")
    if team.status not in _MUTABLE_TEAM_STATUSES:
        raise _fail(409, "team_not_forming", f"This team is {team.status} and can no longer be changed")


def _status_for(occupancy: RosterOccupancy) -> str:
    return TEAM_COMPLETE if occupancy.is_complete else TEAM_FORMING


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


def _owned_by(auth_user_id: int) -> sa.ColumnElement[bool]:
    """Is this registration owned by that account?

    ``workspace_member`` carries no ``auth_user_id`` — identity runs through
    ``player_id`` (``dbarch02`` dropped the direct column), so the chain is
    member -> player -> auth user. Same predicate ``get_registration`` uses;
    spelled once here so the team flows cannot drift from it.
    """
    return models.BalancerRegistration.workspace_member.has(
        models.WorkspaceMember.player.has(models.User.auth_user_id == auth_user_id)
    )


def _diagnose_dead_invite(invite: models.BalancerRegistrationTeamInvite) -> ApiHTTPException:
    """Turn a rowcount-0 guard result into a distinct machine code (§12.1).

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
    invite: models.BalancerRegistrationTeamInvite,
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
        models.BalancerRegistration.tournament_id == tournament_id,
        models.BalancerRegistration.registration_team_id.is_(None),
        models.BalancerRegistration.deleted_at.is_(None),
        models.BalancerRegistration.status.notin_(_SLOT_RELEASING_STATUSES),
    ]


class RegistrationTeamService:
    """Captain, invitee and organizer flows over ``registration_team``."""

    def __init__(
        self,
        *,
        team_repo: BalancerRegistrationTeamRepository = BalancerRegistrationTeamRepository(),
        invite_repo: BalancerRegistrationTeamInviteRepository = BalancerRegistrationTeamInviteRepository(),
        registration_repo: BalancerRegistrationRepository = BalancerRegistrationRepository(),
        tournament_repo: TournamentRepository = TournamentRepository(),
        registrations: RegistrationService = registration_service,
    ) -> None:
        self.team_repo = team_repo
        self.invite_repo = invite_repo
        self.registration_repo = registration_repo
        self.tournament_repo = tournament_repo
        self.registrations = registrations

    # ── loading ──────────────────────────────────────────────────────────────

    async def _lock_team(self, session: AsyncSession, team_id: int) -> models.BalancerRegistrationTeam:
        """Load a team holding its row lock, or reject.

        The lock is the serialization point for every roster decision below; taking it
        before reading occupancy is what stops two acceptances from overfilling one
        slot.
        """
        team = await self.team_repo.get_active_for_update(session, team_id)
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")
        return team

    async def _assert_registration_open(self, session: AsyncSession, tournament_id: int) -> models.Tournament:
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        if not is_registration_open(tournament):
            raise _fail(400, "registration_closed", "Registration is not open for this tournament")
        return tournament

    async def _resolve_shape(self, session: AsyncSession, tournament: models.Tournament) -> RosterShape:
        """The tournament's roster shape, through the same cache-backed getters the
        admin read path uses — so the roster a captain fills is the roster the export
        will check."""
        tournament_slots = await get_tournament_roster_slots(session, tournament.id)
        workspace_slots = await get_workspace_roster_slots(session, tournament.workspace_id)
        return resolve_roster_shape(tournament_slots, workspace_slots)

    async def _max_substitutes(self, session: AsyncSession, tournament_id: int) -> int:
        # Single-column scalar projection off the form, not a row fetch.
        return (
            await session.scalar(
                sa.select(models.BalancerRegistrationForm.max_substitutes).where(
                    models.BalancerRegistrationForm.tournament_id == tournament_id
                )
            )
            or 0
        )

    async def _roster_members(self, session: AsyncSession, team_id: int) -> list[models.BalancerRegistration]:
        result = await session.scalars(
            self.registration_repo.select().where(
                models.BalancerRegistration.registration_team_id == team_id,
                models.BalancerRegistration.deleted_at.is_(None),
                models.BalancerRegistration.status.notin_(_SLOT_RELEASING_STATUSES),
            )
        )
        return list(result)

    async def _pending_invites(
        self, session: AsyncSession, team_id: int
    ) -> list[models.BalancerRegistrationTeamInvite]:
        """Live invites only: an expired one reserves nothing, so its slot is
        offerable again without an explicit revoke."""
        return list(await self.invite_repo.list_pending(session, team_id, pending_state=INVITE_PENDING))

    async def _occupancy(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
        shape: RosterShape,
        *,
        max_substitutes: int,
        extra: RosterMember | None = None,
    ) -> RosterOccupancy:
        """Current slot occupancy, optionally including one not-yet-written member.

        ``extra`` is how a flow projects the roster *after* the write it is about to
        make, so the team's denormalized ``status`` can be set under the same lock
        rather than in a follow-up transaction where it could drift.
        """
        members = await self._roster_members(session, team.id)
        accepted = [
            RosterMember(slot_code=m.team_slot_code or "", is_substitute=bool(m.is_substitute))
            for m in members
            if m.team_slot_code
        ]
        if extra is not None:
            accepted.append(extra)
        invites = await self._pending_invites(session, team.id)
        return RosterOccupancy(
            shape=shape,
            accepted=tuple(accepted),
            pending=tuple(RosterMember(slot_code=i.slot_code, is_substitute=bool(i.is_substitute)) for i in invites),
            max_substitutes=max_substitutes,
        )

    # ── captain flows ────────────────────────────────────────────────────────

    async def create_team(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        auth_user: models.AuthUser,
        name: str,
        slot_code: str,
        body: RegistrationCreate,
    ) -> tuple[models.BalancerRegistrationTeam, RegistrationRead]:
        """Register a new team, with the caller as captain occupying one slot.

        The captain is a member like any other — decision 5: they take a real slot and
        their own registration goes through the same validation as a solo entrant. One
        transaction, so a team can never exist without its captain's registration.
        """
        cleaned_name = name.strip()
        if not cleaned_name:
            raise _fail(400, "team_name_required", "A team needs a name")
        if "#" in cleaned_name:
            # The materialization seam derives ``Team.name`` as everything before the
            # first "#" (the battle-tag convention the balancer/draft payloads use), so
            # a name containing one would be silently truncated on export — and the
            # exported_team_id backfill, keyed on the full name, would then miss.
            raise _fail(400, "team_name_invalid", 'A team name cannot contain "#"')

        tournament = await self._assert_registration_open(session, tournament_id)
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, tournament_id)

        team = models.BalancerRegistrationTeam(
            tournament_id=tournament_id,
            workspace_id=tournament.workspace_id,
            name=cleaned_name,
            name_normalized=cleaned_name.lower(),
            status=TEAM_FORMING,
        )
        try:
            await self.team_repo.create(session, team)
        except IntegrityError as exc:
            # The partial unique index on (tournament_id, lower(name)) — decision 10,
            # mirroring the export writer's dedup rule so a silent two-teams-into-one
            # merge is impossible.
            raise _fail(409, "team_name_taken", "A team with this name is already registered") from exc

        # An empty roster: the captain's own slot must exist in the shape, and this is
        # the check that rejects e.g. "tank" on a role-less tournament.
        occupancy = await self._occupancy(session, team, shape, max_substitutes=max_substitutes)
        _check_slot(occupancy, slot_code, is_substitute=False, offering=False)

        read = await self.registrations.submit_public_registration(
            session,
            tournament_id=tournament_id,
            auth_user=auth_user,
            body=body,
            team_placement=TeamPlacement(registration_team_id=team.id, slot_code=slot_code),
            commit=False,
        )
        team.captain_registration_id = read.id
        team.status = _status_for(
            await self._occupancy(
                session,
                team,
                shape,
                max_substitutes=max_substitutes,
            )
        )
        await emit(
            session,
            scope=Scope.tournament(tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            # ``commit=False`` moved the duplicate-registration and duplicate-name
            # races out of the submit helper's own ``try``, so they surface here.
            raise _fail(409, "already_registered", "You are already registered for this tournament") from exc
        return team, read

    async def is_team_captain(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
        auth_user_id: int,
    ) -> bool:
        """Does this account captain this team?

        A team whose ``captain_registration_id`` is NULL is structurally broken (the
        captain's registration was hard-deleted) — never true for that team.
        """
        if team.captain_registration_id is None:
            return False
        is_captain = await session.scalar(
            sa.select(models.BalancerRegistration.id).where(
                models.BalancerRegistration.id == team.captain_registration_id,
                _owned_by(auth_user_id),
            )
        )
        return is_captain is not None

    async def _assert_captain(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
        auth_user: models.AuthUser,
    ) -> None:
        """Only the captain edits a roster."""
        if team.captain_registration_id is None:
            raise _fail(409, "team_has_no_captain", "This team has no captain and must be handled by an organizer")
        if not await self.is_team_captain(session, team, auth_user.id):
            raise _fail(403, "not_captain", "Only the team captain can do this")

    async def set_team_image(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
        image_url: str | None,
    ) -> models.BalancerRegistrationTeam:
        """Set (or clear, with ``None``) a registered team's crest.

        Captain-gated rather than workspace-permission-gated — the deliberate
        difference from the materialized ``Team``'s image pair in
        ``services/admin/team.py``, which requires ``team.update`` on the workspace.
        A registration team belongs to the players who formed it, not to the
        organizer's staff: its captain is an ordinary competitor who typically holds
        no workspace membership at all, so a workspace gate would lock out exactly
        the person who owns the crest. The organizer's lever over a team's branding
        stays :meth:`reject_team`, not silent re-branding.

        Same mutability rule as every other roster edit (:func:`_assert_mutable`): an
        exported or terminal team is frozen, so its card cannot change after the
        field is set.
        """
        team = await self._lock_team(session, team_id)
        await self._assert_captain(session, team, auth_user)
        _assert_mutable(team)
        team.image_url = image_url
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
        # Scalar-only mutation; expire_on_commit=False keeps the instance renderable
        # by ``describe_team`` without a refresh round-trip.
        return team

    async def assert_captain_of_team(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> models.BalancerRegistrationTeam:
        """Captaincy alone, with no mutability rule and no row lock.

        Separate from :meth:`assert_may_edit_team` because reading is not editing: a
        captain must still be able to read the history of a team that was rejected or
        already exported, and folding ``_assert_mutable`` in would refuse exactly the
        cases someone opens the history to understand.
        """
        team = await self.team_repo.get_by(session, id=team_id, deleted_at=None)
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")
        await self._assert_captain(session, team, auth_user)
        return team

    async def assert_may_edit_team(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """The captain gate without the row lock, for callers that must refuse
        *before* doing slow external work.

        The crest upload deletes the previously stored S3 object before writing the
        new one, so a stranger who reached S3 could destroy a captain's image
        regardless of what the database later refuses. Taking :meth:`_lock_team`'s
        row lock across that network round-trip would instead pin a backend slot for
        its whole duration, so this reads without ``FOR UPDATE``.

        Advisory only: :meth:`set_team_image` re-runs both checks under the lock, and
        that is the authoritative decision.
        """
        team = await self.assert_captain_of_team(session, team_id=team_id, auth_user=auth_user)
        _assert_mutable(team)

    async def _resolve_invite_target(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        registration_id: int,
    ) -> int:
        """The account behind a targeted invite's registration.

        An invite binds to an IDENTITY, not to a registration row: the invitee may
        withdraw and resubmit before answering, and `accept_invite` attaches whatever
        live registration they have at that moment. Binding to the row would strand the
        offer on a dead one.

        Every rejection here is a distinct code because each has a different recourse:
        picked someone from another tournament (impossible from the UI, so a real bug),
        picked someone who joined a team while the dialog was open (pick again), or
        picked a row with no account behind it (an imported player who never signed in —
        only a link invite can reach them).
        """
        registration = await session.scalar(
            self.registration_repo.select()
            .where(
                models.BalancerRegistration.id == registration_id,
                models.BalancerRegistration.deleted_at.is_(None),
            )
            .options(selectinload(models.BalancerRegistration.workspace_member))
        )
        if registration is None or registration.tournament_id != tournament_id:
            # Deliberately 404 rather than 403: confirming that a registration exists
            # elsewhere would answer a question the caller has no business asking.
            raise _fail(404, "registration_not_found", "That registration is not in this tournament")
        if registration.registration_team_id is not None or registration.status in _SLOT_RELEASING_STATUSES:
            # The free-agent list is a snapshot; someone can be recruited between the
            # captain opening the picker and pressing invite.
            raise _fail(409, "player_not_free", "That player is no longer available")

        member = registration.workspace_member
        auth_user_id = (
            await session.scalar(sa.select(models.User.auth_user_id).where(models.User.id == member.player_id))
            if member is not None
            else None
        )
        if auth_user_id is None:
            raise _fail(409, "player_has_no_account", "That player has no site account; send them a link instead")
        return auth_user_id

    async def invite_member(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
        slot_code: str,
        is_substitute: bool = False,
        target_registration_id: int | None = None,
        ttl: timedelta | None = DEFAULT_INVITE_TTL,
    ) -> tuple[models.BalancerRegistrationTeamInvite, str | None]:
        """Offer one roster slot. Returns the invite and, for a link invite, the raw
        token — which is shown exactly once and never stored.

        Decision 3: two addressing modes on one entity. ``target_registration_id`` is
        an in-app offer to a free agent already in this tournament; without it the
        invite is a shareable link for someone who has no account yet.

        A targeted invite gets NO token. That is the point: nothing to paste, nothing
        to leak, nothing to forward to the wrong person. Its recipient learns of it from
        their own registration card, which is why that read had to exist before this
        mode was reachable at all.
        """
        # Metered BEFORE the row lock: a limiter behind the lock would let a flood
        # serialize on the team row and hold it, turning the throttle into a
        # lock-contention amplifier.
        team = await self.team_repo.get_by(session, id=team_id, deleted_at=None)
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")
        await assert_invite_attempt_allowed(tournament_id=team.tournament_id, auth_user_id=auth_user.id)

        team = await self._lock_team(session, team_id)
        _assert_mutable(team)
        tournament = await self._assert_registration_open(session, team.tournament_id)
        await self._assert_captain(session, team, auth_user)

        # §7 control 2: the slot reservation caps *concurrent* pending invites, but an
        # invite -> revoke -> invite loop stays inside every slot rule. This cumulative
        # ceiling counts every invite ever created for the team, so the loop ends.
        issued = await self.count_invites_against_cap(session, team)
        if issued >= TEAM_INVITE_TOTAL_CAP:
            raise _fail(
                409,
                "invite_cap_reached",
                "This team has issued too many invites; revoke an outstanding one or ask an organizer to reset the cap",
            )

        shape = await self._resolve_shape(session, tournament)
        occupancy = await self._occupancy(
            session, team, shape, max_substitutes=await self._max_substitutes(session, team.tournament_id)
        )
        # ``offering=True``: a pending invite reserves its slot, so a captain cannot
        # hold ten open offers for one place.
        _check_slot(occupancy, slot_code, is_substitute=is_substitute, offering=True)

        raw_token: str | None = None
        token_hash: str | None = None
        target_auth_user_id: int | None = None
        if target_registration_id is None:
            raw_token, token_hash = generate_invite_token()
        else:
            # Resolved INSIDE the lock, after the slot check: the freshness of "this
            # player is unattached" and "this slot is open" must be decided under the
            # same lock that the write commits under, or a concurrent acceptance can
            # invalidate one of them between check and insert.
            target_auth_user_id = await self._resolve_invite_target(
                session, tournament_id=team.tournament_id, registration_id=target_registration_id
            )

        invite = await self.invite_repo.create(
            session,
            models.BalancerRegistrationTeamInvite(
                team_id=team.id,
                slot_code=slot_code,
                is_substitute=is_substitute,
                target_auth_user_id=target_auth_user_id,
                token_sha256=token_hash,
                expires_at=datetime.now(UTC) + ttl if ttl is not None else None,
                state=INVITE_PENDING,
                invited_by=auth_user.id,
            ),
        )
        if target_auth_user_id is not None:
            # Only the targeted mode has an addressee. A link invite is a bearer
            # credential whose recipient is whoever the captain sends it to --
            # there is no account to write an inbox row for.
            await notify(
                session,
                kind="team_invite.received",
                recipient_auth_user_id=target_auth_user_id,
                source_workspace_id=team.workspace_id,
                actor_auth_user_id=auth_user.id,
                payload={
                    "team_id": team.id,
                    "team_name": team.name,
                    "tournament_id": team.tournament_id,
                    "tournament_name": tournament.name,
                    "slot_code": slot_code,
                    "is_substitute": is_substitute,
                    "invite_id": invite.id,
                },
            )
        await session.commit()
        return invite, raw_token

    async def count_invites_against_cap(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
    ) -> int:
        """How many invites count toward this team's cumulative ceiling.

        One definition, shared by the check that refuses an invite and the number the
        UI shows. Two copies would produce the worst version of this feature: a captain
        told "12 of 60 used" and refused at the same moment, with no way to tell which
        is wrong.

        Every invite ever created counts, not just live ones — that is the whole point
        of a cumulative cap, since an invite -> revoke -> invite loop stays inside every
        slot rule. ``invite_cap_reset_at`` moves the floor rather than zeroing a
        counter, so the rows behind a forgiven cap remain readable.
        """
        conditions: list[sa.ColumnElement[bool]] = [models.BalancerRegistrationTeamInvite.team_id == team.id]
        if team.invite_cap_reset_at is not None:
            conditions.append(models.BalancerRegistrationTeamInvite.invited_at > team.invite_cap_reset_at)
        return await self.invite_repo.count(session, filters=conditions)

    async def revoke_invite(
        self,
        session: AsyncSession,
        *,
        invite_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """A captain withdraws their own outstanding offer, releasing its slot."""
        invite = await self.invite_repo.get(session, invite_id)
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")
        team = await self._lock_team(session, invite.team_id)
        await self._assert_captain(session, team, auth_user)
        _withdraw_invite(invite, by=auth_user, by_organizer=False)
        await session.commit()

    async def revoke_invite_as_organizer(
        self,
        session: AsyncSession,
        *,
        invite_id: int,
        tournament_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """An organizer withdraws an offer from a team they do not captain.

        The caller owns the workspace-permission check; what this owns is the scope
        one: the invite must belong to a team in ``tournament_id``. Without that an
        organizer of any tournament could pass any invite id and act on another
        tournament's roster, because an invite id is global while their permission is
        not.

        Unlike the captain path this does NOT require the team to be mutable. A
        forming-only rule would make the power useless exactly when it is needed — the
        reason to reach in is usually that something is stuck.
        """
        invite = await self.invite_repo.get(session, invite_id)
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")
        team = await self._lock_team(session, invite.team_id)
        if team.tournament_id != tournament_id:
            # 404, not 403: confirming the invite exists elsewhere would answer a
            # question this organizer has no permission to ask.
            raise _fail(404, "invite_not_found", "Invite not found")
        _withdraw_invite(invite, by=auth_user, by_organizer=True)
        await session.commit()

    async def list_invite_history(
        self,
        session: AsyncSession,
        *,
        team_id: int,
    ) -> RegistrationTeamInviteHistoryResponse:
        """Every invite the team ever issued, newest first, plus its cap standing.

        A separate read from ``describe_team`` on purpose. That one returns only LIVE
        pending invites because occupancy depends on them reserving slots; mixing
        terminal rows in would make a declined offer hold a place. This is also why the
        section is collapsed in the UI: nothing pays for it until someone asks.

        The gap this closes: the cap counts every invite ever created, but only pending
        ones were visible. A captain cycling invite -> revoke -> invite burned the
        ceiling invisibly and hit a refusal whose cause was nowhere on screen. Worse, a
        DECLINED offer simply vanished — the slot reopened and the captain could not
        tell whether they were refused or the link merely lapsed, which are different
        situations with different next moves.
        """
        team = await self.team_repo.get(session, team_id)
        if team is None:
            raise _fail(404, "team_not_found", "Team not found")

        rows = list(await self.invite_repo.list_for_team(session, team_id))
        tags = await self._battle_tags_by_account(
            session,
            tournament_id=team.tournament_id,
            auth_user_ids={r.target_auth_user_id for r in rows if r.target_auth_user_id is not None},
        )
        now = datetime.now(UTC)
        return RegistrationTeamInviteHistoryResponse(
            items=[
                RegistrationTeamInviteHistoryEntry(
                    id=row.id,
                    slot_code=row.slot_code,
                    is_substitute=bool(row.is_substitute),
                    # `expired` is not a stored state: it is a pending row past its
                    # clock. Computed here for the same reason the link preview computes
                    # it — a lapsed offer and a live one are not the same entry, and the
                    # column cannot tell them apart.
                    state="expired"
                    if row.state == INVITE_PENDING and row.expires_at is not None and row.expires_at <= now
                    else row.state,
                    target_battle_tag=tags.get(row.target_auth_user_id),
                    is_link=row.token_sha256 is not None,
                    invited_at=row.invited_at,
                    expires_at=row.expires_at,
                    answered_at=row.accepted_at or row.revoked_at,
                    # Who ended it, when anyone did. A captain revoking their own offer
                    # and an organizer reaching into the roster are the same state and
                    # very different events.
                    revoked_by_organizer=bool(row.revoked_by_organizer),
                )
                for row in rows
            ],
            cap_used=await self.count_invites_against_cap(session, team),
            cap_limit=TEAM_INVITE_TOTAL_CAP,
            cap_reset_at=team.invite_cap_reset_at,
        )

    async def reset_invite_cap(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        tournament_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """Forgive a team's cumulative invite count so its captain can invite again.

        A watermark, not a counter reset: the cap is a COUNT over every invite ever
        created, and clearing it by deleting rows would erase the history that explains
        why the cap was hit. The rows stay; the count starts here.
        """
        team = await self._lock_team(session, team_id)
        if team.tournament_id != tournament_id:
            raise _fail(404, "team_not_found", "Team not found")
        team.invite_cap_reset_at = datetime.now(UTC)
        team.invite_cap_reset_by = auth_user.id
        await session.commit()

    # ── invitee flows ────────────────────────────────────────────────────────

    async def _resolve_invite(
        self,
        session: AsyncSession,
        *,
        auth_user: models.AuthUser,
        token: str | None,
        invite_id: int | None,
    ) -> models.BalancerRegistrationTeamInvite:
        """Find the invite being redeemed, by token or by id.

        Token lookup is by *hash*, which the partial unique index serves as a single
        indexed read — the raw value is never compared against anything stored.
        """
        if token is not None:
            invite = await self.invite_repo.get_by_token_hash(
                session, hash_invite_token(_normalize_invite_token(token))
            )
        elif invite_id is not None:
            invite = await self.invite_repo.get(session, invite_id)
        else:
            raise _fail(400, "invite_reference_required", "An invite id or token is required")
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")
        # A targeted invite is addressed to one account; a link invite is bearer.
        if invite.target_auth_user_id is not None and invite.target_auth_user_id != auth_user.id:
            raise _fail(403, "invite_not_for_you", "This invite was sent to a different account")
        return invite

    async def preview_invite(self, session: AsyncSession, *, token: str) -> RegistrationTeamInvitePreview:
        """What a link invite shows before anyone signs in.

        Deliberately anonymous: the whole point of a link invite is that it reaches
        someone with no account yet, and asking them to register before telling them
        what they are joining is the wrong order. The token itself is the credential,
        so holding it is the authorization — and this returns strictly the offer (team,
        tournament, slot), never the roster.

        Unmetered by necessity: with no actor there is nothing to key a limiter on. The
        guessing space is a 256-bit token, and flooding is the gateway's anonymous IP
        budget, not this handler's problem.

        A dead or expired invite is NOT an error here. The landing page needs to say
        *why* a link stopped working, so state travels in the payload and only a token
        matching nothing at all is a 404.
        """
        # Not ``get_by_token_hash``: this read needs the team -> tournament eager-load
        # graph for the preview payload, and that method takes no ``options``.
        invite = await session.scalar(
            self.invite_repo.select()
            # See `_normalize_invite_token`'s docstring for why stripping whitespace
            # here is safe: a real token never contains any.
            .where(
                models.BalancerRegistrationTeamInvite.token_sha256 == hash_invite_token(_normalize_invite_token(token))
            )
            .options(
                selectinload(models.BalancerRegistrationTeamInvite.team).selectinload(
                    models.BalancerRegistrationTeam.tournament
                )
            )
        )
        if invite is None:
            raise _fail(404, "invite_not_found", "Invite not found")

        team = invite.team
        # Expiry is computed here rather than client-side: the clock this compares
        # against is the one the guarded UPDATE in `accept_invite` uses, not the
        # visitor's. A link that looks live but rejects on submit is the worse bug.
        live = invite.state == INVITE_PENDING and (invite.expires_at is None or invite.expires_at > datetime.now(UTC))
        return RegistrationTeamInvitePreview(
            tournament_id=team.tournament_id,
            tournament_name=team.tournament.name,
            workspace_id=team.workspace_id,
            team_id=team.id,
            team_name=team.name,
            slot_code=invite.slot_code,
            is_substitute=invite.is_substitute,
            state=invite.state,
            expires_at=invite.expires_at,
            # A team that already exported, or was disbanded, cannot take anyone —
            # regardless of how healthy the invite row looks.
            is_redeemable=live and team.status == TEAM_FORMING and team.exported_team_id is None,
        )

    async def _notify_invite_answered(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        team_name: str,
        workspace_id: int,
        captain_registration_id: int | None,
        invite_id: int,
        answer: str,
        responder: models.AuthUser,
        responder_name: str,
    ) -> None:
        """Tell the captain how their offer was answered.

        Nobody to tell is not an error: a team whose captain registration was
        hard-deleted, or a captain who is a shadow player
        (``players.user.auth_user_id IS NULL``). The roster change itself stands,
        it just goes unannounced.

        The recipient is derived from the team's own captain row, never from
        anything the answering account supplied.
        """
        if captain_registration_id is None:
            return
        captain_auth_user_id = await session.scalar(
            sa.select(models.User.auth_user_id)
            .join(models.WorkspaceMember, models.WorkspaceMember.player_id == models.User.id)
            .join(
                models.BalancerRegistration,
                models.BalancerRegistration.workspace_member_id == models.WorkspaceMember.id,
            )
            .where(models.BalancerRegistration.id == captain_registration_id)
        )
        if captain_auth_user_id is None:
            return
        await notify(
            session,
            kind="team_invite.answered",
            recipient_auth_user_id=int(captain_auth_user_id),
            source_workspace_id=workspace_id,
            actor_auth_user_id=responder.id,
            payload={
                "team_id": team_id,
                "team_name": team_name,
                "invite_id": invite_id,
                "answer": answer,
                "responder_name": responder_name,
            },
        )

    async def accept_invite(
        self,
        session: AsyncSession,
        *,
        auth_user: models.AuthUser,
        body: RegistrationCreate,
        token: str | None = None,
        invite_id: int | None = None,
    ) -> tuple[models.BalancerRegistrationTeam, int]:
        """Redeem an invite: take the offered slot, registering if necessary.

        Returns the team and the id of the registration now holding the slot.

        Everything below happens in one transaction while holding the team's row lock,
        which is what makes the slot check binding. Ordering matters: every rejection
        that can be known up front is raised *before* the invite is consumed, so a
        failed acceptance never burns the invite.

        ``body`` is used ONLY when the redeemer has no registration yet. An existing
        one is attached to the team instead — see the comment at the write below.
        """
        # Metered before the token lookup, so a guessing flood is throttled without
        # even reaching the index. Fails OPEN: 256 bits of entropy already make
        # guessing infeasible, so this is defence in depth, not the defence.
        await assert_accept_attempt_allowed(auth_user_id=auth_user.id)

        invite = await self._resolve_invite(session, auth_user=auth_user, token=token, invite_id=invite_id)
        team = await self._lock_team(session, invite.team_id)
        _assert_mutable(team)
        tournament = await self._assert_registration_open(session, team.tournament_id)
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, team.tournament_id)

        occupancy = await self._occupancy(session, team, shape, max_substitutes=max_substitutes)
        # ``offering=False``: this invite must not block its own acceptance.
        _check_slot(occupancy, invite.slot_code, is_substitute=bool(invite.is_substitute), offering=False)

        # §3.3's guard: state and expiry are checked *in the UPDATE*, so two
        # simultaneous redemptions of one link cannot both win. ``consume_if_pending``
        # is that one conditional statement, decided by whether its RETURNING produced
        # a row — never split into a read-then-write.
        consumed = await self.invite_repo.consume_if_pending(
            session,
            invite.id,
            pending_state=INVITE_PENDING,
            accepted_state=INVITE_ACCEPTED,
            accepted_at=datetime.now(UTC),
        )
        if not consumed:
            await session.refresh(invite)
            raise _diagnose_dead_invite(invite)

        # A player who already registered solo is a FREE AGENT, not a duplicate.
        #
        # There is exactly one registration row per player per tournament (the partial
        # unique index guarantees it), so "solo registration" and "team registration"
        # are the same row in two states. Accepting an invite therefore *attaches* the
        # existing row to the team rather than creating a second one — which the index
        # would reject anyway, and which `submit_public_registration` used to turn into
        # an `already_registered` 409. That 409 left a solo registrant permanently
        # unable to join any team: withdrawal is final, so there was no way out.
        #
        # The submitted ``body`` is deliberately IGNORED on this path: the player
        # already answered the form, and the only thing the invite decides is which
        # slot they occupy. Their recorded roles and ranks stand.
        existing = await self.registrations.get_registration(session, team.tournament_id, auth_user.id)
        if existing is not None:
            if existing.status in _SLOT_RELEASING_STATUSES:
                # Withdrawn or rejected. Reviving it here would smuggle a re-entry past
                # the rule that withdrawal is final, which exists because a withdrawal
                # after check-in invalidates a composed roster.
                raise _fail(
                    409,
                    "registration_terminal",
                    "Your registration for this tournament is no longer active",
                )
            existing.registration_team_id = team.id
            existing.team_slot_code = invite.slot_code
            existing.is_substitute = bool(invite.is_substitute)
            await session.flush()
            registration_id = existing.id
            responder_name = existing.battle_tag or auth_user.username
        else:
            read = await self.registrations.submit_public_registration(
                session,
                tournament_id=team.tournament_id,
                auth_user=auth_user,
                body=body,
                team_placement=TeamPlacement(
                    registration_team_id=team.id,
                    slot_code=invite.slot_code,
                    is_substitute=bool(invite.is_substitute),
                ),
                commit=False,
            )
            registration_id = read.id
            responder_name = read.battle_tag or auth_user.username
        invite.accepted_registration_id = registration_id
        # Projected, not re-read: the new member's row is already flushed, but
        # computing the post-write status here keeps it inside the lock.
        team.status = _status_for(
            await self._occupancy(session, team, shape, max_substitutes=max_substitutes),
        )
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await self._notify_invite_answered(
            session,
            team_id=team.id,
            team_name=team.name,
            workspace_id=team.workspace_id,
            captain_registration_id=team.captain_registration_id,
            invite_id=invite.id,
            answer="accepted",
            responder=auth_user,
            responder_name=responder_name,
        )
        try:
            await session.commit()
        except IntegrityError as exc:
            raise _fail(409, "already_registered", "You are already registered for this tournament") from exc
        return team, registration_id

    async def decline_invite(
        self,
        session: AsyncSession,
        *,
        auth_user: models.AuthUser,
        token: str | None = None,
        invite_id: int | None = None,
    ) -> None:
        """Refuse an offer, releasing its reserved slot back to the captain."""
        invite = await self._resolve_invite(session, auth_user=auth_user, token=token, invite_id=invite_id)
        if invite.state != INVITE_PENDING:
            raise _diagnose_dead_invite(invite)
        invite.state = INVITE_DECLINED
        # A narrow projection of the team, not a row fetch: the snapshot needs the
        # name the captain reads, the registration that identifies them, and the
        # tenant that owns the resulting notification.
        team_row = (
            await session.execute(
                sa.select(
                    models.BalancerRegistrationTeam.name,
                    models.BalancerRegistrationTeam.captain_registration_id,
                    models.BalancerRegistrationTeam.tournament_id,
                    models.BalancerRegistrationTeam.workspace_id,
                ).where(models.BalancerRegistrationTeam.id == invite.team_id)
            )
        ).one_or_none()
        if team_row is not None:
            # The battle tag the captain picked them by, not the account handle:
            # a targeted invite was chosen off the free-agent list, which shows
            # exactly this. Accepting gets it for free off the registration it
            # just wrote; declining has to read it.
            tags = await self._battle_tags_by_account(
                session, tournament_id=team_row.tournament_id, auth_user_ids={auth_user.id}
            )
            await self._notify_invite_answered(
                session,
                team_id=invite.team_id,
                team_name=team_row.name,
                workspace_id=team_row.workspace_id,
                captain_registration_id=team_row.captain_registration_id,
                invite_id=invite.id,
                answer="declined",
                responder=auth_user,
                responder_name=tags.get(auth_user.id) or auth_user.username,
            )
        await session.commit()

    # ── roster edits ─────────────────────────────────────────────────────────

    async def _release_member(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
        registration: models.BalancerRegistration,
        shape: RosterShape,
        *,
        max_substitutes: int,
    ) -> None:
        """Detach a member from the roster and recompute the team's status.

        The registration itself is *withdrawn*, not deleted: it is a real person's
        real entry, and the admin registration table plus the audit trail both expect
        it to survive. Clearing the three team columns is what frees the slot.
        """
        registration.status = "withdrawn"
        registration.registration_team_id = None
        registration.team_slot_code = None
        registration.is_substitute = False
        await session.flush()
        team.status = _status_for(await self._occupancy(session, team, shape, max_substitutes=max_substitutes))
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )

    async def kick_member(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        registration_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """Captain removes an accepted member; the vacated slot returns to open."""
        team = await self._lock_team(session, team_id)
        _assert_mutable(team)
        tournament = await self._assert_registration_open(session, team.tournament_id)
        await self._assert_captain(session, team, auth_user)

        if registration_id == team.captain_registration_id:
            raise _fail(409, "cannot_kick_captain", "A captain cannot remove themselves; transfer or disband instead")
        registration = await self.registration_repo.get(session, registration_id)
        if registration is None or registration.registration_team_id != team.id:
            raise _fail(404, "member_not_found", "This player is not on the team")

        shape = await self._resolve_shape(session, tournament)
        await self._release_member(
            session,
            team,
            registration,
            shape,
            max_substitutes=await self._max_substitutes(session, team.tournament_id),
        )
        await session.commit()

    async def leave_team(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """A member withdraws themselves. Symmetric with :meth:`kick_member` by
        decision 12 — but a captain must transfer or disband, never silently vanish
        from a team other people have already joined."""
        team = await self._lock_team(session, team_id)
        _assert_mutable(team)
        tournament = await self._assert_registration_open(session, team.tournament_id)

        registration = await session.scalar(
            self.registration_repo.select().where(
                models.BalancerRegistration.registration_team_id == team.id,
                _owned_by(auth_user.id),
            )
        )
        if registration is None:
            raise _fail(404, "member_not_found", "You are not on this team")
        if registration.id == team.captain_registration_id:
            raise _fail(409, "captain_must_transfer", "Transfer captaincy or disband the team instead")

        shape = await self._resolve_shape(session, tournament)
        await self._release_member(
            session,
            team,
            registration,
            shape,
            max_substitutes=await self._max_substitutes(session, team.tournament_id),
        )
        await session.commit()

    async def transfer_captaincy(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        registration_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """Hand captaincy to another accepted member. Rosters are unchanged."""
        team = await self._lock_team(session, team_id)
        _assert_mutable(team)
        await self._assert_registration_open(session, team.tournament_id)
        await self._assert_captain(session, team, auth_user)

        successor = await self.registration_repo.get(session, registration_id)
        if successor is None or successor.registration_team_id != team.id:
            raise _fail(404, "member_not_found", "This player is not on the team")
        if successor.is_substitute:
            # A bench player holds no starter slot, so making them captain would leave
            # the roster with a captain outside its own shape.
            raise _fail(409, "captain_must_be_starter", "A substitute cannot captain the team")
        team.captain_registration_id = successor.id
        await session.commit()

    async def disband_team(
        self,
        session: AsyncSession,
        *,
        team_id: int,
        auth_user: models.AuthUser,
    ) -> None:
        """Captain dissolves the team.

        Members' registrations survive as withdrawn rows — decision from step 3, and
        the reason the captain FK is ``SET NULL`` rather than a cascade: a captain
        walking away must not delete other people's entries.
        """
        team = await self._lock_team(session, team_id)
        _assert_mutable(team)
        await self._assert_registration_open(session, team.tournament_id)
        await self._assert_captain(session, team, auth_user)

        # Only the STATUS changes: the team link is retained deliberately.
        #
        # Clearing it (as ``kick_member``/``leave_team`` correctly do) would leave the
        # member with a withdrawn registration and no explanation — §12.5's exact dead
        # end, since the "your team was disbanded" line on their own card is derived
        # from this FK. Keeping it costs nothing: ``_roster_members`` filters withdrawn
        # rows out, so slot accounting and the export are unaffected.
        #
        # The distinction is meaningful: kick/leave means "you are not on this team",
        # disband/reject means "this team ended".
        for registration in await self._roster_members(session, team.id):
            registration.status = "withdrawn"
        # Revokes EXPIRED pending rows too, unlike ``consume_if_pending`` — see that
        # repository method's docstring.
        await self.invite_repo.revoke_pending_for_team(
            session, team.id, pending_state=INVITE_PENDING, revoked_state=INVITE_REVOKED
        )
        team.status = TEAM_DISBANDED
        team.deleted_at = datetime.now(UTC)
        team.deleted_by = auth_user.id
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()

    # ── organizer flows ──────────────────────────────────────────────────────

    async def count_unassigned_players(self, session: AsyncSession, tournament_id: int) -> int:
        """How many free agents there are.

        These are invisible to the export: it materializes registered teams, and on a
        team-registration tournament neither the balancer nor the draft runs. So an
        approved player nobody invited silently never becomes a ``tournament.player``.
        Surfacing the count is what lets an organizer notice them BEFORE pressing
        export, which is the only moment it is still cheap to fix.
        """
        return await self.registration_repo.count(session, filters=_free_agent_clause(tournament_id))

    async def list_free_agents(self, session: AsyncSession, tournament_id: int) -> list[RegistrationFreeAgentRead]:
        """The free agents a captain may invite, newest registration last.

        This is what makes a targeted invite possible without a global account search:
        the captain picks from people who already registered for THIS tournament, so no
        new identity surface is opened. Everything returned here is already on the
        public participants list — the account requirement on the route exists because
        the only use of this list is to act on it.

        Roles ride along because the captain is filling a specific slot; a list of bare
        names would make them open every profile to find a tank.
        """
        rows = await session.scalars(
            self.registration_repo.select()
            .where(*_free_agent_clause(tournament_id))
            .options(selectinload(models.BalancerRegistration.roles))
            .order_by(models.BalancerRegistration.submitted_at.asc())
        )
        return [
            RegistrationFreeAgentRead(
                registration_id=row.id,
                battle_tag=row.battle_tag,
                # Primary first: it is the role they actually want, and the captain
                # scanning for one reads the first chip.
                roles=[entry.role for entry in sorted(row.roles, key=lambda r: not r.is_primary)],
            )
            for row in list(rows)
        ]

    async def list_teams(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        include_terminal: bool = False,
    ) -> list[tuple[models.BalancerRegistrationTeam, RosterOccupancy]]:
        """Every registered team with its live occupancy — the organizer's answer to
        "who is incomplete, and what are they missing?" (§8).

        Occupancy is recomputed rather than read off ``status``: the denormalized
        column answers "complete?" for indexed filtering, but the organizer needs the
        per-slot shortfall, which only the shape comparison produces.
        """
        tournament = await self.tournament_repo.get(session, tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, tournament_id)

        conditions = [models.BalancerRegistrationTeam.tournament_id == tournament_id]
        if not include_terminal:
            conditions.append(models.BalancerRegistrationTeam.deleted_at.is_(None))
            conditions.append(models.BalancerRegistrationTeam.status.in_(sorted(_MUTABLE_TEAM_STATUSES)))
        result = await session.scalars(
            self.team_repo.select().where(*conditions).order_by(models.BalancerRegistrationTeam.name_normalized)
        )
        return [
            (team, await self._occupancy(session, team, shape, max_substitutes=max_substitutes))
            for team in list(result)
        ]

    async def reject_team(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        team_id: int,
        auth_user: models.AuthUser,
        withdraw_members: bool = True,
    ) -> models.BalancerRegistrationTeam:
        """Organizer refuses a team — the counterpart of rejecting a registration.

        ``tournament_id`` is required and asserted, not decorative: the caller's
        permission was checked against *that* tournament's workspace, so accepting a
        ``team_id`` from any other tournament would let an organizer of one event
        reject teams in another.

        ``withdraw_members`` defaults to True because leaving the members' rows
        approved is the §12.5 dead end: a player holding a live registration for a
        tournament they cannot play in, with nothing on their card explaining why.
        Passing False keeps them in the solo pool, which is the right call when the
        team is rejected for being incomplete rather than unwelcome.
        """
        team = await self._lock_team(session, team_id)
        if team.tournament_id != tournament_id:
            # Deliberately 404, not 403: confirming the team exists elsewhere would
            # leak roster membership across workspaces.
            raise _fail(404, "team_not_found", "Team not found")
        if team.exported_team_id is not None:
            raise _fail(409, "team_already_exported", "This team has already been exported to the tournament")
        if team.status in (TEAM_REJECTED, TEAM_DISBANDED):
            raise _fail(409, "team_not_forming", f"This team is already {team.status}")

        for registration in await self._roster_members(session, team.id):
            if withdraw_members:
                registration.status = "withdrawn"
            else:
                # Returning to the solo pool DOES mean leaving the team, so here the
                # link is cleared. When members are withdrawn it is retained, so their
                # own card can say the team was rejected rather than leaving them with
                # an unexplained withdrawal (§12.5).
                registration.registration_team_id = None
                registration.team_slot_code = None
                registration.is_substitute = False
        # Revokes EXPIRED pending rows too, unlike ``consume_if_pending`` — see that
        # repository method's docstring.
        await self.invite_repo.revoke_pending_for_team(
            session, team.id, pending_state=INVITE_PENDING, revoked_state=INVITE_REVOKED
        )
        team.status = TEAM_REJECTED
        team.deleted_at = datetime.now(UTC)
        team.deleted_by = auth_user.id
        await emit(
            session,
            scope=Scope.tournament(team.tournament_id),
            invalidates=[Resource.TOURNAMENT_REGISTRATIONS],
        )
        await session.commit()
        return team

    # ── read models ──────────────────────────────────────────────────────────

    async def describe_team(
        self,
        session: AsyncSession,
        team: models.BalancerRegistrationTeam,
        *,
        include_invites: bool = False,
    ) -> RegistrationTeamRead:
        """Serialize a team with its live occupancy.

        ``include_invites`` is off by default because a public roster must not leak who
        has been asked and declined; only the captain's own view and the organizer's
        pass True.
        """
        tournament = await self.tournament_repo.get(session, team.tournament_id)
        if tournament is None:
            raise _fail(404, "tournament_not_found", "Tournament not found")
        shape = await self._resolve_shape(session, tournament)
        max_substitutes = await self._max_substitutes(session, team.tournament_id)
        occupancy = await self._occupancy(session, team, shape, max_substitutes=max_substitutes)

        members = [
            RegistrationTeamMemberRead(
                registration_id=registration.id,
                display_name=registration.display_name,
                battle_tag=registration.battle_tag,
                slot_code=registration.team_slot_code,
                is_substitute=bool(registration.is_substitute),
                is_captain=registration.id == team.captain_registration_id,
                status=registration.status,
            )
            for registration in await self._roster_members(session, team.id)
        ]
        invites: list[RegistrationTeamInviteRead] = []
        if include_invites:
            pending = await self._pending_invites(session, team.id)
            tags = await self._battle_tags_by_account(
                session,
                tournament_id=team.tournament_id,
                auth_user_ids={i.target_auth_user_id for i in pending if i.target_auth_user_id is not None},
            )
            invites = [
                serialize_invite(invite, target_battle_tag=tags.get(invite.target_auth_user_id)) for invite in pending
            ]
        return serialize_registration_team(team, occupancy, members=members, invites=invites)

    async def _battle_tags_by_account(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        auth_user_ids: set[int],
    ) -> dict[int, str]:
        """Battle tags for the accounts a team's pending invites address.

        One query for every invite on the team rather than one per invite: the
        organizer's page describes every team at once, so a per-invite lookup would be
        an N+1 that grows with the field.

        Read from the addressee's registration in THIS tournament, not from their
        profile: the battle tag they entered on the form is the one the captain picked
        them by, and a profile rename must not make a pending offer unrecognisable.
        """
        if not auth_user_ids:
            return {}
        # Analytical: a two-column projection across a member -> player join.
        rows = await session.execute(
            sa.select(models.User.auth_user_id, models.BalancerRegistration.battle_tag)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.BalancerRegistration.workspace_member_id,
            )
            .join(models.User, models.User.id == models.WorkspaceMember.player_id)
            .where(
                models.BalancerRegistration.tournament_id == tournament_id,
                models.BalancerRegistration.deleted_at.is_(None),
                models.User.auth_user_id.in_(sorted(auth_user_ids)),
            )
        )
        return dict(rows.all())

    async def list_my_invites(
        self,
        session: AsyncSession,
        *,
        tournament_id: int,
        auth_user: models.AuthUser,
    ) -> list[RegistrationTeamInviteOffer]:
        """Targeted invites addressed to the caller in this tournament.

        The whole reason targeted invites are reachable: they carry no token, so this
        read is the ONLY way their recipient can learn one exists. Without it the mode
        was strictly worse than a link — nothing to copy and nowhere to see it.

        Link invites are excluded because they have no addressee; a bearer credential
        is not "yours" until you hold it, and listing them here would hand every
        outstanding link to whoever asked.

        Expired rows are filtered rather than shown greyed out: an offer the accept
        guard would refuse is not an offer, and the recipient has no action for it.
        """
        # Analytical: joins the team to scope by tournament and forming status, which
        # no single-table invite lookup can express.
        rows = await session.scalars(
            self.invite_repo.select()
            .join(
                models.BalancerRegistrationTeam,
                models.BalancerRegistrationTeam.id == models.BalancerRegistrationTeamInvite.team_id,
            )
            .where(
                models.BalancerRegistrationTeam.tournament_id == tournament_id,
                models.BalancerRegistrationTeam.deleted_at.is_(None),
                models.BalancerRegistrationTeam.status == TEAM_FORMING,
                models.BalancerRegistrationTeamInvite.target_auth_user_id == auth_user.id,
                models.BalancerRegistrationTeamInvite.state == INVITE_PENDING,
                sa.or_(
                    models.BalancerRegistrationTeamInvite.expires_at.is_(None),
                    models.BalancerRegistrationTeamInvite.expires_at > datetime.now(UTC),
                ),
            )
            .options(selectinload(models.BalancerRegistrationTeamInvite.team))
            .order_by(models.BalancerRegistrationTeamInvite.invited_at.asc())
        )
        return [
            RegistrationTeamInviteOffer(
                invite_id=invite.id,
                team_id=invite.team_id,
                team_name=invite.team.name,
                slot_code=invite.slot_code,
                is_substitute=bool(invite.is_substitute),
                expires_at=invite.expires_at,
            )
            for invite in list(rows)
        ]


teams_service = RegistrationTeamService()
