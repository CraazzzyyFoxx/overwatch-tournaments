"""The caller's own pickup-mix settings: everything a host configures, once.

Deliberately not the full ``ConfigOverrides`` vocabulary -- only these keys ever
reach the mix engine, so the wire names them one by one instead of carrying an
opaque blob a client could stuff a tournament-GA knob into. The read and the
write carry the same five stored fields: a PUT answers with exactly what the
next GET would return, plus one derived, read-only ``roster_shape``.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from shared.domain.roster_shape import RosterSlotCode
from shared.schemas.roster_slots import RosterShapeRead
from src.services.balancer.config.defaults import MAX_RESULT_VARIANTS

__all__ = (
    "MAX_POINTS_PER_WIN",
    "UserMixPreferencesRead",
    "UserMixPreferencesUpsert",
)

#: Upper bound on the rank-adjustment-per-win. Generous for any plausible rank
#: scale, guards against a fat-fingered setting wrecking the host's whole rank
#: book in one recorded match.
MAX_POINTS_PER_WIN = 1000

_TILT_DOC = (
    "Trade-off between rank balance (0) and role comfort (1); null leaves the mix engine's own 0.5 weighting in place."
)
_WEIGHTS_DOC = (
    "Per-role importance for role-line balance, keyed by roster slot code. An omitted "
    "role weighs 1.0; null means no per-role opinion at all."
)
_VARIANTS_DOC = "How many balance options the solver keeps for the host to page through; null leaves the mix default."
_MASK_DOC = (
    "How many seats of each role a team gets in this account's mixes, keyed by roster slot code; "
    "null inherits the workspace default and then the built-in Overwatch 5v5 shape."
)
_POINTS_DOC = (
    "How far a decided match moves both teams' ranks in this account's own rank book. "
    "0 and null both mean recording a match adjusts nothing."
)
_SHAPE_DOC = (
    "Read-only: role_mask resolved through the fallback chain, so the client never recomputes it. "
    "source is 'user' when this account stored a mask and 'default' when it did not."
)

#: A weight per roster slot, ``flex`` included -- the mix engine drops the slots
#: this roster does not field, so an unused code is harmless, but an unknown one
#: would silently weigh nothing and is rejected here instead.
_RoleWeights = dict[RosterSlotCode, Annotated[float, Field(ge=0.0, le=100.0)]]

#: The slot map itself is validated (and normalized) by the service through
#: ``normalize_roster_slots``, the same call the deleted per-mix override used --
#: one place decides what a legal roster shape is, and its ``RosterShapeError``
#: code is what the frontend localizes off.
_RoleMask = dict[str, int] | None


class UserMixPreferencesRead(BaseModel):
    """What is stored, plus the shape it resolves to.

    All five stored fields are null for an account that never saved any;
    ``roster_shape`` is always present, since a mix always has *some* shape.
    """

    mix_comfort_tilt: float | None = Field(default=None, ge=0.0, le=1.0, description=_TILT_DOC)
    mix_role_weights: _RoleWeights | None = Field(default=None, description=_WEIGHTS_DOC)
    max_result_variants: int | None = Field(default=None, ge=1, le=MAX_RESULT_VARIANTS, description=_VARIANTS_DOC)
    role_mask: _RoleMask = Field(default=None, description=_MASK_DOC)
    points_per_win: int | None = Field(default=None, ge=0, le=MAX_POINTS_PER_WIN, description=_POINTS_DOC)
    roster_shape: RosterShapeRead = Field(description=_SHAPE_DOC)


class UserMixPreferencesUpsert(BaseModel):
    """A full replacement: all five keys required, each nullable to unset one."""

    model_config = ConfigDict(extra="forbid")

    mix_comfort_tilt: float | None = Field(ge=0.0, le=1.0, description=_TILT_DOC)
    mix_role_weights: _RoleWeights | None = Field(description=_WEIGHTS_DOC)
    max_result_variants: int | None = Field(ge=1, le=MAX_RESULT_VARIANTS, description=_VARIANTS_DOC)
    role_mask: _RoleMask = Field(description=_MASK_DOC)
    points_per_win: int | None = Field(ge=0, le=MAX_POINTS_PER_WIN, description=_POINTS_DOC)
