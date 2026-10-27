"""Admin correction of one position's result.

A confirmed game is locked against participants -- ``submit_game_claim`` refuses
it with ``result_locked`` -- so this is the only way its numbers ever change,
and it always carries a reason into the result journal.

The hard part is not the numbers: it is what the OLD result already decided.
A correction that changes who won position N changes the encounter's standing,
and a standing is what the bracket advanced on. So when the encounter's result
was already confirmed, the correction is the full sequence -- ``reopen`` the
encounter, ``reset_downstream`` to un-seat and re-state everything it fed,
write the new game result, then ``advance_after_result`` on what the games now
say. Anything less leaves a later round holding a team that did not win.

That result also opened the room's NEXT round under a result rotation. An
untouched one is scrapped and re-appended for the corrected opener; one already
in use refuses the whole correction (409 ``dependent_round_started``) before
the audit and before any write -- guard, audit, correction, one commit.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import (
    EncounterGameResultSource,
    EncounterGameState,
    EncounterResultStatus,
    PickBanKind,
)
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.models.encounter.encounter import Encounter
from shared.services.encounter.result import lock_encounter, reopen
from src.services.bracket import advancement
from src.services.encounter.games import (
    EncounterGameService,
    GameResultIn,
    encounter_game_service,
)
from src.services.encounter.pick_ban_session import PickBanSessionService, pick_ban_session_service
from src.services.encounter.realtime_commit import emit_pick_ban_update
from src.services.encounter.settle import enqueue_challonge_push
from src.services.tournament.events import enqueue_tournament_recalculation

__all__ = ("GameCorrectionService", "game_correction_service")


class GameCorrectionService:
    """The organizer's override of one position's result, and the cascade it
    sometimes owes."""

    def __init__(
        self,
        *,
        games: EncounterGameService = encounter_game_service,
        sessions: PickBanSessionService = pick_ban_session_service,
    ) -> None:
        self.games = games
        self.sessions = sessions

    async def correct_game(
        self,
        session: AsyncSession,
        encounter_id: int,
        *,
        game_id: int,
        results: Sequence[GameResultIn],
        actor_user_id: int,
        reason: str,
        audit: Callable[[AsyncSession], Awaitable[object]],
    ) -> dict:
        """Write ``results`` onto one position as an ADMIN result. Commits once.

        ``audit`` writes the caller's audit row on ``session``. It runs only once
        the dependent-round guard has passed and before anything is written, so
        a refused correction leaves no audit row, and an accepted one commits
        its audit, result, bracket and rebuilt round together.

        Returns ``{"game": ..., "reset_downstream": bool}``.
        """
        if not (reason or "").strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[ApiExc(code="reason_required", msg="Correcting a result needs a stated reason")],
            )
        # Encounter first, then the game -- the lock order every result path
        # takes, so a captain's claim and this correction queue instead of
        # deadlocking.
        encounter = await lock_encounter(session, encounter_id)
        game = await self.games.game_repo.get_for_update(session, game_id)
        if game is None or game.encounter_id != encounter.id or game.state == EncounterGameState.CANCELLED:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")

        plan = await self.sessions.plan_dependent_rounds(session, encounter, game, results)
        await audit(session)
        rebuilt = await self.sessions.apply_dependent_rounds(session, plan)
        cascaded = await self._unwind(session, encounter, actor_user_id=actor_user_id, reason=reason)
        await self.games.record_result(
            session,
            encounter,
            game,
            results=results,
            source=EncounterGameResultSource.ADMIN,
            actor_user_id=actor_user_id,
            reason=reason,
        )
        for kind in rebuilt:
            # Re-appends the scrapped round off the corrected result (its own
            # ``round_opened`` row), or re-raises the choice for the new loser.
            await self.sessions._sync_rounds(session, encounter, kind, commit=False, encounter_locked=True)
        # A correction moves the encounter's standing and may reseat a whole
        # bracket branch through ``reset_downstream``: every cached
        # tournament-encounters read is stale and the standings have to be
        # rebuilt. ``enqueue_tournament_recalculation`` emits the invalidation
        # and queues the job in one call.
        await enqueue_tournament_recalculation(session, encounter.tournament_id)
        await emit_pick_ban_update(session, encounter.id)
        await emit_pick_ban_update(session, encounter.id, kind=PickBanKind.HERO.value)
        # Every confirm path pushes; a correction bumps the version (reopen, then
        # re-confirm), so the push already queued for the old one goes stale.
        if encounter.result_status == EncounterResultStatus.CONFIRMED:
            await enqueue_challonge_push(session, encounter)
        await session.commit()
        lines = (await self.games.lines_by_game(session, [game])).get(game.id) or []
        claims = (await self.games.claim_payloads(session, [game]))[game.id]
        return {"game": self.games.serialize(game, lines, claims), "reset_downstream": cascaded}

    async def _unwind(self, session: AsyncSession, encounter: Encounter, *, actor_user_id: int, reason: str) -> bool:
        """Take a standing correction back out of the bracket before rewriting it.

        Only when a result was actually standing. ``reopen`` is what un-makes
        the decision (and is why this needs a real actor), and
        ``reset_downstream`` retires the seats it filled, cancels the games
        those seats had not played and re-states every target -- recursively,
        because a correction three rounds up invalidates everything below it.
        """
        if encounter.result_status != EncounterResultStatus.CONFIRMED:
            return False
        await reopen(session, encounter, actor_user_id=actor_user_id, reason=reason)
        await advancement.reset_downstream(session, encounter, actor_user_id=actor_user_id)
        return True


game_correction_service = GameCorrectionService()
