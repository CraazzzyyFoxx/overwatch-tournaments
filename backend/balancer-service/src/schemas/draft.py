"""Pydantic DTOs for the Live Draft REST API.

Request models validate at the system boundary; read models carry the data the
public ``/board`` snapshot and admin views need. Enum-like fields use the
shared StrEnums so values are validated and serialize to their string form.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from shared.core.enums import (
    DraftAutopickStrategy,
    DraftCaptainOrder,
    DraftFormat,
    DraftPickStatus,
    DraftPlayerStatus,
    DraftPoolSource,
    DraftStatus,
)
from shared.domain.player_sub_roles import workspace_sub_role_slug
from shared.domain.roster_shape import RosterShape
from shared.schemas.base import BaseRead
from shared.schemas.identity import PlayerIdentityRead
from shared.schemas.role import RoleRef
from shared.schemas.roster_slots import RosterShapeRead
from src.domain.draft.ranks import seat_role, slot_rank

__all__ = (
    "QUEUE_MAX_PLAYERS",
    "DraftAutopickPreview",
    "DraftBoardSnapshot",
    "DraftFeasibilityResponse",
    "DraftJournalEntry",
    "DraftJournalResponse",
    "DraftPickAutopickRequest",
    "DraftPickExtendRequest",
    "DraftPickOverrideRequest",
    "DraftPickOptionRead",
    "DraftPickOptionsResponse",
    "DraftPickRead",
    "DraftPickSelectRequest",
    "DraftPlayerCustomFieldRead",
    "DraftPlayerRead",
    "DraftRoleEditRequest",
    "DraftRoleEditResponse",
    "DraftSlotDeficitRead",
    "DraftSlotRead",
    "DraftSeedRequest",
    "DraftSeedDiff",
    "DraftSeedResponse",
    "DraftSessionCreateRequest",
    "DraftSessionPatchRequest",
    "DraftSessionRead",
    "DraftSuggestion",
    "DraftSuggestionsResponse",
    "DraftTeamFitResponse",
    "DraftTeamFitScore",
    "DraftTeamQueueRequest",
    "DraftTeamQueueResponse",
    "DraftTeamRead",
)

_ReadConfig = ConfigDict(from_attributes=True)


def _within(field: str, low: int, high: int) -> AfterValidator:
    def check(value: int) -> int:
        if not low <= value <= high:
            raise ValueError(f"{field} must be between {low} and {high}")
        return value

    return AfterValidator(check)


_PickTimeSeconds = Annotated[int, _within("pick_time_seconds", 10, 600)]
_OvertimeSeconds = Annotated[int, _within("overtime_seconds", 0, 300)]


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #
class DraftSessionCreateRequest(BaseModel):
    """Everything about a new draft EXCEPT its size and its format.

    ``rounds`` is derived from the tournament's roster shape server-side and the
    format is a tournament rule (``Tournament.draft_format_json``), so the admin
    form has nothing to submit and nothing to keep in sync for either.
    """

    pool_source: DraftPoolSource = DraftPoolSource.BALANCER_BALANCE
    source_balance_id: int | None = None
    pick_time_seconds: _PickTimeSeconds = 45
    # Grace period after the main clock, before the autopick. 0 = no overtime.
    overtime_seconds: _OvertimeSeconds = 0
    autopick_strategy: DraftAutopickStrategy = DraftAutopickStrategy.BEST_FIT
    allow_admin_override: bool = True
    settings: dict[str, Any] = Field(default_factory=dict)


class DraftPoolCaptainInput(BaseModel):
    """A captain chosen from the balancer pool (by registration.registration id)."""

    registration_id: int
    name: str | None = None
    #: The role this captain is seated on; ``None`` = their lead role. Must be
    #: one they play and one the roster has a slot for (422 otherwise).
    role: RoleRef | None = None


class DraftSeedRequest(BaseModel):
    """Who captains. Everything else about a player comes from their registration.

    A draft player is a reference to a balancer registration, so there is no
    manual seat: hand-typed roles and ranks could not be resolved by the engine
    and would be a second source of truth.
    """

    source_balance_id: int | None = None
    seed: int | None = None
    # Seat order for captains (who picks first). WEAKEST_FIRST seats the lowest-
    # rated captain at position 1; snake then balances across rounds.
    captain_order: DraftCaptainOrder = DraftCaptainOrder.MANUAL
    pool_captains: list[DraftPoolCaptainInput] = Field(default_factory=list)
    preview_only: bool = False
    expected_version: int | None = None


class DraftSessionPatchRequest(BaseModel):
    pick_time_seconds: _PickTimeSeconds | None = None
    overtime_seconds: _OvertimeSeconds | None = None
    autopick_strategy: DraftAutopickStrategy | None = None
    allow_admin_override: bool | None = None
    rounds: int | None = None
    settings: dict[str, Any] | None = None


class DraftPickSelectRequest(BaseModel):
    player_id: int
    expected_version: int
    target_role: RoleRef | None = None


class DraftPickAutopickRequest(BaseModel):
    expected_version: int
    reason: Literal["expiry", "admin"] = "expiry"


class DraftPickExtendRequest(BaseModel):
    """An admin hands the on-clock captain more time.

    Additive, not absolute: the deadline moves by ``seconds``, so two admins
    pressing the button twice give twice the time instead of racing to set the
    same value. ``expected_version`` is the same optimistic token the pick
    actions use -- extending a pick that has already resolved is a conflict.
    """

    expected_version: int
    seconds: Annotated[int, _within("seconds", 5, 300)]


class DraftPickOverrideRequest(BaseModel):
    expected_version: int
    player_id: int | None = None
    draft_team_id: int | None = None
    target_role: RoleRef | None = None
    note: str | None = None


class DraftRoleEditRequest(BaseModel):
    """Give a pool player one more playable role, mid-draft.

    Writes the REGISTRATION, not a draft-local copy: the balancer is the only
    writer of roles and ranks. ``rank_value`` is required -- a role with no rank
    is not playable, so adding one without a number would change nothing.
    """

    role: RoleRef
    rank_value: int = Field(gt=0)
    reason: str
    expected_version: int
    preview_only: bool = False

    @field_validator("reason")
    @classmethod
    def _reason_not_blank(cls, value: str) -> str:
        reason = value.strip()
        if not reason:
            raise ValueError("reason must not be empty")
        return reason


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
class DraftTeamRead(BaseRead):
    model_config = _ReadConfig

    session_id: int
    captain_user_id: int | None
    captain_auth_user_id: int | None
    name: str
    draft_position: int
    exported_team_id: int | None


class DraftPlayerCustomFieldRead(BaseModel):
    """One public registration answer, ready to render.

    Carries the definition's current ``label``/``type`` alongside the value so
    the draft client renders it without knowing anything about registration
    forms. Built by ``services.draft.board.player_custom_fields``; only custom
    questions the organizer left PUBLIC ever appear here, because the board
    snapshot is public.
    """

    key: str
    label: str
    type: str
    value: Any


class DraftPlayerRead(BaseRead):
    """A seat, projected. Every role/rank field below is RESOLVED, never stored.

    Built by :meth:`from_seat` from the ``DraftPlayer`` row plus the
    ``PlayerRoster`` the engine resolved for its registration, so what the
    draft shows and what the balancer shows are the same numbers by
    construction.
    """

    model_config = _ReadConfig

    session_id: int
    #: The balancer registration this seat IS (tournament); ``None`` for a mix seat. The client uses it to link
    #: straight to the pool row an organizer must edit to change a rank.
    registration_id: int | None
    user_id: int | None
    #: The workspace member this seat is: a mix seat's anchor, a tournament seat's when its registrant has one.
    workspace_member_id: int | None
    #: The seat's primary handle for the tournament's identity provider; null when the registrant gave none.
    identity: PlayerIdentityRead | None
    #: The player's canonical ``players.user.name``: what a ``/users/<name>`` profile link is built from.
    player_name: str | None
    #: The role this player leads with, over their PLAYABLE roles. ``None`` when
    #: the balancer ranks them on no role at all -- possible mid-draft if an
    #: organizer clears their ranks. Clients must render that as "no role", not
    #: substitute a default; feasibility reports it as a shortage.
    primary_role: RoleRef | None
    is_flex: bool
    status: DraftPlayerStatus
    #: The crown: this seat is its team's current captain (the one who picks). A mix host may hand a team to a
    #: teammate mid-draft, so it can differ from the seeded seat, which keeps ``captain_role``.
    is_captain: bool
    drafted_by_team_id: int | None
    #: A captain's seat role -- the one the organizer pinned while it stays
    #: playable, else their lead role. ``None`` for everyone who is not a
    #: captain: their role on a roster is the pick's ``target_role``.
    captain_role: RoleRef | None = None
    #: Playable off-roles, priority-ordered. Empty, never null.
    secondary_roles: list[RoleRef] = Field(default_factory=list)
    #: ``{slot_code: rank}`` over playable roles. A missing key means the role is
    #: not playable -- clients render a dash there and never borrow another
    #: role's number.
    role_ranks: dict[str, int] = Field(default_factory=dict)
    #: ``{slot_code: registration|workspace|ow}`` -- which layer that rank came
    #: from, so an organizer can see why a number is what it is.
    role_sources: dict[str, str] = Field(default_factory=dict)
    #: ``{top-level code: sub-role slug}`` over playable roles that declare one.
    role_sub_roles: dict[str, str] = Field(default_factory=dict)
    #: ``{slot_code: [{entity_id, slug, image_path}]}`` -- the registrant's declared top characters per role.
    role_top_characters: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    #: The registration's ``public_notes``: captains read them in the Player
    #: Inspector. The wire name stays ``notes`` -- clients depend on it, and the
    #: organizers-only ``organizer_notes``/``admin_notes`` are deliberately NOT
    #: projected here.
    notes: str | None = None
    #: The one rank that represents this player in THIS draft: their seat role's
    #: rank under a shape with role slots (a captain's pinned role, everyone
    #: else's lead role), their best playable rank under a role-less (all-flex)
    #: one, where nobody is assigned a role. The rule lives once, in
    #: ``domain.draft.ranks.slot_rank``.
    effective_rank: int | None = None
    custom_fields: list[DraftPlayerCustomFieldRead] = Field(default_factory=list)
    version: int

    @classmethod
    def from_seat(
        cls,
        player: Any,
        roster: Any | None,
        *,
        shape: Any,
        custom_fields: list[Any],
        dimension: str,
        crowned: bool | None = None,
    ) -> DraftPlayerRead:
        """``crowned`` is the crown the board shows -- whether this seat is its team's current captain -- when the
        caller knows; ``None`` reads the seed flag. ``captain_role`` stays the seeded seat's: it has no pick."""
        from src.services.draft.board import player_custom_fields

        seat = seat_role(roster, player.captain_role)
        lead = roster.primary if roster is not None else None
        return cls(
            id=player.id,
            created_at=player.created_at,
            updated_at=player.updated_at,
            session_id=player.session_id,
            registration_id=player.registration_id,
            user_id=player.user_id,
            workspace_member_id=player.workspace_member_id,
            identity=roster.identity if roster is not None else None,
            player_name=roster.player_name if roster is not None else None,
            primary_role=RoleRef.of(dimension, lead.role, lead.subrole) if lead is not None else None,
            is_flex=bool(roster.is_full_flex) if roster is not None else False,
            status=player.status,
            is_captain=player.is_captain if crowned is None else crowned,
            drafted_by_team_id=player.drafted_by_team_id,
            captain_role=RoleRef.of(dimension, seat) if player.is_captain else None,
            secondary_roles=[
                RoleRef.of(dimension, code, roster.role_sub_roles.get(code)) for code in roster.secondary_roles
            ]
            if roster is not None
            else [],
            role_ranks=roster.role_ranks if roster is not None else {},
            role_sources=roster.role_sources if roster is not None else {},
            role_sub_roles={
                role: workspace_sub_role_slug(role, subrole) for role, subrole in roster.role_sub_roles.items()
            }
            if roster is not None
            else {},
            role_top_characters=roster.role_top_characters if roster is not None else {},
            notes=roster.public_notes if roster is not None else None,
            # The player's OWN role under role slots -- a support main is not
            # worth their damage rank on the pool card, and a captain seated on
            # support is worth their support rank. ``slot_rank`` drops the role
            # itself under a role-less shape, where the maximum is the answer.
            effective_rank=slot_rank(roster, seat, shape),
            custom_fields=player_custom_fields(roster.custom_fields if roster is not None else None, custom_fields),
            version=player.version,
        )


