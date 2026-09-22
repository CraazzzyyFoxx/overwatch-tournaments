"""Admin correction of one position's result (spec §6.5 cases 1-3).

A confirmed game is locked against captains -- `map_report.submit_map_report`
refuses it with `result_locked` -- so this is the only way its score ever
changes, and it always carries a reason into the audit journal.

The hard part is not the score: it is what the OLD result already unlocked.
Position N's outcome is what opened map N+1's bans (and, through them, that
map's hero round), so flipping which side won N makes the round that followed
it wrong -- it was opened by the losing side. That round is therefore scrapped
and re-opened on the new outcome, but only while it is still untouched: once
anyone has banned in it, or a later position has a claim, the tail is real
history and the correction is refused (`downstream_started`) rather than
silently deleting it.

A correction that leaves the OUTCOME alone (2:1 -> 3:1) changes no round at
all: the rounds after it were opened by the winner, and the winner is the same.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import (
    EncounterGameResultSource,
    EncounterGameState,
    MapPickSide,
    PickBanKind,
)
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain import pick_ban_engine as engine
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.pick_ban import PickBanSession
from shared.repository import PickBanEntryRepository
from shared.services.realtime import Resource, Scope, emit
from src.services.encounter.games import EncounterGameService, encounter_game_service
from src.services.encounter.map_report import MapReportService, map_report_service
from src.services.encounter.pick_ban_session import (
    PickBanSessionService,
    build_round_sequence,
    pick_ban_session_service,
    rounds_are_progressive,
)
from src.services.encounter.realtime_commit import emit_pick_ban_update


class GameCorrectionService:
    """The organizer's override of a position's result, and the round rebuild it
    sometimes owes."""

    def __init__(
        self,
        *,
        games: EncounterGameService = encounter_game_service,
        reports: MapReportService = map_report_service,
        sessions: PickBanSessionService = pick_ban_session_service,
        entry_repo: PickBanEntryRepository = PickBanEntryRepository(),
    ) -> None:
        self.games = games
        self.reports = reports
        self.sessions = sessions
        self.entry_repo = entry_repo

    # -- the dependent tail ------------------------------------------------
    async def _downstream_started(
        self,
        session: AsyncSession,
        encounter: Encounter,
        game: EncounterGame,
        pick_bans: list[PickBanSession],
    ) -> bool:
        """Whether anything AFTER ``game``'s position has already happened.

        Two kinds of "happened": a pick-ban step was taken in a later round
        (``action_index`` is the record of one committed step), or a later
        position collected a claim or a result. Both are history a rebuild would
        destroy, so they turn the correction into a refusal.
        """
        for pick_ban in pick_bans:
            entries = await self.entry_repo.list_by_session(session, pick_ban.id)
            if any(
                entry.round is not None and entry.round > game.position and entry.action_index is not None
                for entry in entries
            ):
                return True
        later = [row for row in await self.games.list_games(session, encounter.id) if row.position > game.position]
        reports = await self.games.reports_by_game(session, later)
        return any(row.state == EncounterGameState.CONFIRMED or reports.get(row.id) for row in later)

    # -- the rebuild -------------------------------------------------------
    async def _rebuild_round(self, session: AsyncSession, pick_ban: PickBanSession, *, position: int) -> bool:
        """Scrap round ``position + 1`` of ``pick_ban`` so it can be re-opened on
        the corrected outcome. Returns whether this session had such a round to
        scrap at all.

        Both halves of the round have to go: its candidate entries AND the step
        tokens it appended to ``resolved_sequence_json``, because
        ``engine.get_current_step`` indexes entry count into that sequence — a
        session whose tokens outlive its entries reports a step nobody can take.
        The surviving prefix is recomputed rather than sliced blind: each closed
        round contributed exactly the tokens its own candidate count resolves to.

        A flat (round-less) map veto settles the whole series in one round and
        has nothing per-position to rebuild, which ``rounds_are_progressive``
        already says.
        """
        config = await self.sessions._load_config(session, pick_ban.config_id) if pick_ban.config_id else None
        if config is None or not rounds_are_progressive(config, pick_ban.kind):
            return False
        entries = list(await self.entry_repo.list_by_session(session, pick_ban.id))
        await self.entry_repo.delete_for_round(session, session_id=pick_ban.id, round=position + 1)
        kept = sum(
            len(
                build_round_sequence(
                    config,
                    pick_ban.kind,
                    candidate_count=len([entry for entry in entries if entry.round == round_number]),
                    # The opener only rotates WHICH side each token names; the
                    # number of tokens — all this needs — is opener-independent.
                    opener=MapPickSide.HOME,
                )
            )
            for round_number in range(1, position + 1)
        )
        pick_ban.resolved_sequence_json = list(pick_ban.resolved_sequence_json)[:kept]
        # The scrapped round may have been suspended on a `result_loser_choice`
        # election; the outcome it was waiting on is the one being corrected.
        pick_ban.awaiting_choice = False
        pick_ban.pending_loser_side = None
        return True

    # -- the command -------------------------------------------------------
    async def correct(
        self,
        session: AsyncSession,
        encounter: Encounter,
        *,
        game_id: int,
        home_score: int,
        away_score: int,
        actor_user_id: int,
        reason: str,
    ) -> dict:
        """Write ``home_score``/``away_score`` onto one position as an ADMIN
        result. Returns ``{"game": ..., "rebuilt_rounds": [...]}``."""
        # Locked for the same reason a captain claim locks it: the accepted score
        # and the live series score derived from it are written together.
        game = await self.games.game_repo.get_for_update(session, game_id)
        if game is None or game.encounter_id != encounter.id or game.state == EncounterGameState.CANCELLED:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")

        outcome = engine.map_outcome(home_score, away_score)
        rebuilt: list[int] = []

        if game.state == EncounterGameState.CONFIRMED:
            unchanged = engine.map_outcome(game.accepted_home_score, game.accepted_away_score) == outcome
            if unchanged:
                # Same winner, different margin: every later round was opened by
                # the same side it would be opened by now.
                await self._accept(session, encounter, game, home_score, away_score, actor_user_id, reason)
            else:
                rebuilt = await self._flip(
                    session, encounter, game, home_score, away_score, actor_user_id, reason, outcome
                )
        else:
            # Never accepted (awaiting a claim, or disputed): the admin is making
            # the FIRST decision for this position, so the series simply carries
            # on from it.
            await self._accept(session, encounter, game, home_score, away_score, actor_user_id, reason)
            await self.reports.open_next_round(session, encounter, game, outcome)

        # The accepted score moved the encounter's live score and the room's
        # games list; both are stale the moment this commits.
        await emit(
            session,
            scope=Scope.tournament(encounter.tournament_id),
            invalidates=[Resource.TOURNAMENT_ENCOUNTERS],
            entity_ids={"encounter_ids": [encounter.id]},
        )
        await emit_pick_ban_update(session, encounter.id)
        await emit_pick_ban_update(session, encounter.id, kind=PickBanKind.HERO.value)
        await session.commit()
        reports = (await self.games.reports_by_game(session, [game])).get(game.id) or []
        return {"game": self.games.serialize(game, reports), "rebuilt_rounds": rebuilt}

    async def _accept(
        self,
        session: AsyncSession,
        encounter: Encounter,
        game: EncounterGame,
        home_score: int,
        away_score: int,
        actor_user_id: int,
        reason: str,
    ) -> None:
        await self.games.accept_result(
            session,
            encounter,
            game,
            home_score=home_score,
            away_score=away_score,
            source=EncounterGameResultSource.ADMIN,
            actor_user_id=actor_user_id,
            reason=reason,
        )

    async def _flip(
        self,
        session: AsyncSession,
        encounter: Encounter,
        game: EncounterGame,
        home_score: int,
        away_score: int,
        actor_user_id: int,
        reason: str,
        outcome: engine.MapOutcome,
    ) -> list[int]:
        """A confirmed position changes hands: refuse if the tail has started,
        otherwise scrap the round it opened and open it again on the new
        outcome."""
        map_pick_ban = await self.sessions.get_pick_ban_session(session, encounter.id, PickBanKind.MAP)
        hero_pick_ban = await self.sessions.get_pick_ban_session(session, encounter.id, PickBanKind.HERO)
        # Either may be absent: freeplay has no map veto, and the hero session
        # only exists once a map has been picked.
        pick_bans = [pick_ban for pick_ban in (map_pick_ban, hero_pick_ban) if pick_ban is not None]
        if await self._downstream_started(session, encounter, game, pick_bans):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[
                    ApiExc(
                        code="downstream_started",
                        msg="Later maps already have actions or claims; correct them first or reset the series",
                    )
                ],
            )
        rebuilt = [
            game.position + 1
            for pick_ban in pick_bans
            if await self._rebuild_round(session, pick_ban, position=game.position)
        ]
        if map_pick_ban is not None:
            # The position the scrapped round had already opened: its map came
            # from a pick that no longer stands. Freeplay has no such pick, so
            # its planned position is left alone.
            stale = [
                row for row in await self.games.list_games(session, encounter.id) if row.position == game.position + 1
            ]
            if stale:
                await self.games.cancel_games(
                    session, encounter, stale, actor_user_id=actor_user_id, reason="correction_rebuild"
                )
        await session.flush()

        await self._accept(session, encounter, game, home_score, away_score, actor_user_id, reason)
        await self.reports.open_next_round(session, encounter, game, outcome)
        # The hero session's rounds follow the map's; re-opening one owes the
        # other the same catch-up the read path does.
        await self.sessions.sync_hero_rounds(session, encounter, commit=False)
        return sorted(set(rebuilt))


game_correction_service = GameCorrectionService()
