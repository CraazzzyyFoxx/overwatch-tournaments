"""Wire shapes for ad-hoc scrim rooms (``docs/plans/2026-08-12-scrim-rooms.md``).

The custom-pool entry deliberately mirrors ``rpc/pick_ban_admin.PickBanConfigUpsert``
field for field, minus the cascade coordinates (``stage_id``/``round``), which a
room owns rather than chooses: the organizer's config editor and the scrim room's
pool editor are the same UI, so a diverging body would fork it.
"""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from shared.core.enums import (
    FirstBanRotation,
    FirstPickRule,
    MapVetoMode,
    PickBanKind,
)

__all__ = (
    "ScrimCreateRequest",
    "ScrimPoolCopy",
    "ScrimPoolCustom",
    "ScrimPoolConfigInput",
    "ScrimPoolSlotInput",
    "ScrimRoomListRead",
    "ScrimRoomRead",
    "ScrimTeamRead",
)


class ScrimTeamRead(BaseModel):
    id: int
    name: str
    #: Whether this side has a captain yet. The away side starts unclaimed —
    #: that is what the room's share link is for.
    captain_claimed: bool


class ScrimRoomRead(BaseModel):
    id: int
    token: str
    label: str
    workspace_id: int
    #: The hidden per-workspace container, not a real tournament. Exposed because
    #: the client needs it for nothing except debugging — the room is addressed by
    #: ``token`` and the pre-game UI by ``encounter_id``.
    tournament_id: int
    stage_id: int
    encounter_id: int
    best_of: int
    #: Never null: both sides are provisioned with the room, and the encounter's
    #: team FKs cascade on delete, so neither can outlive the other.
    home_team: ScrimTeamRead
    away_team: ScrimTeamRead
    #: The viewer's own side, or null for a spectator. Never inferred client-side:
    #: authority lives in ``Team.captain_id``.
    viewer_side: Literal["home", "away"] | None
    can_claim: bool
    created_at: datetime
    #: Set when the room is closed, which frees its creator's open-room slot.
    #: Closing is not deleting — the room stays readable by its participants.
    closed_at: datetime | None


class ScrimRoomListRead(BaseModel):
    rooms: list[ScrimRoomRead]


class ScrimPoolSlotInput(BaseModel):
    """One slot of a slot-mode pool. List order IS play order — same contract as
    ``PickBanConfigSlotUpsert``."""

    candidates: list[int]
    reserve_item_id: int | None = None


class ScrimPoolConfigInput(BaseModel):
    kind: PickBanKind
    mode: MapVetoMode = MapVetoMode.POOL
    first_pick_rule: FirstPickRule = FirstPickRule.HIGHER_SEED
    first_ban_rotation: FirstBanRotation = FirstBanRotation.FIXED
    #: Ruleset v2 document (docs/plans/2026-09-28-pick-ban-constructor.md §1),
    #: validated by the same engine call the organizer's upsert runs.
    ruleset: dict[str, Any]
    item_ids: list[int] = Field(default_factory=list)
    slots: list[ScrimPoolSlotInput] = Field(default_factory=list)


class ScrimPoolCopy(BaseModel):
    """ "We play this round's maps" — clone whatever the cascade resolves there.

    ``stage_id``/``round`` may be null to copy a tournament-wide or stage-wide
    config; resolution uses the engine's own ranking
    (``pick_ban_session.resolve_config_at_level``), so what a room copies is
    exactly what an encounter at that coordinate would have played.
    """

    source: Literal["copy"]
    tournament_id: int
    stage_id: int | None = None
    round: int | None = None


class ScrimPoolCustom(BaseModel):
    """A pool authored for this room only. At most one entry per ``kind``."""

    source: Literal["custom"]
    configs: list[ScrimPoolConfigInput] = Field(min_length=1)


ScrimPoolInput = Annotated[ScrimPoolCopy | ScrimPoolCustom, Field(discriminator="source")]


class ScrimCreateRequest(BaseModel):
    workspace_id: int
    label: str = Field(min_length=1, max_length=255)
    #: Upper bound comes from ``Settings["tournament.scrim"].max_best_of``, not
    #: from here: it is an operational limit, raisable without a deploy.
    best_of: int = Field(ge=1)
    home_team_name: str = Field(min_length=1, max_length=255)
    away_team_name: str = Field(min_length=1, max_length=255)
    pool: ScrimPoolInput