class DraftPickRead(BaseRead):
    model_config = _ReadConfig

    session_id: int
    overall_no: int
    round_no: int
    pick_in_round: int
    draft_team_id: int
    target_role: RoleRef | None
    target_rank_value: int | None
    status: DraftPickStatus
    picked_player_id: int | None
    picked_by_user_id: int | None
    is_autopick: bool
    is_admin_override: bool
    clock_started_at: datetime | None
    clock_expires_at: datetime | None
    # Null while the pick runs on its main clock; once set, ``clock_expires_at``
    # is the OVERTIME deadline and no further grace period is granted.
    overtime_started_at: datetime | None
    version: int

    @classmethod
    def from_pick(cls, pick: Any, *, dimension: str) -> DraftPickRead:
        return cls.model_validate(
            {
                **{name: getattr(pick, name) for name in cls.model_fields},
                "target_role": RoleRef.of(dimension, pick.target_role),
            }
        )


_DERIVED_SESSION_FIELDS = frozenset({"roster_shape", "discipline"})


class DraftSessionRead(BaseRead):
    model_config = _ReadConfig

    tournament_id: int | None
    #: The mix owning this draft and the lobby it forms teams for; both ``None`` for a tournament draft (spec §9.1).
    custom_game_id: int | None = None
    lobby_index: int | None = None
    workspace_id: int
    #: The owner's discipline (a column of the session).
    discipline: str
    status: DraftStatus
    blocked_reason: str | None
    format: DraftFormat
    rounds: int
    pick_time_seconds: int
    overtime_seconds: int
    roster_shape: RosterShapeRead
    current_pick_id: int | None
    pool_source: DraftPoolSource
    source_balance_id: int | None
    autopick_strategy: DraftAutopickStrategy
    allow_admin_override: bool
    exported_at: datetime | None
    export_status: str | None
    settings_json: dict[str, Any]
    version: int
    # None only for a transient row that has not been flushed yet; every session
    # off the wire carries the timestamp the admin draft history sorts on.
    created_at: datetime | None = None

    @classmethod
    def from_session(cls, draft_session: Any, *, shape: RosterShape, discipline: str) -> DraftSessionRead:
        """The row plus what the row does not store: the roster shape and the owner's discipline.

        Every other field maps straight off the ORM object, but the shape is
        resolved from the tournament/workspace override chain and the discipline
        belongs to the tournament, so both have to be handed in. Building the
        payload off ``model_fields`` keeps those the ONLY differences: add a
        column, and it is picked up here without an edit.
        """
        payload: dict[str, Any] = {
            name: getattr(draft_session, name) for name in cls.model_fields if name not in _DERIVED_SESSION_FIELDS
        }
        payload["roster_shape"] = RosterShapeRead.from_shape(shape)
        payload["discipline"] = discipline
        return cls.model_validate(payload)


