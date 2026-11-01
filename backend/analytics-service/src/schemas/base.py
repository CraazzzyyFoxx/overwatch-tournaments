"""Minimal Pydantic readers — kept local to analytics-service.

These mirror the subset of ``app-service`` Pydantic shapes that the analytics
read API needs to return. Duplicating the few fields here is much cheaper than
pulling the entire ``app-service`` schema graph (which references team / user /
tournament / standing readers).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from shared.schemas.identity import PersonDisplayRead
from shared.schemas.role import RoleRef

__all__ = (
    "BaseRead",
    "UserReadMin",
    "TeamGroupMin",
    "TournamentMin",
    "PlayerRead",
    "TeamRead",
)


class BaseRead(BaseModel):
    """Common ``id`` + ``created_at`` + ``updated_at`` mixin."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime | None = None


class UserReadMin(BaseRead):
    """Minimal user fields the analytics responses need.

    Only includes plain *columns* — relationship-backed fields like
    ``battle_tag``, ``discord``, ``twitch`` would trigger lazy IO once the
    async session is detached and aren't actually consumed by the frontend
    analytics surface.
    """

    name: str | None = None
    avatar_url: str | None = None


class TeamGroupMin(BaseModel):
    """The group a team played in: a ``StageItem`` of type GROUP, name only."""

    id: int
    name: str


class TournamentMin(BaseRead):
    name: str | None = None
    is_finished: bool | None = None
    division_grid_version_id: int | None = None


class PlayerRead(BaseRead):
    name: str | None = None
    #: How the tournament's game names the player (``name`` is the roster snapshot).
    display: PersonDisplayRead
    rank: int | None
    division: int | None = None
    role: RoleRef | None = None
    tournament_id: int
    user_id: int
    team_id: int
    is_newcomer: bool
    is_newcomer_role: bool
    is_substitution: bool
    related_player_id: int | None = None
    user: UserReadMin | None = None


class TeamRead(BaseRead):
    name: str
    image_url: str | None = None
    avg_sr: float
    total_sr: float
    captain_id: int | None = None
    tournament_id: int
    tournament: TournamentMin | None = None
    placement: int | None = None
    group: TeamGroupMin | None = None
