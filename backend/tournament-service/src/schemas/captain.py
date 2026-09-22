"""Captain result-submission and map-veto request schemas + viewer-side helper.

Extracted verbatim from the decommissioned ``src/routes/captain.py`` so the
typed-RPC handlers in ``src/rpc/public_rpc.py`` keep validating the SAME bodies
and resolving the viewer side identically. This module must NOT import fastapi.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.services.encounter import captain as captain_mod

# ── Schemas ──────────────────────────────────────────────────────────────


class PickBanActionInput(BaseModel):
    """One ban/pick/protect against a hero- or map-kind pick-ban session."""

    item_id: int
    action: str  # "ban" | "pick" | "protect"


class ElectOpenerInput(BaseModel):
    """``result_loser_choice`` rotation only: the losing captain names who
    opens the next round's bans."""

    first_side: str  # "home" | "away"


class PickBanUndoInput(BaseModel):
    """One captain's consent to undo the session's last action. ``consent=False``
    withdraws an open request — the asker changing their mind and the opponent
    refusing are the same outcome, so they share one field."""

    consent: bool = True


class GameReportInput(BaseModel):
    """One captain's independent claim of a single played GAME's result —
    submitted immediately after that position, not at series end (contrast
    ``CaptainReportSubmission``). The position, not the map, identifies what is
    being claimed: a series may play the same map twice. See
    ``services.encounter.map_report``."""

    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)


class GameMapSelectInput(BaseModel):
    """Freeplay's half of what the map pick-ban does automatically: a captain
    names the map an open position is played on."""

    map_id: int


class CaptainMapCodeInput(BaseModel):
    map_index: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=32)


class CaptainReportSubmission(BaseModel):
    """One captain's independent encounter report.

    ``home_score``/``away_score`` are in the encounter's home/away orientation.
    Everything else is optional here and validated against the tournament's
    report-form config server-side (``services.encounter.report_form``), because
    what is required depends on that config, not on the wire shape.
    """

    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    closeness: int | None = Field(default=None, ge=1, le=10)
    map_codes: list[CaptainMapCodeInput] = Field(default_factory=list)
    comment: str | None = None
    custom_fields: dict[str, str] = Field(default_factory=dict)


# HTTP 403 Forbidden — matched without importing fastapi so this module stays
# fastapi-free. ``captain_service.resolve_captain_side`` raises a
# ``HTTPException`` whose ``status_code`` we inspect by attribute.
_HTTP_403_FORBIDDEN = 403


async def resolve_optional_viewer_side(
    session: AsyncSession,
    auth_user: models.AuthUser | None,
    encounter: models.Encounter,
) -> str | None:
    """Resolve a viewer's captain side for read-only annotation, or ``None``.

    Mirrors the old WebSocket viewer resolution: an authenticated captain gets
    their side ('home'/'away'); anonymous or non-captain viewers get ``None``
    (and see the pool serialized identically — ``viewer_side`` is presentation
    only). A 403 means "not a captain" and resolves to ``None``.
    """
    if auth_user is None:
        return None
    try:
        return await captain_mod.captain_service.resolve_captain_side(session, auth_user, encounter)
    except Exception as exc:  # noqa: BLE001 - re-raised below unless it's a 403
        if getattr(exc, "status_code", None) == _HTTP_403_FORBIDDEN:
            return None
        raise