class DraftExportResponse(DraftSessionRead):
    advisories: list[str] = Field(default_factory=list)


class DraftBoardSnapshot(BaseModel):
    """Single-shot spectator/captain bootstrap + realtime resume cursor."""

    session: DraftSessionRead
    teams: list[DraftTeamRead]
    picks: list[DraftPickRead]
    players: list[DraftPlayerRead]  # all pool players; client derives availability + rosters
    current_pick: DraftPickRead | None
    last_event_id: int | None = None


class DraftSuggestion(BaseModel):
    player_id: int
    role: RoleRef
    fit_score: float
    breakdown: dict[str, float] = Field(default_factory=dict)


class DraftSuggestionsResponse(BaseModel):
    pick_id: int
    draft_team_id: int
    suggestions: list[DraftSuggestion]


class DraftSlotRead(BaseModel):
    model_config = _ReadConfig

    team_id: int
    slot_code: str
    ordinal: int


class DraftSlotDeficitRead(BaseModel):
    model_config = _ReadConfig

    slot_code: str
    unmatched_slots: int
    eligible_players: int


class DraftFeasibilityResponse(BaseModel):
    model_config = _ReadConfig

    is_feasible: bool
    total_open_slots: int
    matched_slots: int
    unmatched_slots: list[DraftSlotRead]
    slot_deficits: list[DraftSlotDeficitRead]
    blocking_player_ids: list[int]
    reason_code: str | None = None


