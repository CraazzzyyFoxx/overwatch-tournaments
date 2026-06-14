from pydantic import BaseModel

__all__ = (
    "TeamCreate",
    "TeamUpdate",
    "PlayerCreate",
    "PlayerUpdate",
)


class TeamCreate(BaseModel):
    """Schema for creating a team"""

    name: str
    balancer_name: str | None = None
    tournament_id: int
    captain_id: int
    avg_sr: float = 0.0
    total_sr: int = 0


class TeamUpdate(BaseModel):
    """Schema for updating a team"""

    name: str | None = None
    balancer_name: str | None = None
    captain_id: int | None = None
    avg_sr: float | None = None
    total_sr: int | None = None


class PlayerCreate(BaseModel):
    """Schema for creating a player"""

    name: str
    user_id: int
    team_id: int
    tournament_id: int
    role: str | None = None
    rank: int = 0
    div: int = 0
    sub_role: str | None = None
    is_newcomer: bool = False
    is_newcomer_role: bool = False
    is_substitution: bool = False
    related_player_id: int | None = None


class PlayerUpdate(BaseModel):
    """Schema for updating a player"""

    name: str | None = None
    role: str | None = None
    rank: int | None = None
    div: int | None = None
    sub_role: str | None = None
    is_newcomer: bool | None = None
    is_newcomer_role: bool | None = None
    is_substitution: bool | None = None
    related_player_id: int | None = None
