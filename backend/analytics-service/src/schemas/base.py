"""Minimal Pydantic readers — kept local to analytics-service.

These mirror the subset of ``app-service`` Pydantic shapes that the analytics
read API needs to return. Duplicating the few fields here is much cheaper than
pulling the entire ``app-service`` schema graph (which references team / user /
tournament / standing readers).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = (
    "BaseRead",
    "UserReadMin",
    "TournamentGroupMin",
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


class TournamentGroupMin(BaseRead):
    name: str
    tournament_id: int


class TournamentMin(BaseRead):
    number: int | None = None
    name: str | None = None
    is_finished: bool | None = None
    division_grid_version_id: int | None = None


class PlayerRead(BaseRead):
    name: str | None = None
    sub_role: str | None = None
    rank: int
    division: int | None = None
    role: str
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
    avg_sr: float
    total_sr: float
    captain_id: int | None = None
    tournament_id: int
    tournament: TournamentMin | None = None
    placement: int | None = None
    group: TournamentGroupMin | None = None