class DraftPickOptionRead(BaseModel):
    model_config = _ReadConfig

    player_id: int
    role: RoleRef
    is_safe: bool
    reason_code: str | None = None
    unmatched_slots: list[DraftSlotRead] = Field(default_factory=list)
    blocking_player_ids: list[int] = Field(default_factory=list)


class DraftPickOptionsResponse(BaseModel):
    pick_id: int
    pick_version: int
    draft_team_id: int
    options: list[DraftPickOptionRead]


class DraftRoleEditResponse(BaseModel):
    player_id: int
    role: RoleRef
    player_version: int
    committed: bool
    before: DraftFeasibilityResponse
    after: DraftFeasibilityResponse


class DraftSeedDiff(BaseModel):
    teams_before: int
    teams_after: int
    players_before: int
    players_after: int
    picks_before: int
    picks_after: int
    session_version_before: int
    session_version_after: int


class DraftSeedResponse(BaseModel):
    session: DraftSessionRead
    preview_only: bool
    diff: DraftSeedDiff
    feasibility: DraftFeasibilityResponse


# --------------------------------------------------------------------------- #
# Team fit, captain queue, organizer journal
# --------------------------------------------------------------------------- #
#: A captain's list is a shortlist, not a second pool: past this it stops being
#: a priority and starts being the board again.
QUEUE_MAX_PLAYERS = 60


