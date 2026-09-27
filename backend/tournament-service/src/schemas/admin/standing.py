from pydantic import BaseModel, Field, model_validator

__all__ = ("StandingUpdate", "StandingPinInput", "StandingPinsUpdate")


class StandingUpdate(BaseModel):
    """Schema for updating a standing"""

    position: int | None = None
    overall_position: int | None = None
    matches: int | None = None
    win: int | None = None
    draw: int | None = None
    lose: int | None = None
    points: float | None = None
    buchholz: float | None = None
    tb: int | None = None


class StandingPinInput(BaseModel):
    team_id: int
    #: 1-based place in the table, counted like ``Standing.position``.
    position: int = Field(ge=1)


class StandingPinsUpdate(BaseModel):
    """Every pin one standings table should have, replacing what it had.

    The table is the stage from the path plus ``stage_item_id`` (its group; NULL
    for an elimination stage, whose table spans the whole stage). An empty
    ``pins`` list unpins the whole table.
    """

    stage_item_id: int | None = None
    pins: list[StandingPinInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def _distinct(self) -> StandingPinsUpdate:
        teams = [pin.team_id for pin in self.pins]
        if len(set(teams)) != len(teams):
            raise ValueError("a team can be pinned only once")
        positions = [pin.position for pin in self.pins]
        if len(set(positions)) != len(positions):
            raise ValueError("two teams cannot be pinned to the same place")
        return self
