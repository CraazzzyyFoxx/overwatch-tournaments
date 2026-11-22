"""``participants_count``: how many people are admitted to a tournament, as one SQL expression.

One source for the tournament read (single and list) and the list's sort, so they can never disagree.
"Admitted" is the decision ``evaluate`` reaches for a checked-in entry whose ``signals.ready`` holds: an
approved entry in the ready balancer pool. A tournament with no registration rows at all (a legacy or
imported one) has no admission data: its roster IS the admitted set, so it keeps counting its ``player`` rows.
"""

from __future__ import annotations

import sqlalchemy as sa

from shared import models
from src.services.admission.types import APPROVED_REGISTRATION_STATUS, READY_BALANCER_STATUS

__all__ = ("participants_count_expr",)


def participants_count_expr(tournament_id: sa.ColumnElement[int] | int) -> sa.ColumnElement[int]:
    """Scalar subquery: admitted registrations of ``tournament_id``, or its player rows with no registrations."""
    live_registrations = sa.select(models.Registration.id).where(
        models.Registration.tournament_id == tournament_id,
        models.Registration.deleted_at.is_(None),
    )
    admitted = (
        sa.select(sa.func.count(sa.distinct(models.Registration.id)))
        .select_from(models.RegistrationEntry)
        .join(models.Registration, models.Registration.id == models.RegistrationEntry.registration_id)
        .where(
            models.Registration.tournament_id == tournament_id,
            models.Registration.deleted_at.is_(None),
            models.RegistrationEntry.deleted_at.is_(None),
            models.RegistrationEntry.checked_in.is_(True),
            models.RegistrationEntry.status == APPROVED_REGISTRATION_STATUS,
            models.RegistrationEntry.balancer_status == READY_BALANCER_STATUS,
        )
        .scalar_subquery()
    )
    players = (
        sa.select(sa.func.count(models.Player.id)).where(models.Player.tournament_id == tournament_id).scalar_subquery()
    )
    return sa.case((~live_registrations.exists(), players), else_=admitted)
