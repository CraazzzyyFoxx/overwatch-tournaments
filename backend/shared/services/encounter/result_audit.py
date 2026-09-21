"""The single way to append to an encounter's result history.

Every path that moves ``Encounter.result_status`` records one row here. Callers
capture the "before" values, mutate the encounter, then call this — the "after"
values are read off the encounter so they can never disagree with what was
actually written.

Like the finalization primitive itself, this never commits: the audit row lands
in the caller's transaction, so a rolled-back result leaves no trail of having
happened.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import EncounterResultAuditAction, EncounterResultStatus
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_result_audit import EncounterResultAudit
from shared.repository import EncounterResultAuditRepository

__all__ = ("record_result_transition",)

_result_audit = EncounterResultAuditRepository()


def record_result_transition(
    session: AsyncSession,
    encounter: Encounter,
    *,
    action: EncounterResultAuditAction,
    source: str,
    actor_user_id: int | None = None,
    from_result_status: EncounterResultStatus | None = None,
    home_score_before: int | None = None,
    away_score_before: int | None = None,
    adopted_team_id: int | None = None,
) -> EncounterResultAudit:
    """Append one transition row. ``actor_user_id=None`` means a machine actor."""
    row = EncounterResultAudit(
        encounter_id=encounter.id,
        actor_user_id=actor_user_id,
        action=action,
        from_result_status=from_result_status,
        to_result_status=encounter.result_status,
        home_score_before=home_score_before,
        away_score_before=away_score_before,
        home_score_after=encounter.home_score,
        away_score_after=encounter.away_score,
        adopted_team_id=adopted_team_id,
        source=source,
    )
    return _result_audit.add(session, row)
