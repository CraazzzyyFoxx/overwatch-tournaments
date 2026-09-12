"""The caller's own mix-balancer preferences: the account-level solver knobs.

Deliberately not the full ``ConfigOverrides`` vocabulary -- only these three keys
ever reached the mix engine, so the wire names them one by one instead of
carrying an opaque blob a client could stuff a tournament-GA knob into. The read
and the write carry the same three fields: a PUT answers with exactly what the
next GET would return.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from shared.domain.roster_shape import RosterSlotCode

__all__ = (
    "UserMixPreferencesRead",
    "UserMixPreferencesUpsert",
)

_TILT_DOC = (
    "Trade-off between rank balance (0) and role comfort (1); null leaves the mix engine's own 0.5 weighting in place."
)
_WEIGHTS_DOC = (
    "Per-role importance for role-line balance, keyed by roster slot code. An omitted "
    "role weighs 1.0; null means no per-role opinion at all."
)
_VARIANTS_DOC = "How many balance options the solver keeps for the host to page through; null leaves the mix default."

#: A weight per roster slot, ``flex`` included -- the mix engine drops the slots
#: this roster does not field, so an unused code is harmless, but an unknown one
#: would silently weigh nothing and is rejected here instead.
_RoleWeights = dict[RosterSlotCode, Annotated[float, Field(ge=0.0, le=100.0)]]


class UserMixPreferencesRead(BaseModel):
    """What is stored. All three are null for an account that never saved any."""

    mix_comfort_tilt: float | None = Field(default=None, ge=0.0, le=1.0, description=_TILT_DOC)
    mix_role_weights: _RoleWeights | None = Field(default=None, description=_WEIGHTS_DOC)
    max_result_variants: int | None = Field(default=None, ge=1, le=500, description=_VARIANTS_DOC)


class UserMixPreferencesUpsert(BaseModel):
    """A full replacement: all three keys required, each nullable to unset one."""

    model_config = ConfigDict(extra="forbid")

    mix_comfort_tilt: float | None = Field(ge=0.0, le=1.0, description=_TILT_DOC)
    mix_role_weights: _RoleWeights | None = Field(description=_WEIGHTS_DOC)
    max_result_variants: int | None = Field(ge=1, le=500, description=_VARIANTS_DOC)
