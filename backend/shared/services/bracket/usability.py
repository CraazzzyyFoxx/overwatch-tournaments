"""Whether a bracket-engine-generated encounter is live or still a preview.

``admin/stage.py::generate_encounters`` can populate a stage's encounters
while the stage is still Draft (``Stage.is_active=False``, ``Stage.
is_published=False``) -- e.g. an organizer previewing an upcoming playoff
bracket's shape before the current stage finishes. Nothing else distinguishes
that preview from a real, playable encounter, so every mutating action a
captain (or the pick-ban engine) can take on an encounter goes through
``is_encounter_live`` first.

Gated on ``is_published``, never ``is_active``: ``is_active`` is a tournament
-wide singleton that moves to whichever stage is currently selected and turns
back off the moment another stage activates, so gating on it would lock
out in-flight reporting on a stage the organizer has since moved past.
``is_published`` is sticky -- set once by ``activate_stage`` and never
cleared -- so a stage that already went live stays usable forever.

Scrim encounters (``stage_id is None``) have no stage and are always live.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.stage import Stage

__all__ = ("assert_encounter_live", "is_encounter_live")


async def is_encounter_live(session: AsyncSession, encounter: Encounter) -> bool:
    """True when the encounter's bracket has been published (or it has none).

    Looks the stage up via ``session.get`` rather than the ORM relationship so
    it works whether or not the caller eager-loaded ``Encounter.stage`` --
    ``session.get`` is satisfied from the identity map when it was.
    """
    if encounter.stage_id is None:
        return True
    stage = await session.get(Stage, encounter.stage_id)
    return stage is None or stage.is_published


async def assert_encounter_live(session: AsyncSession, encounter: Encounter) -> None:
    """409 for an encounter of a preview bracket: look-only until its stage is activated."""
    if not await is_encounter_live(session, encounter):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stage bracket is a preview and is not active yet",
        )
