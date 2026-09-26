"""FFA lobby request bodies and the read model the lobby table is drawn from.

The write side mirrors what ``FfaEncounterService`` accepts; the read side is
one shape for both public endpoints -- a stage answers a list of lobbies and a
single lobby answers one of them, so the table renders from the same model
either way (docs/plans/2026-09-24-ffa-encounters.md §6).

Nulls carry meaning here and are never dropped on the wire: a cell with no
``state`` is a game nobody has entered yet, and a row with no ``position`` is a
group the standings job has not ranked once.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from shared.core import enums
from shared.domain.ffa_scoring import FFA_MAX_LOBBY_SIZE

__all__ = (
    "FfaGameCancelInput",
    "FfaGameCellRead",
    "FfaGameResultLineInput",
    "FfaGameResultsInput",
    "FfaGamesCountInput",
    "FfaLobbyRead",
    "FfaLobbyRowRead",
    "FfaRulesRead",
)


class FfaGameResultLineInput(BaseModel):
    team_id: int
    placement: int | None = Field(default=None, ge=1)
    score: int = Field(ge=0)


class FfaGameResultsInput(BaseModel):
    results: list[FfaGameResultLineInput] = Field(min_length=2, max_length=FFA_MAX_LOBBY_SIZE)
    reason: str | None = Field(default=None, max_length=500)


class FfaGameCancelInput(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


class FfaGamesCountInput(BaseModel):
    games: int = Field(ge=1, le=50)


class FfaRulesRead(BaseModel):
    placement_points: list[float]
    score_points: float
    score_label: str | None


class FfaGameCellRead(BaseModel):
    position: int
    #: ``None`` — the game has not been opened yet.
    state: enums.EncounterGameState | None
    placement: int | None
    score: int | None
    points: float | None


class FfaLobbyRowRead(BaseModel):
    team_id: int
    team_name: str
    team_image_url: str | None
    slot: int
    #: ``Standing.position`` — the number advancement reads. ``None`` until the
    #: standings job has ranked the group once.
    position: int | None
    tie_group: int | None
    #: The organizer pinned ``position``: it is not what the points earn.
    is_pinned: bool = False
    points: float
    games_played: int
    wins: int
    score: int
    games: list[FfaGameCellRead]


class FfaLobbyRead(BaseModel):
    encounter_id: int
    tournament_id: int
    stage_id: int | None
    stage_item_id: int | None
    name: str
    status: enums.EncounterStatus
    result_status: enums.EncounterResultStatus
    best_of: int
    scheduled_at: datetime | None
    #: Item override, else the stage's number; ``None`` draws no cut line.
    advance_count: int | None
    rules: FfaRulesRead
    rows: list[FfaLobbyRowRead]
