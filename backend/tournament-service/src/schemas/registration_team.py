"""Read/write contracts for team registration.

The read models deliberately carry the *computed* shortfall alongside the
denormalized `status`. `status` exists for indexed filtering ("show me incomplete
teams"); the per-slot `open_slots` is what a captain and an organizer actually act
on, and it can only come from comparing the roster against the tournament's
`RosterShape`. Serving only `status` is the §12.5 dead end in read-model form: the
people in an incomplete team learn they are stuck but not what is missing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from shared.domain.roster_shape import ROSTER_SLOT_CODES, RosterSlotCode
from shared.domain.team_roster import RosterOccupancy
from src import models
from src.schemas.registration import RegistrationCreate

__all__ = (
    "RegistrationTeamAcceptRequest",
    "RegistrationTeamCreateRequest",
    "RegistrationTeamInviteCreateRequest",
    "RegistrationTeamInviteRead",
    "RegistrationTeamListResponse",
    "RegistrationTeamMemberRead",
    "RegistrationTeamRead",
)


# ── requests ─────────────────────────────────────────────────────────────────


class RegistrationTeamCreateRequest(BaseModel):
    """Create a team and register the caller as its captain, in one call.

    The captain is a member like any other (decision 5), so their own registration
    payload rides along and goes through the identical validation a solo entrant
    gets. Splitting this into "create team" then "register captain" would allow a
    captainless team to exist between the two calls.
    """

    name: str = Field(min_length=1, max_length=255)
    slot_code: RosterSlotCode
    registration: RegistrationCreate

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A team needs a name")
        return cleaned


class RegistrationTeamInviteCreateRequest(BaseModel):
    """Offer one roster slot.

    ``target_registration_id`` addresses a free agent already registered for this
    tournament; omitting it produces a shareable link for someone with no account
    yet (decision 3). Both modes are one entity, so the slot accounting cannot
    diverge between them.

    A REGISTRATION id, not an account id: the captain picks from this tournament's
    own free agents, so no global account search — and no new identity surface —
    is needed. The server resolves the account behind it and stores that, because
    identity is what an invite is bound to; a registration can be withdrawn and
    resubmitted underneath it.
    """

    slot_code: RosterSlotCode
    is_substitute: bool = False
    target_registration_id: int | None = None
    #: ``None`` means "no expiry"; the service's default is applied when the field
    #: is omitted entirely, which is why this is not simply ``int = 7``.
    ttl_days: int | None = Field(default=None, ge=1, le=90)


class RegistrationTeamAcceptRequest(BaseModel):
    """Redeem an invite by token or by id.

    Exactly one reference must be given. Accepting both would leave which one
    authorizes the acceptance ambiguous — and since a link invite is bearer while a
    targeted one is not, the ambiguity is a privilege question, not a cosmetic one.

    ``registration`` is OPTIONAL because an invitee who already has a live
    registration is a free agent *attaching*: the service reuses their existing row
    and ignores anything sent here, so demanding a payload would make them re-answer
    a form they already filled. Required-but-ignored is what it used to be, and the
    client expressed that by casting an empty object — a lie the type system had no
    way to catch.

    A genuinely new invitee who sends nothing is still rejected, by the registration
    form's own validation downstream. This default cannot create a blank row.
    """

    token: str | None = None
    invite_id: int | None = None
    registration: RegistrationCreate = Field(default_factory=RegistrationCreate)

    @model_validator(mode="after")
    def _exactly_one_reference(self) -> RegistrationTeamAcceptRequest:
        provided = [value for value in (self.token, self.invite_id) if value is not None]
        if len(provided) != 1:
            raise ValueError("Exactly one of token or invite_id is required")
        return self


class RegistrationTeamRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def _strip(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("A team needs a name")
        return cleaned


class RegistrationTeamPlaceMemberRequest(BaseModel):
    slot_code: RosterSlotCode
    is_substitute: bool = False
    swap_with_registration_id: int | None = None


class RegistrationTeamSetManagerRequest(BaseModel):
    is_manager: bool


class RegistrationTeamExtendInviteRequest(BaseModel):
    ttl_days: int | None = Field(default=None, ge=1, le=90)
    rotate_token: bool = False


class RegistrationTeamCheckInRequest(BaseModel):
    exclude_registration_ids: list[int] = Field(default_factory=list)


class RegistrationTeamRedeemSubscriptionRequest(BaseModel):
    code: str | None = None
    provider: str = "boosty"


class RegistrationTeamAdmissionRequest(BaseModel):
    admission: Literal["pending", "accepted", "waitlisted"]


class RegistrationTeamNotesRequest(BaseModel):
    notes: str | None = None


class RegistrationTeamPlaceAdminRequest(BaseModel):
    registration_id: int
    slot_code: RosterSlotCode
    is_substitute: bool = False


class RegistrationTeamRejectRequest(BaseModel):
    withdraw_members: bool = False
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def _strip_reason(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


# ── reads ────────────────────────────────────────────────────────────────────


class TeamEligibilityIssueRead(BaseModel):
    code: str
    registration_id: int | None = None
    blocking: bool = True


class RegistrationTeamMemberRead(BaseModel):
    registration_id: int
    display_name: str | None = None
    battle_tag: str | None = None
    slot_code: str | None = None
    is_substitute: bool = False
    is_captain: bool = False
    is_manager: bool = False
    checked_in: bool = False
    status: str


class RegistrationTeamInviteRead(BaseModel):
    id: int
    slot_code: str
    is_substitute: bool
    state: str
    #: Who a targeted invite was addressed to, as the captain knows them. The
    #: account id it replaced was useless to any client and was an internal
    #: identity leaking outward; a captain managing pending offers needs a name,
    #: otherwise two chips are indistinguishable and neither can be revoked on
    #: purpose. ``None`` on a link invite, which has no addressee.
    target_battle_tag: str | None = None
    #: True when the invite is a shareable link. The token itself is never
    #: serialized — it is returned once, by the create call.
    is_link: bool = False
    expires_at: datetime | None = None
    invited_at: datetime | None = None


class RegistrationTeamRead(BaseModel):
    id: int
    tournament_id: int
    name: str
    image_url: str | None = None
    status: str
    captain_registration_id: int | None = None
    exported_team_id: int | None = None
    members: list[RegistrationTeamMemberRead] = Field(default_factory=list)
    #: Outstanding offers. Only ever populated for the captain's own view and the
    #: organizer's — a public roster must not leak who has been asked.
    invites: list[RegistrationTeamInviteRead] = Field(default_factory=list)
    #: Slots with nobody accepted yet, in canonical order. Empty means complete.
    open_slots: dict[str, int] = Field(default_factory=dict)
    #: Human-readable rendering of ``open_slots`` for the captain's card.
    shortfall: str = "roster complete"
    is_complete: bool = False
    substitutes_used: int = 0
    max_substitutes: int = 0
    admission: str = "pending"
    rejection_reason: str | None = None
    organizer_notes: str | None = None
    roster_locked_at: datetime | None = None
    subscription_covered: bool = False
    subscription_expires_at: datetime | None = None
    checked_in_count: int = 0
    check_in_total: int = 0
    eligibility_issues: list[TeamEligibilityIssueRead] = Field(default_factory=list)

    @field_validator("open_slots")
    @classmethod
    def _known_codes(cls, slots: dict[str, int]) -> dict[str, int]:
        unknown = set(slots) - set(ROSTER_SLOT_CODES)
        if unknown:
            raise ValueError(f"Unknown roster slot codes: {', '.join(sorted(unknown))}")
        return slots


class RegistrationTeamListResponse(BaseModel):
    items: list[RegistrationTeamRead] = Field(default_factory=list)
    total: int = 0
    #: Live registrations on no team at all — the free agents.
    #:
    #: Carried alongside the teams because the export cannot see them: it
    #: materializes registered teams, and on a team-registration tournament
    #: neither the balancer nor the draft runs, so a player nobody invited never
    #: becomes a ``tournament.player``. An organizer needs the number before
    #: pressing export; a captain needs it to know there are people to recruit.
    unassigned_players: int = 0


class RegistrationTeamInvitePreview(BaseModel):
    """What a link invite reveals BEFORE it is redeemed.

    Deliberately minimal: the holder of a token is not yet a member, so this shows
    what they are being asked to join and nothing about who else is on the roster.
    It carries ``state`` rather than 404-ing a dead invite, so the landing page can
    say *why* a link no longer works instead of looking broken.
    """

    tournament_id: int
    tournament_name: str
    workspace_id: int
    team_id: int
    team_name: str
    slot_code: str
    is_substitute: bool
    state: str
    expires_at: datetime | None = None
    #: False when the invite is pending but past its expiry. Computed server-side
    #: because the client's clock is not the one the guarded UPDATE compares against.
    is_redeemable: bool = False


class RegistrationFreeAgentRead(BaseModel):
    """A registrant on no team, as a captain sees them in the invite picker.

    Carries the registration id rather than an account id: the client never learns
    an ``auth_user_id``, and the server resolves the identity itself. Everything
    here is already on the public participants list, so the picker opens no new
    privacy surface — which is what makes targeted invites possible without a
    global account search.
    """

    registration_id: int
    battle_tag: str
    #: Role codes, primary first. The captain is filling one slot; a list of bare
    #: names would make them open every profile to find a tank.
    roles: list[str] = Field(default_factory=list)


class RegistrationFreeAgentListResponse(BaseModel):
    items: list[RegistrationFreeAgentRead] = Field(default_factory=list)
    total: int = 0


class RegistrationTeamInviteOffer(BaseModel):
    """An invite addressed to the caller, as their own registration card shows it.

    Distinct from :class:`RegistrationTeamInvitePreview`, which answers the same
    question for a LINK held by a stranger. This one is for a targeted invite,
    which has no token at all — so this read is the only way its recipient can
    ever learn it exists.
    """

    invite_id: int
    team_id: int
    team_name: str
    slot_code: str
    is_substitute: bool
    expires_at: datetime | None = None


class RegistrationTeamInviteOfferListResponse(BaseModel):
    items: list[RegistrationTeamInviteOffer] = Field(default_factory=list)


class RegistrationTeamInviteHistoryEntry(BaseModel):
    """One invite the team ever issued, live or finished.

    Distinct from :class:`RegistrationTeamInviteRead`, which is the LIVE list that
    reserves roster slots. Terminal rows must never appear there — a declined offer
    holding a place is the bug that separation prevents.
    """

    id: int
    slot_code: str
    is_substitute: bool
    #: Includes ``expired``, which is not a stored state but a pending row past its
    #: clock. A lapsed offer and a live one are not the same entry to a reader.
    state: str
    target_battle_tag: str | None = None
    is_link: bool = False
    invited_at: datetime | None = None
    expires_at: datetime | None = None
    #: When it stopped being open, if anything closed it.
    answered_at: datetime | None = None
    #: True when staff withdrew it rather than the captain. Same state, very
    #: different event — and the reason the write path records provenance instead
    #: of the reader guessing from who happens to captain the team now.
    revoked_by_organizer: bool = False


class RegistrationTeamInviteHistoryResponse(BaseModel):
    """The history plus the cap standing it explains.

    They ship together because apart they are a riddle: the cap counts every invite
    ever issued while only pending ones were ever visible, so a captain refused at
    the ceiling had no way to see where it went.
    """

    items: list[RegistrationTeamInviteHistoryEntry] = Field(default_factory=list)
    cap_used: int = 0
    cap_limit: int = 0
    #: Set when an organizer forgave the count. The rows before it remain in
    #: ``items``; only the counter's floor moved.
    cap_reset_at: datetime | None = None


def serialize_registration_team(
    team: models.BalancerRegistrationTeam,
    occupancy: RosterOccupancy,
    *,
    members: list[RegistrationTeamMemberRead] | None = None,
    invites: list[RegistrationTeamInviteRead] | None = None,
    include_staff: bool = False,
    include_private: bool = False,
    eligibility_issues: list[TeamEligibilityIssueRead] | None = None,
    subscription_covered: bool = False,
) -> RegistrationTeamRead:
    """Map a team plus its computed occupancy into the read model.

    Only slots the roster still needs are emitted. Organizer notes never leave
    this function unless include_staff is set.
    """
    roster = members or []
    checked_in_count = sum(1 for member in roster if member.checked_in)
    return RegistrationTeamRead(
        id=team.id,
        tournament_id=team.tournament_id,
        name=team.name,
        image_url=team.image_url,
        status=team.status,
        captain_registration_id=team.captain_registration_id,
        exported_team_id=team.exported_team_id,
        members=roster,
        invites=invites or [],
        open_slots={code: count for code, count in occupancy.open_slots.items() if count > 0},
        shortfall=occupancy.describe_shortfall(),
        is_complete=occupancy.is_complete,
        substitutes_used=occupancy.accepted_substitutes,
        max_substitutes=occupancy.max_substitutes,
        admission=getattr(team, "admission", None) or "pending",
        rejection_reason=team.rejection_reason if include_private or include_staff else None,
        organizer_notes=team.organizer_notes if include_staff else None,
        roster_locked_at=getattr(team, "roster_locked_at", None),
        subscription_covered=subscription_covered,
        subscription_expires_at=getattr(team, "subscription_expires_at", None),
        checked_in_count=checked_in_count,
        check_in_total=len(roster),
        eligibility_issues=eligibility_issues or [],
    )


def serialize_invite(
    invite: models.BalancerRegistrationTeamInvite,
    *,
    target_battle_tag: str | None = None,
) -> RegistrationTeamInviteRead:
    """Serialize an outstanding offer.

    ``token_sha256`` is reduced to the boolean ``is_link``: the hash is not secret,
    but serving it would let a caller confirm a guessed token offline, and nothing
    downstream needs it.

    ``target_battle_tag`` is passed IN rather than resolved here: the addressee
    lives two joins away (member -> player -> account), and a lookup inside a
    per-invite serializer would be an N+1 across every team on the organizer's
    page. The caller batches it.
    """
    return RegistrationTeamInviteRead(
        id=invite.id,
        slot_code=invite.slot_code,
        is_substitute=bool(invite.is_substitute),
        state=invite.state,
        target_battle_tag=target_battle_tag,
        is_link=invite.token_sha256 is not None,
        expires_at=invite.expires_at,
        invited_at=invite.invited_at,
    )
