"""Read and write models of the ``individual_swiss`` stage: the personal table, its rounds, pins and the qualification lock."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from shared.core import enums

__all__ = (
    "IndividualRoundEncounterRead",
    "IndividualRoundRead",
    "IndividualRoundSeatMemberRead",
    "IndividualRoundSeatRead",
    "PlayerStandingPinRead",
    "PlayerStandingPinWrite",
    "PlayerStandingPinsRead",
    "PlayerStandingPinsUpdate",
    "PlayerStandingRead",
    "QualificationLockRead",
)


class PlayerStandingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage_id: int
    workspace_member_id: int
    registration_id: int | None
    display_name: str
    role: str
    #: Frozen when the stage started.
    start_rank: int
    #: ``start_rank`` moved by the stage's rank deltas per result.
    rank: int
    #: 1-based inside the role; ``None`` until the standings job has ranked the table once.
    position: int | None
    points: float
    wins: int
    draws: int
    losses: int
    maps_won: float
    maps_lost: float
    #: ``maps_won - maps_lost``.
    map_diff: float
    buchholz: float
    matches_played: int
    is_qualified: bool
    is_captain: bool
    is_pinned: bool


class IndividualRoundSeatMemberRead(BaseModel):
    workspace_member_id: int
    display_name: str
    #: The player's role code in the stage's personal table.
    role: str | None
    rank: int | None
    is_captain: bool


class IndividualRoundSeatRead(BaseModel):
    participation_id: int
    slot: int
    name: str
    score: float
    #: ``None`` while the encounter has no result.
    placement: int | None
    members: list[IndividualRoundSeatMemberRead]


class IndividualRoundEncounterRead(BaseModel):
    encounter_id: int
    status: enums.EncounterStatus
    result_status: enums.EncounterResultStatus
    best_of: int
    seats: list[IndividualRoundSeatRead]


class IndividualRoundRead(BaseModel):
    round: int
    encounters: list[IndividualRoundEncounterRead]


class PlayerStandingPinWrite(BaseModel):
    workspace_member_id: int
    #: 1-based place inside the player's role.
    position: int = Field(ge=1)


class PlayerStandingPinsUpdate(BaseModel):
    """The whole set of pins of the stage; an empty list unpins everyone."""

    pins: list[PlayerStandingPinWrite]


class PlayerStandingPinRead(PlayerStandingPinWrite):
    model_config = ConfigDict(from_attributes=True)


class PlayerStandingPinsRead(BaseModel):
    pins: list[PlayerStandingPinRead]


class QualificationLockRead(BaseModel):
    qualified: list[PlayerStandingRead]
    #: The playoff captains, highest rank first.
    captains: list[PlayerStandingRead]
