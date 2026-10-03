"""The organizer's tournament-wide view of every pre-game room.

One row per encounter whose pick-ban room can exist, carrying only what the
overview table draws: where the room stands (``phase``), what is keeping it
there (the two kind summaries), and what wants a human (``attention``). The
room ITSELF is still read through ``get_pick_ban_state`` -- this is the list
that tells an organizer which room to open, so it is deliberately thin: no
pools, no submissions, no per-viewer anything.

Nulls carry meaning and are never dropped on the wire: a ``null`` kind summary
is a kind this encounter plays no room of at all, while a summary with
``status: null`` is a configured room that has not opened yet and whose
``reason`` says why.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

__all__ = (
    "PregameGamesSummary",
    "PregameKindSummary",
    "PregameRoomHistoryEntry",
    "PregameRoomHistoryRead",
    "PregameRoomRow",
    "PregameRoomTeam",
    "PregameRoomsRead",
)

#: Where a room stands, most urgent phase first (see ``derive_phase``).
PregamePhase = Literal["teams_unknown", "readiness", "map", "hero", "report", "done", "idle"]
PregameAttention = Literal["game_disputed", "result_disputed", "awaiting_choice", "overdue", "late_not_ready"]


class PregameRoomTeam(BaseModel):
    id: int
    name: str


class PregameKindSummary(BaseModel):
    """One kind's (map|hero) room, as the overview needs it."""

    #: ``None`` while the kind is configured but no session exists yet.
    status: Literal["active", "completed", "cancelled"] | None = None
    #: The ``REASON_*`` string explaining a ``null`` status; ``None`` otherwise.
    reason: str | None = None
    current_round: int | None = None
    #: The OPEN step's index, or ``None`` when nothing is open (complete, or a
    #: round awaiting an opener choice).
    step_index: int | None = None
    step_count: int = 0
    #: The open step's action (``ban``/``pick``/``protect``) and blindness.
    step_action: str | None = None
    step_blind: bool = False
    #: Sides that still owe the open step an answer.
    acting_sides: list[Literal["home", "away"]] = []
    step_started_at: datetime | None = None
    #: ``step_started_at`` + the open step's timer, when it has one.
    deadline_at: datetime | None = None
    #: Set while an organizer has frozen this kind's room: no clock runs and no
    #: captain may write, so ``deadline_at`` is ``null`` for as long as it holds.
    paused_at: datetime | None = None
    awaiting_choice: bool = False


class PregameGamesSummary(BaseModel):
    """The series' positions by state. Cancelled positions are history and are
    counted nowhere -- a replayed map would otherwise read as two."""

    total: int = 0
    confirmed: int = 0
    disputed: int = 0
    awaiting_result: int = 0


class PregameRoomRow(BaseModel):
    encounter_id: int
    name: str
    stage_id: int | None = None
    stage_name: str | None = None
    round: int
    best_of: int
    scheduled_at: datetime | None = None
    status: str
    result_status: str | None = None
    home_team: PregameRoomTeam | None = None
    away_team: PregameRoomTeam | None = None
    home_score: int = 0
    away_score: int = 0
    readiness: dict[str, bool]
    phase: PregamePhase
    #: ``None`` = this encounter plays no room of that kind (no pooled config,
    #: no session); a summary with ``status: null`` is one that has not opened.
    map: PregameKindSummary | None = None
    hero: PregameKindSummary | None = None
    games: PregameGamesSummary
    attention: list[PregameAttention] = []


class PregameRoomsRead(BaseModel):
    tournament_id: int
    #: When the snapshot was taken -- the client compares deadlines against it
    #: rather than against its own clock.
    generated_at: datetime
    rooms: list[PregameRoomRow]


class PregameRoomHistoryEntry(BaseModel):
    """One line of the room's journal, from either of the two tables it merges."""

    #: ``"room:<id>"`` / ``"result:<id>"`` -- the two sources number their rows
    #: independently, so a bare id would collide across them.
    id: str
    at: datetime
    origin: Literal["room", "result"]
    #: The room vocabulary (``room_journal``), or the result audit's own action
    #: verbatim (``confirm``, ``reopen``, ``game_cancel``, ...).
    action: str
    kind: Literal["map", "hero"] | None = None
    source: Literal["captain", "admin", "system"]
    side: Literal["home", "away"] | None = None
    actor_auth_user_id: int | None = None
    #: Display name of whoever acted; null for the clock and the engine.
    actor_name: str | None = None
    reason: str | None = None
    data: dict = {}


class PregameRoomHistoryRead(BaseModel):
    encounter_id: int
    entries: list[PregameRoomHistoryEntry]
