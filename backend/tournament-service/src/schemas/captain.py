"""Captain result-submission and pick-ban request schemas.

The typed-RPC handlers validate captain bodies through here. This module must
NOT import fastapi.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ── Schemas ──────────────────────────────────────────────────────────────


class PickBanActionInput(BaseModel):
    """One ban/pick/protect against an OPEN (non-blind) step of a hero- or
    map-kind pick-ban session. ``target_player_id`` is required exactly when
    the step names an opponent roster player (``step.target``)."""

    #: The catalog item, or -- for a ``side_pick`` step -- the INDEX into the
    #: discipline's side codes (the room state's ``sides`` array).
    item_id: int
    action: str  # "ban" | "pick" | "protect" | "side_pick"
    target_player_id: int | None = None
    #: A mix's member pick (spec §11.6): the ``encounter.team_member`` seat the hero is for (``state.members[].id``).
    member_id: int | None = None


class PickBanSubmissionItemInput(BaseModel):
    """One item of a blind draft: what is chosen, and for whom on a target step."""

    item_id: int
    target_player_id: int | None = None
    #: An assignment's item: the member this hero is given to (spec §11.6 R4-1).
    member_id: int | None = None


class PickBanSubmitInput(BaseModel):
    """A blind step's whole draft, replacing whatever the participation had.
    ``lock`` validates it in full and makes it final — the step reveals once
    every acting participation has locked."""

    items: list[PickBanSubmissionItemInput] = Field(default_factory=list)
    lock: bool = False


class ElectOpenerInput(BaseModel):
    """``result_loser_choice`` rotation only: the losing captain names which
    PARTICIPATION opens the next round's bans."""

    first_team_id: int


class PickBanUndoInput(BaseModel):
    """One captain's consent to undo the session's last action. ``consent=False``
    withdraws an open request — the asker changing their mind and the opponent
    refusing are the same outcome, so they share one field."""

    consent: bool = True


class GameClaimResultIn(BaseModel):
    """One participation's numbers inside a game claim."""

    encounter_team_id: int
    score: int | None = Field(default=None, ge=0)
    placement: int | None = Field(default=None, ge=1)
    column_values: dict[str, float] = Field(default_factory=dict)


class GameClaimIn(BaseModel):
    """One captain's independent claim of a single played GAME's result —
    submitted immediately after that position, not at series end (contrast
    ``TeamReportIn``). The position, not the map, identifies what is being
    claimed: a series may play the same map twice. See
    ``services.encounter.map_report``."""

    #: The ``game.result_version`` the claim was made against -- a correction
    #: landing in between makes this claim stale rather than silently winning.
    basis_version: int = 0
    results: list[GameClaimResultIn] = Field(default_factory=list)


class GameMapSelectInput(BaseModel):
    """Freeplay's half of what the map pick-ban does automatically: a captain
    names the map an open position is played on."""

    map_id: int


class MatchImportInput(BaseModel):
    """The game's match as its discipline's source names it (a match id); the stats service checks the shape."""

    external_id: str = Field(min_length=1, max_length=128)


class MatchImportWarningRead(BaseModel):
    """An organizer warning about an import: ``fetch_failed``, ``participants_dropped`` (``count`` players fewer than
    the format's starters were observed) or ``banned_character_played`` (``characters`` the game's hero room banned).
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


class CaptainMapCodeInput(BaseModel):
    map_index: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=32)


class TeamReportResultIn(BaseModel):
    """One participation's line of a series report.

    ``wins`` is omitted when the encounter's rule does not count them (a
    lobby's card, where points alone decide); ``placement`` when the form does
    not ask for places.
    """

    encounter_team_id: int
    score: float = Field(ge=0)
    placement: int | None = Field(default=None, ge=1)
    wins: int | None = Field(default=None, ge=0)


class TeamReportIn(BaseModel):
    """One participation's independent report of the finished encounter.

    ``results`` carries one line per live seat -- a duel reports two, a lobby
    as many as it seats, and neither is oriented. Everything after
    ``games_played`` is optional here and validated against the tournament's
    report-form config server-side (``services.encounter.report_form``),
    because what is required depends on that config, not on the wire shape.
    """

    #: The ``encounter.result_version`` the report was filed against -- a
    #: correction landing in between makes it stale rather than a winner.
    basis_version: int = 0
    #: Draws included: how many of the series' positions were actually played.
    games_played: int = Field(ge=0)
    results: list[TeamReportResultIn] = Field(default_factory=list)
    closeness: int | None = Field(default=None, ge=1, le=10)
    map_codes: list[CaptainMapCodeInput] = Field(default_factory=list)
    comment: str | None = None
    custom_fields: dict[str, str] = Field(default_factory=dict)
