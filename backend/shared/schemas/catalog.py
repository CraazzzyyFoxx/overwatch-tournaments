"""Catalog read models shared by app-service, stats-service, and tournament-service.

``CatalogEntityRead`` is the one native wire for a ``catalog.entity`` row of any discipline and kind (public reads,
admin CRUD, embedded relationships). The character playtime/leaderboard parameter shapes live here once so every
service that serves them shares one definition (same consolidation as ``shared/schemas/base.py``).
"""

import typing
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from shared.core import enums, pagination
from shared.schemas.base import BaseRead
from shared.schemas.identity import PersonDisplayRead
from shared.schemas.role import RoleRef

__all__ = (
    "CatalogEntityRead",
    "CatalogEntityRef",
    "CharacterLeaderboardEntry",
    "CharacterLeaderboardParams",
    "CharacterLeaderboardQueryParams",
    "CharacterPlaytime",
    "CharacterPlaytimePaginationParams",
    "CharacterPlaytimeQueryPaginationParams",
)


class CatalogEntityRead(BaseRead):
    """One ``catalog.entity`` row of any discipline and kind; the public, admin and embedded catalog wire."""

    created_at: datetime
    updated_at: datetime | None = None
    discipline: str
    kind: typing.Literal["character", "map", "mode"]
    slug: str
    name: str
    image_path: str | None
    parent_id: int | None
    attrs: dict[str, Any]
    aliases: list[str]
    active: bool
    #: Same shape, one level deep: ``parent.parent`` is always ``None``.
    parent: CatalogEntityRead | None = None

    @classmethod
    def from_entity(cls, entity: Any, *, with_parent: bool = True) -> typing.Self:
        """``with_parent`` reads ``entity.parent`` when the row has a ``parent_id``; the caller must have loaded it
        (an async lazy load raises). A row without a parent never touches the relationship."""
        parent = entity.parent if with_parent and entity.parent_id is not None else None
        return cls(
            id=entity.id,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
            discipline=entity.discipline,
            kind=entity.kind,
            slug=entity.slug,
            name=entity.name,
            image_path=entity.image_path,
            parent_id=entity.parent_id,
            attrs=dict(entity.attrs or {}),
            aliases=list(entity.aliases or []),
            active=entity.active,
            parent=None if parent is None else cls.from_entity(parent, with_parent=False),
        )


class CatalogEntityRef(BaseModel):
    """A ``catalog.entity`` named and drawn, nothing more: what a compact strip of characters renders."""

    id: int
    slug: str
    name: str
    image_path: str | None

    @classmethod
    def from_entity(cls, entity: Any) -> typing.Self:
        return cls(id=entity.id, slug=entity.slug, name=entity.name, image_path=entity.image_path)


class CharacterPlaytime(BaseModel):
    """One character's share of the observed playtime (a fraction of the returned set), not a duration."""

    entity: CatalogEntityRead
    playtime: float


class CharacterPlaytimeQueryPaginationParams(pagination.PaginationSortQueryParams):
    user_id: int | typing.Literal["all"] = "all"
    sort: typing.Literal["id", "name", "slug", "playtime"] = "playtime"
    tournament_id: int | None = None


@dataclass
class CharacterPlaytimePaginationParams(pagination.PaginationSortParams):
    user_id: int | typing.Literal["all"] = "all"
    # role: enums.HeroRole | typing.Literal["all"] = "all"
    tournament_id: int | None = None


class CharacterLeaderboardEntry(BaseModel):
    rank: int
    user_id: int
    #: How the leaderboard's game names the player: the scope workspace's name, the game handle, the player's latest
    #: roster name, the canonical name (``display.canonical`` builds the profile link).
    display: PersonDisplayRead
    role: RoleRef | None = None
    #: The workspace grid's tier number in a scoped read; in the all-workspaces read the canonical number on the
    #: game's native ladder (``None`` for a game without one).
    div: int | None
    #: Which stored grid ``div`` is a number on (scoped reads; those grids ship once per page in ``division_grids``).
    #: ``None`` in the all-workspaces read: the native ladder is in-code.
    division_grid_version_id: int | None = None
    team: str | None = None
    team_id: int | None = None
    games_played: int
    playtime_seconds: float
    per10_eliminations: float
    per10_healing: float
    per10_deaths: float
    per10_damage: float
    per10_final_blows: float
    per10_damage_blocked: float
    per10_solo_kills: float
    per10_obj_kills: float
    per10_defensive_assists: float
    per10_offensive_assists: float
    per10_all_damage: float
    per10_damage_taken: float
    per10_self_healing: float
    per10_ultimates_used: float
    per10_multikills: float
    per10_env_kills: float
    per10_crit_hits: float
    avg_weapon_accuracy: float
    avg_crit_accuracy: float
    kd: float
    kda: float


class CharacterLeaderboardQueryParams(pagination.PaginationQueryParams):
    tournament_id: int | None = None
    stat: enums.LogStatsName = enums.LogStatsName.Eliminations


@dataclass
class CharacterLeaderboardParams(pagination.PaginationParams):
    tournament_id: int | None = None
    stat: enums.LogStatsName = enums.LogStatsName.Eliminations

    @classmethod
    def from_query_params(cls, query_params: CharacterLeaderboardQueryParams) -> CharacterLeaderboardParams:  # type: ignore[override]
        return cls(
            page=query_params.page,
            per_page=query_params.per_page,
            entities=query_params.entities,
            tournament_id=query_params.tournament_id,
            stat=query_params.stat,
        )
