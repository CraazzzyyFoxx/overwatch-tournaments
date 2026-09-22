"""The single way to journal one GAME's accepted-result transition.

The sibling helper ``result_audit.record_result_transition`` records what moved
the ENCOUNTER's result; this one records what moved one position of the series
(``tournament.encounter_game``). Both append to the same table, so an admin
reads one ordered history: ``game_id``/``game_result_version`` are set here and
NULL there, and the ``*_score_after`` pair carries the GAME's accepted score for
the ``GAME_*`` actions (see ``EncounterResultAudit``).

The encounter's own ``result_status`` does not move when a game is confirmed --
only the official finalize touches it -- so ``from_``/``to_result_status`` are
both the encounter's current status: the row says "nothing changed at the series
level", which is the truth.

Like its sibling, this never commits: the row rides the caller's transaction.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import EncounterGameState, EncounterResultAuditAction
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.encounter_result_audit import EncounterResultAudit
from shared.repository import EncounterResultAuditRepository

__all__ = ("cancel_games", "record_game_result_transition")

_result_audit = EncounterResultAuditRepository()


def record_game_result_transition(
    session: AsyncSession,
    encounter: Encounter,
    game: EncounterGame,
    *,
    action: EncounterResultAuditAction,
    source: str,
    actor_user_id: int | None,
    home_score_before: int | None,
    away_score_before: int | None,
    reason: str | None = None,
) -> EncounterResultAudit:
    """Append one game transition row. ``actor_user_id=None`` = machine actor."""
    row = EncounterResultAudit(
        encounter_id=encounter.id,
        actor_user_id=actor_user_id,
        action=action,
        from_result_status=encounter.result_status,
        to_result_status=encounter.result_status,
        home_score_before=home_score_before,
        away_score_before=away_score_before,
        home_score_after=game.accepted_home_score,
        away_score_after=game.accepted_away_score,
        game_id=game.id,
        game_result_version=game.result_version,
        reason=reason,
        source=source,
    )
    return _result_audit.add(session, row)


def cancel_games(
    session: AsyncSession,
    encounter: Encounter,
    games: Sequence[EncounterGame],
    *,
    actor_user_id: int | None,
    reason: str,
) -> None:
    """Retire positions as history. A cancelled confirmed game loses its wins
    from the live score, so the journal has to say who dropped them.

    Shared because both the service path and the bracket's cascade reset cancel
    games, and an unaudited cancellation is a score change nobody signed for.
    Callers own re-materialising the series score.
    """
    for game in games:
        if game.state == EncounterGameState.CANCELLED:
            continue
        was_confirmed = game.state == EncounterGameState.CONFIRMED
        game.state = EncounterGameState.CANCELLED
        if was_confirmed:
            record_game_result_transition(
                session,
                encounter,
                game,
                action=EncounterResultAuditAction.GAME_CANCEL,
                source="admin" if actor_user_id is not None else "system",
                actor_user_id=actor_user_id,
                home_score_before=game.accepted_home_score,
                away_score_before=game.accepted_away_score,
                reason=reason,
            )