class DraftTeamFitScore(BaseModel):
    """How well one player fits one role this team can still seat."""

    model_config = _ReadConfig

    player_id: int
    #: ``None`` under a role-less (all-flex) shape, where no seat has a role and
    #: a player therefore has exactly one entry.
    role: RoleRef | None = None
    #: 1..99, min-max normalized across THIS response; 50 when every candidate
    #: scores the same. Raw fit is an unbounded heuristic, so only the ordering
    #: within one answer means anything.
    score: int


class DraftTeamFitResponse(BaseModel):
    session_id: int
    team_id: int
    scores: list[DraftTeamFitScore] = Field(default_factory=list)


class DraftTeamQueueRequest(BaseModel):
    """The captain's autopick priority ("My list"), in their own order."""

    player_ids: list[int] = Field(default_factory=list, max_length=QUEUE_MAX_PLAYERS)


class DraftAutopickPreview(BaseModel):
    """Exactly what ``DraftSelectionService.autopick`` would take right now.

    Computed by the same call autopick makes, so a captain watching the clock
    run out is never shown a different player than the one it takes.
    """

    player_id: int
    #: ``None`` under a role-less (all-flex) shape.
    role: RoleRef | None = None
    source: Literal["queue", "fit"]


class DraftTeamQueueResponse(BaseModel):
    team_id: int
    #: Stored order, filtered to players still available.
    player_ids: list[int] = Field(default_factory=list)
    #: Non-null ONLY while this team is on the clock.
    autopick_preview: DraftAutopickPreview | None = None


class DraftJournalEntry(BaseModel):
    id: int
    created_at: datetime
    action: str
    actor_auth_user_id: int | None = None
    #: Display name of the acting account; ``None`` for the clock and every
    #: other system action.
    actor_name: str | None = None
    reason: str
    pick_no: int | None = None
    team_id: int | None = None
    player_id: int | None = None
    role: RoleRef | None = None
    seconds: int | None = None


class DraftJournalResponse(BaseModel):
    session_id: int
    entries: list[DraftJournalEntry] = Field(default_factory=list)
