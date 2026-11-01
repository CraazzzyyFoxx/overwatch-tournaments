"""The workspace roster's wire shapes: the add-player and rank-write bodies and the row ``players.list`` / ``players.upsert`` return."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.schemas.identity import PersonDisplayRead, PlayerIdentityRead

__all__ = ("WorkspacePlayerRanksWrite", "WorkspacePlayerRead", "WorkspacePlayerUpsert")


class WorkspacePlayerUpsert(BaseModel):
    """``POST /balancer/workspaces/{id}/players``: find-or-admit the member a game identity denotes.

    ``identity.provider`` must be the discipline's own identity provider; there is no ``battle_tag`` spelling.
    """

    model_config = ConfigDict(extra="forbid")

    discipline: str = Field(description="An enabled discipline of the workspace.")
    identity: PlayerIdentityRead
    display_name: str | None = Field(
        default=None, description="Roster display name; blank is none. Setting it needs workspace team.create."
    )

    @field_validator("display_name")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None


class WorkspacePlayerRanksWrite(BaseModel):
    """``PUT /balancer/workspaces/{id}/players/{member_id}/ranks``: one rank layer of one member.

    ``discipline`` is required: a rank write names its game rather than landing on the workspace's first.
    """

    discipline: str = Field(description="An enabled discipline of the workspace whose rated roles hold the ranks.")
    scope: Literal["workspace", "author"] = Field(
        default="workspace", description="The shared canon, or the caller's own book."
    )
    ranks: dict[str, int] = Field(default_factory=dict, description="Rank values to set, by rated role code.")
    clear: list[str] = Field(
        default_factory=list, description="Role codes deleted from the layer, restoring inheritance."
    )


class WorkspacePlayerRead(BaseModel):
    """One roster row, identically shaped for a list page and the upsert answer."""

    member_id: int
    player_id: int
    identity: PlayerIdentityRead | None = Field(
        description="Primary account of the requested discipline's identity provider; null when the player has none."
    )
    display_name: str | None
    display: PersonDisplayRead = Field(description="How the member is named in this workspace's game.")
    auth_user_id: int | None = Field(description="Linked login (auth.user.id); null if the player never signed in.")
    ranks: dict[str, int] = Field(description="The workspace canon, by rated role code.")
    author_ranks: dict[str, int] = Field(description="The read author's own book, by rated role code.")
