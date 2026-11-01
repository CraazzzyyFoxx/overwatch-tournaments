"""A game's match imported by its external id (``stats.match_fetch``): the body a caller sends, the request it reads.

stats-service answers both the tournament routes (relayed by tournament-service) and the mix routes (its own).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

__all__ = ("MatchImportInput", "MatchImportRead", "MatchImportWarningRead")


class MatchImportInput(BaseModel):
    """The game's match as its discipline's source names it (a match id); the stats service checks the shape."""

    external_id: str = Field(min_length=1, max_length=128)


class MatchImportWarningRead(BaseModel):
    """An organizer warning about an import: ``fetch_failed``, ``participants_dropped`` (``count`` players fewer than
    the tournament format's starters -- a mix round's own seats -- were observed) or ``banned_character_played``
    (``characters`` the game's hero room banned).
    """

    code: Literal["fetch_failed", "participants_dropped", "banned_character_played"]
    count: int | None = None
    characters: list[str] = Field(default_factory=list)


class MatchImportRead(BaseModel):
    """One request to import a game's match by external id (``stats.match_fetch``)."""

    id: int
    status: Literal["pending", "done", "failed"]
    attempts: int
    last_error: str | None = None
    external_id: str
    created_at: datetime
    #: Filled on the organizer's read only; a captain's read is always empty.
    warnings: list[MatchImportWarningRead] = Field(default_factory=list)
