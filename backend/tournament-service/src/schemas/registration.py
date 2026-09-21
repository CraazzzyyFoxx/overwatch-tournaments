"""Pydantic schemas for tournament registration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from shared.services.subscriptions import VERIFICATION_METHODS, VerificationMethod, parse_requirement
from src.schemas.admission import AdmissionRead
from src.schemas.division_grid import DivisionGridVersionRead

# ---------------------------------------------------------------------------
# Registration form (config)
#
# What a tournament ASKS now lives in ``schemas/registration_form.py`` as one
# versioned ``FormSchema``; only the sub-role catalog entry both sides render
# stayed behind.
# ---------------------------------------------------------------------------


class SubroleOption(BaseModel):
    slug: str
    label: str


# ---------------------------------------------------------------------------
# Registration (public user-facing)
# ---------------------------------------------------------------------------


class RegistrationSubmit(BaseModel):
    """A sign-up: the version the registrant answered, and the answers.

    Flat ``{field key -> value}`` rather than a column per built-in, so adding a
    question costs an organizer a schema edit and nothing else. The server always
    validates against the form's CURRENT version and refuses a stale
    ``form_version_id`` with ``form_version_stale`` (409).
    """

    form_version_id: int
    answers: dict[str, Any] = Field(default_factory=dict)


class RegistrationUpdate(BaseModel):
    """A partial edit: only the keys present in ``answers`` are validated and written."""

    form_version_id: int
    answers: dict[str, Any] = Field(default_factory=dict)


class RegistrationRoleRead(BaseModel):
    role: str
    subrole: str | None = None
    is_primary: bool = False
    priority: int = 0
    rank_value: int | None = None
    top_heroes: list[str] = Field(default_factory=list)  # ordered hero slugs


class RegistrationTeamBrief(BaseModel):
    """The registered team a roster read carries inline.

    Deliberately not the full ``RegistrationTeamRead``: this rides in every row of
    the public participants list, so it holds only what a team column and the
    §12.5 status line need. In particular it carries **no invites** — a public
    roster must not leak who has been asked and declined.
    """

    id: int
    name: str
    status: str
    slot_code: str | None = None
    is_substitute: bool = False
    is_captain: bool = False


class RegistrationRead(BaseModel):
    id: int
    tournament_id: int
    workspace_id: int
    user_id: int | None = None
    battle_tag: str | None = None
    #: Every answer this registration carries that the READER may see: the
    #: public participants list passes the form version's ``public_keys()``, an
    #: organizer context passes nothing and gets everything. ``battle_tag`` and
    #: ``roles`` stay top-level because every surface renders them.
    answers: dict[str, Any] = Field(default_factory=dict)
    roles: list[RegistrationRoleRead] = Field(default_factory=list)
    #: The schema version these answers were validated against, and whether the
    #: form has moved on since. ``form_version_stale`` is what tells the
    #: registrant's own card to ask them to answer the new questions.
    form_version_id: int | None = None
    form_version_stale: bool = False
    status: str = "pending"
    status_meta: dict[str, Any] | None = None
    balancer_status: str = "not_in_balancer"
    balancer_status_meta: dict[str, Any] | None = None
    checked_in: bool = False
    # The single admission answer, computed server-side. Never ``None``: a
    # registration the list did not resolve carries ``AdmissionRead.unknown()``,
    # so no consumer needs a null branch -- the five client-side re-derivations
    # this replaced all grew out of per-consumer defaulting.
    admission: AdmissionRead = Field(default_factory=AdmissionRead.unknown)
    # All-profiles-open verdict when the tournament requires it:
    # True = public, False = closed, None = unknown / not required.
    profiles_open: bool | None = None
    # Subscription admission verdict when the tournament requires one.
    # ``subscription_outcome`` is the COMPOSED answer ("satisfied"/"refused"/
    # "undetermined"); only "refused" blocks, mirroring ``profiles_open is False``.
    # ``subscription_verdicts`` is per provider and drives the per-row chips —
    # under ``any`` mode one red chip next to a green one is still a pass, which is
    # why the composed outcome is sent separately rather than derived client-side.
    subscription_outcome: str | None = None
    subscription_verdicts: dict[str, Any] | None = None
    # Team registration: which registered team this player belongs to, if any.
    # Present on the PUBLIC roster because the participants table needs a team
    # column and the "Your Registration" card must be able to say "your team is
    # still incomplete" — §12.5's whole point is that the people in a stuck team
    # learn it from their own card, not from an admin-only list.
    team: RegistrationTeamBrief | None = None
    submitted_at: datetime | None = None
    reviewed_at: datetime | None = None
    #: Place in submission order and the size of that order — overall, and inside
    #: this registration's primary role. The role pair is the one that answers
    #: "am I getting in": a field fills role by role, so 2nd of 119 says little
    #: next to 42 other DPS. ``queue_role`` names the bucket the role numbers
    #: were counted in, so the client never has to re-derive it.
    #:
    #: Populated ONLY by the caller's own registration reads (``reg_pub_*_me``,
    #: submit) — the participants list would pay a count per row for a number
    #: equal to the row's own index. ``None`` on every other path.
    queue_position: int | None = None
    queue_total: int | None = None
    queue_role: str | None = None
    queue_role_position: int | None = None
    queue_role_total: int | None = None
    #: Self-service editing, answered by the server (``self_edit_policy``): the
    #: form schema decides per question, three keys are floored regardless, and
    #: the reason is a machine code the client translates
    #: (``status_locked`` / ``checked_in`` / ``window_closed`` /
    #: ``nothing_editable``). Populated ONLY by the caller's own registration
    #: reads, like ``queue_*`` above — a reader looking at somebody else's row
    #: gets ``can_edit=False``, which is the truth for them.
    #:
    #: The client MUST NOT re-derive this from ``FormField.editable``: the policy
    #: also folds in the floors and the "never answered yet" exception, and three
    #: consumers re-deriving it would grow three different answers.
    can_edit: bool = False
    edit_locked_reason: str | None = None
    edit_writable_keys: list[str] = Field(default_factory=list)


class TournamentHistoryEntry(BaseModel):
    tournament_id: int
    tournament_name: str
    role: str | None = None
    division: int | None = None
    # References a version in ``RegistrationListResponse.division_grids`` instead of
    # embedding the (large) version per entry. ``None`` when the rank/division is unknown.
    division_grid_version_id: int | None = None


class SubscriptionRedeemRequest(BaseModel):
    """Body of the challenge-code redemption endpoint.

    ``provider`` defaults to ``boosty`` because the challenge code exists
    specifically for it -- Twitch has a real API and needs no code.
    """

    code: str = Field(min_length=1, max_length=128)
    provider: str = "boosty"


class SubscriptionProviderVerdictRead(BaseModel):
    """One provider's verdict, as shown to the patron.

    Deliberately narrow: ``evidence`` may hold guild ids and role ids, so only
    ``reason`` is exposed -- the UI branches on it to pick a call to action
    ("link Discord" vs "reconnect Twitch").
    """

    state: str
    tier_rank: int | None = None
    tier_label: str | None = None
    reason: str | None = None
    # Whether pasting a code can help HERE. Not derivable from `reason`: under the
    # permissive method an unlinked patron reports `no_linked_discord_account`, and a
    # code would ALSO satisfy them — so the UI cannot infer this and would either
    # hide a working input or offer one the server is about to reject.
    code_accepted: bool = False


class SubscriptionStatusRead(BaseModel):
    """The caller's own subscription standing for one tournament.

    ``outcome`` is the COMPOSED answer over the tournament's requirement;
    ``verdicts`` is per provider so the form can render a chip per account row.
    ``required`` is false when the tournament does not gate on a subscription, in
    which case the rest is informational only.
    """

    required: bool = False
    mode: str | None = None
    outcome: str | None = None
    rule: str | None = None
    # Whether signing up is refused right now. Narrower than ``outcome == refused``:
    # a provider the patron can still satisfy with a challenge code is deferred,
    # because that field only exists at check-in. The form uses it to explain the
    # block up front instead of letting submit answer 400.
    blocks_registration: bool = False
    verdicts: dict[str, SubscriptionProviderVerdictRead] = Field(default_factory=dict)


# ── workspace subscription provider config ──────────────────────────────────
#
# Minimal surface on purpose: raw ids typed by hand. Resolving Discord role names
# through the API and offering a picker is the "more elegant" follow-up.

_SUBSCRIPTION_PROVIDERS = ("boosty", "twitch")


class RoleTierUpsert(BaseModel):
    """One ``discord role -> subscription tier`` mapping.

    ``role_id`` is a string because a Discord snowflake exceeds 2**53 and must
    never survive a float round-trip.
    """

    role_id: str = Field(min_length=1, max_length=32)
    tier_rank: int = Field(default=1, ge=1, le=100)
    tier_label: str = Field(default="", max_length=64)


class ChallengeCodeUpsert(BaseModel):
    """A challenge code, supplied either as plaintext (new) or as its digest.

    Plaintext is hashed server-side and never persisted. The digest form exists so
    the redacted read model can be sent back unchanged without double-hashing.
    """

    code: str | None = Field(default=None, min_length=1, max_length=128)
    code_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    tier_rank: int = Field(default=1, ge=1, le=100)
    tier_label: str = Field(default="", max_length=64)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _needs_one_form(self) -> ChallengeCodeUpsert:
        if not self.code and not self.code_sha256:
            raise ValueError("a code row needs either `code` or `code_sha256`")
        return self


class SubscriptionProviderConfigUpsert(BaseModel):
    """Per-workspace provider setup.

    Every field except ``provider``/``enabled`` is optional and OMITTING it keeps
    whatever is stored. That matters most for ``codes``: the admin never sees the
    existing ones (only digests are kept), so a plain save must not wipe them.
    Passing an explicit list replaces them.
    """

    provider: str
    enabled: bool = False
    role_tiers: list[RoleTierUpsert] | None = None
    broadcaster_id: str | None = Field(default=None, max_length=32)
    broadcaster_login: str | None = Field(default=None, max_length=64)
    codes: list[ChallengeCodeUpsert] | None = None
    verification_method: str | None = None

    @field_validator("provider")
    @classmethod
    def _known_provider(cls, value: str) -> str:
        if value not in _SUBSCRIPTION_PROVIDERS:
            raise ValueError(f"provider must be one of {_SUBSCRIPTION_PROVIDERS}")
        return value

    @field_validator("role_tiers")
    @classmethod
    def _unique_roles(cls, value: list[RoleTierUpsert] | None) -> list[RoleTierUpsert] | None:
        if value is None:
            return value
        seen: set[str] = set()
        for row in value:
            if row.role_id in seen:
                raise ValueError(f"duplicate role_id {row.role_id!r}")
            seen.add(row.role_id)
        return value

    @field_validator("verification_method")
    @classmethod
    def _known_method(cls, value: str | None) -> str | None:
        """Reject an unknown method on WRITE, unlike the runtime parser which widens
        it to ``any``. Asymmetric on purpose: a typo the admin can still fix must be
        an error, while a bad stored blob must never lock a tournament out.
        """
        if value is None:
            return value
        if value not in VERIFICATION_METHODS:
            raise ValueError(f"verification_method must be one of {sorted(VERIFICATION_METHODS)}")
        return value


class RoleTierRead(BaseModel):
    role_id: str
    tier_rank: int
    tier_label: str = ""


class ChallengeCodeRead(BaseModel):
    """Redacted: never carries the code or its digest.

    A digest is still brute-forcible offline, so the UI only learns that a code
    exists, at what tier, and until when.
    """

    tier_rank: int
    tier_label: str = ""
    expires_at: datetime | None = None


class SubscriptionProviderConfigRead(BaseModel):
    provider: str
    enabled: bool = False
    role_tiers: list[RoleTierRead] = Field(default_factory=list)
    broadcaster_id: str | None = None
    broadcaster_login: str | None = None
    codes: list[ChallengeCodeRead] = Field(default_factory=list)
    verification_method: str = VerificationMethod.ANY


class SubscriptionProviderConfigListResponse(BaseModel):
    configs: list[SubscriptionProviderConfigRead] = Field(default_factory=list)
    # One field for the whole response, not one per provider: the guild belongs to
    # the workspace. The admin card renders it read-only and warns when it is unset.
    discord_guild_id: str | None = None


class WorkspaceSubscriptionRequirementRead(BaseModel):
    """The rule a whole workspace enforces, shared by every tournament in it.

    ``requirement`` is the raw ``{mode, requirements: [{provider, min_tier_rank}]}``
    blob rather than a nested model on purpose: ``parse_requirement`` is the single
    authority on that shape (it clamps thresholds and keeps the strictest duplicate),
    and a second Pydantic definition of it would be a second source of truth for the
    admission rule.
    """

    requirement: dict[str, Any] = Field(default_factory=dict)
    #: How many live tournaments this rule would gate. One workspace rule now governs
    #: every tournament in the workspace, so clearing or tightening it is not a local
    #: edit -- the admin surface names the blast radius rather than leaving the organizer
    #: to guess it. Counts open, unfinished tournaments whose form has the subscription
    #: toggle on: the collector's TOURNAMENT-side predicate only. It deliberately omits
    #: the collector's inner join on the workspace rule row and its drop of empty blobs,
    #: so it reports what a rule WOULD gate rather than only what one currently does --
    #: otherwise it would read 0 for "toggles on, no rule saved yet", the very state the
    #: card exists to warn about.
    enforcing_tournaments: int = 0


class WorkspaceSubscriptionRequirementUpsert(BaseModel):
    """Replaces the rule wholesale -- a partial merge of an admission rule would be
    a silent policy change, and an empty ``requirements`` list is the way to clear it.
    """

    requirement: dict[str, Any] = Field(default_factory=dict)

    @field_validator("requirement")
    @classmethod
    def _validate_requirement(cls, value: dict[str, Any]) -> dict[str, Any]:
        """Reject a malformed requirement on SAVE, not at check-in.

        Moved here verbatim from ``RegistrationFormUpsert`` when the rule moved to the
        workspace: ``parse_requirement`` raises on an unknown ``mode`` (silently picking
        one would change the admission rule) and drops rows with no provider -- which
        would leave the organizer believing they configured a gate that does nothing, so
        an all-dropped payload is rejected too. Better a 422 on save than a surprise at
        check-in, and the read path deliberately stays fail-open for anything that got
        past here.
        """
        if not value:
            return {}
        requirement = parse_requirement(value)
        if (value.get("requirements") or []) and not requirement.requirements:
            raise ValueError("subscription requirement rows must each name a provider")
        return value


class RegistrationListRead(RegistrationRead):
    # Capped to the most recent ``HISTORY_LIMIT`` entries; ``tournament_history_count``
    # holds the true total so the UI can render an accurate count badge.
    tournament_history: list[TournamentHistoryEntry] = Field(default_factory=list)
    tournament_history_count: int = 0


class RegistrationListResponse(BaseModel):
    """Envelope for the public registration list.

    Division grid versions are deduplicated into ``division_grids`` (keyed by version
    id) so each history entry only carries a ``division_grid_version_id`` reference,
    keeping the payload small even when participants have long tournament histories.

    ``hidden`` is the organizer's ``hide_registrations``, answered by the server:
    when it is set, ``registrations`` is EMPTY and ``total``/``role_counts`` are the
    whole payload. They are filled on both paths so a consumer reads one field
    regardless, and so the number can never disagree with the rows beside it —
    ``Tournament.registrations_count`` is a separately cached read and would.
    """

    registrations: list[RegistrationListRead] = Field(default_factory=list)
    # Keyed by stringified version id to match the JSON wire format (object keys are
    # always strings); ``TournamentHistoryEntry.division_grid_version_id`` references these.
    division_grids: dict[str, DivisionGridVersionRead] = Field(default_factory=dict)
    hidden: bool = False
    #: Live registrations (``deleted_at IS NULL``) — exactly the row set the visible
    #: list would have shown, so flipping ``hidden`` never changes the number.
    total: int = 0
    #: Primary role -> count, one bucket per registration. Mirrors what the overview
    #: card used to derive client-side from the rows it can no longer see.
    role_counts: dict[str, int] = Field(default_factory=dict)
    #: How many of ``total`` declared themselves reserves (or were made one by
    #: signing up late). Deliberately an EXTRA number rather than a subtraction:
    #: ``total`` is the queue denominator (``queue_position`` counts the same
    #: rows) and ``Tournament.registrations_count`` is cached separately, so a
    #: reserve-adjusted ``total`` would disagree with both. The capacity line
    #: subtracts this client-side.
    reserve_count: int = 0
    #: Advisory capacity from the form, echoed here so a consumer that already reads
    #: this envelope needs no second request for it.
    max_participants: int | None = None


class RegistrationStatusResponse(BaseModel):
    status: str
    message: str
