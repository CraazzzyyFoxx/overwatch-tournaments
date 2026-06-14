from pydantic import BaseModel

__all__ = ("StandingUpdate",)


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
