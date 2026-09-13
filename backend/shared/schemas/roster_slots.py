"""The Pydantic edge of the roster shape: one field type, one read model.

``TournamentCreate``/``TournamentUpdate`` (tournament-service) and
``WorkspaceCreate``/``WorkspaceUpdate`` (app-service) all accept the same raw
slot map from the same admin form, so the normalize-or-reject step lives here
once instead of being copy-pasted per schema -- the mirroring this whole feature
exists to remove. ``RosterShapeRead`` lives here for the same reason: the admin
tournament read and the draft board both hand a resolved shape to the frontend,
and a per-service copy would be exactly the mirror this feature removes.

It cannot live in ``shared.domain.roster_shape``: that module is deliberately
Pydantic-free so the balancer and draft domain logic can import it without a
web-schema dependency. This module is the one place that bridges the two.

The bound field stores the **normalized** map, never the raw input, so the JSONB
column can never hold a zero count (which would make
``RosterShape.has_role_slots`` answer on key presence instead of real slots).
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator

from shared.domain.roster_shape import RosterShape, RosterShapeError, parse_roster_slots

__all__ = ("RosterShapeRead", "RosterSlotsField", "normalize_roster_slots")


def normalize_roster_slots(value: Any) -> Any:
    """``None`` passes through (clear the override); anything else is normalized.

    ``RosterShapeError`` already subclasses ``ValueError``, so Pydantic would
    turn it into a validation error on its own -- but it carries the
    machine-readable ``code`` in an attribute the message never mentions, and the
    frontend localizes off that code. So it is re-raised with the code prefixed
    into the message, which is what survives into the 422 body.
    """
    if value is None:
        return None
    try:
        return parse_roster_slots(value).slots
    except RosterShapeError as exc:
        raise ValueError(f"{exc.code}: {exc}") from exc


RosterSlotsField = Annotated[dict[str, int] | None, BeforeValidator(normalize_roster_slots)]


class RosterShapeRead(BaseModel):
    """A resolved roster shape. The frontend never recomputes the fallback chain."""

    slots: dict[str, int]
    team_size: int
    flex_slots: int
    has_role_slots: bool
    draft_rounds: int
    # Only a reader that inspects BOTH stored levels can name the level an
    # override lives at. The draft board resolves just the effective shape, so it
    # reports the shape without claiming a level -> None.
    #
    # Five levels because two different chains end here: a tournament resolves
    # ``tournament -> workspace -> default``, a pickup mix resolves
    # ``host -> workspace -> default`` (the host's own ``balancer.user_config``
    # row), and the account preferences endpoint -- which knows no workspace --
    # reports its own stored shape as ``user``.
    source: Literal["tournament", "host", "user", "workspace", "default"] | None = None

    @classmethod
    def from_shape(cls, shape: RosterShape, *, source: str | None = None) -> RosterShapeRead:
        """Project a domain shape, keeping every derived value on one payload.

        ``source`` names the level the value is STORED at, not what it resolved
        to: an override equal to the inherited default is still an override.
        ``shape.slots`` hands back a fresh ``dict`` (never the module-level
        ``MappingProxyType``), so the field serializes as a plain JSON object.
        """
        return cls(
            slots=shape.slots,
            team_size=shape.team_size,
            flex_slots=shape.flex_slots,
            has_role_slots=shape.has_role_slots,
            draft_rounds=shape.draft_rounds,
            source=source,  # type: ignore[arg-type]  # validated by the Literal
        )
