"""Telling the organizers that a captain contradiction needs their decision.

Two different flows produce the same stalemate — ``map_report`` when the two
per-map claims for one position disagree, ``captain`` when the two FINAL series
scores do — and in both the captains have already been told. That is not enough:
a captain can only re-report, and two captains who disagree once disagree twice.
Somebody with ``match.result`` has to adopt a side, and nobody sits watching the
admin screens for a dispute to appear.

Lives beside the two producers rather than in ``shared.services.notifications``
because it is a tournament-domain decision (which workspace owns the encounter,
which permission marks an organizer), not part of the inbox primitive.
"""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_game import EncounterGame
from shared.repository.notification_recipients import NotificationRecipientRepository
from shared.services.notifications import STAFF_PERMISSION, notify

__all__ = ("notify_dispute_review",)

_recipients = NotificationRecipientRepository()


async def notify_dispute_review(
    session: AsyncSession,
    encounter: Encounter,
    *,
    workspace_id: int | None,
    home_team_name: str,
    away_team_name: str,
    game: EncounterGame | None = None,
    actor_auth_user_id: int | None = None,
    skip_auth_user_ids: Collection[int] = (),
) -> None:
    """One ``encounter.dispute_review`` row per organizer who can resolve it.

    ``game=None`` is the series-level dispute. ``skip_auth_user_ids`` is the set
    already told as a CAPTAIN: an organizer who also captains a team in their own
    tournament would otherwise get the same event twice, in two voices.

    Never commits — like every ``notify()`` caller, this runs inside the flow's
    own transaction so the row and the dispute land together or not at all.
    """
    if workspace_id is None:
        # A tournament with no tenant has no organizers to page; the captains'
        # own notifications still went out.
        return
    # The permission that can END a dispute (adopt a side, set the score); read
    # access would page spectators of the admin panel.
    staff = await _recipients.workspace_staff_auth_user_ids(session, workspace_id, *STAFF_PERMISSION)
    already_told = set(skip_auth_user_ids)
    # ponytail: the dedupe key is the game (or the series), so once an organizer
    # has been paged about this position they are never paged about it again --
    # including after they reopen it and the captains disagree a second time.
    # Upgrade path is a key that carries the reopen generation, when reopening
    # turns out to be common enough that the silence is felt.
    dedupe_key = f"game:{game.id}" if game is not None else f"series:{encounter.id}"
    for recipient in staff:
        if recipient in already_told:
            continue
        await notify(
            session,
            kind="encounter.dispute_review",
            recipient_auth_user_id=recipient,
            source_workspace_id=workspace_id,
            actor_auth_user_id=actor_auth_user_id,
            dedupe_key=dedupe_key,
            payload={
                "encounter_id": encounter.id,
                "tournament_id": encounter.tournament_id,
                "game_id": None if game is None else game.id,
                # 0 is the series-level sentinel the inbox's ``plural`` selects
                # on; an absent key is not an ICU argument.
                "position": 0 if game is None else game.position,
                "home_team_name": home_team_name,
                "away_team_name": away_team_name,
            },
        )
