"""Captain result-submission and map-veto request schemas + viewer-side helper.

Extracted verbatim from the decommissioned ``src/routes/captain.py`` so the
typed-RPC handlers in ``src/rpc/public_rpc.py`` keep validating the SAME bodies
and resolving the viewer side identically. This module must NOT import fastapi.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.services.encounter import captain as captain_service

# ── Schemas ──────────────────────────────────────────────────────────────


class VetoAction(BaseModel):
    map_id: int
    action: str  # "ban" or "pick"


class CaptainMapCodeInput(BaseModel):
    map_index: int = Field(ge=1)
    code: str = Field(min_length=1, max_length=32)


class CaptainReportSubmission(BaseModel):
    """One captain's independent encounter report.

    ``home_score``/``away_score`` are in the encounter's home/away orientation.
    """

    home_score: int = Field(ge=0)
    away_score: int = Field(ge=0)
    closeness: int = Field(ge=1, le=10)
    map_codes: list[CaptainMapCodeInput] = Field(default_factory=list)


# HTTP 403 Forbidden — matched without importing fastapi so this module stays
# fastapi-free. ``captain_service.resolve_captain_side`` raises a fastapi
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
        return await captain_service.resolve_captain_side(session, auth_user, encounter)
    except Exception as exc:  # noqa: BLE001 - re-raised below unless it's a 403
        if getattr(exc, "status_code", None) == _HTTP_403_FORBIDDEN:
            return None
        raise
