"""Per-game result confirmation: two independent captain claims for ONE
position of a series, reconciled the moment both arrive.

This is what the pick-ban engine's progressive rounds wait on — nothing else in
the system reports "this map just finished" mid-series (``EncounterCaptainReport``
only fires once, at series end). Agreement accepts the position's result on its
``EncounterGame`` (``EncounterGameService.accept_result``, which is what moves
the live series score) and opens the next map's bans; disagreement marks the
game ``disputed`` and leaves both claims standing for an admin.

No ``matches.match`` row is written here, and none is read: that table records
what a parsed log OBSERVED, while an ``EncounterGame`` records what the
tournament DECIDED
(docs/plans/2026-09-20-pregame-results-statistics-separation.md §5.1/§5.2). That
also retires the scrim carve-out — a scrim ran this loop for the progression
only, and there is no longer any bookkeeping beside the progression to skip.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import EncounterGameResultSource, EncounterGameState, PickBanKind
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain import pick_ban_engine as engine
from shared.models.identity.user import User
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.encounter_report import EncounterMapReport
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament
from shared.repository import EncounterMapReportRepository
from shared.services.bracket.usability import is_encounter_live
from shared.services.notifications import notify
from shared.services.realtime import Resource, Scope, emit
from src.services.encounter.games import EncounterGameService, encounter_game_service
from src.services.encounter.pick_ban_session import pick_ban_session_service
from src.services.encounter.realtime_commit import emit_pick_ban_update


class MapReportService:
    """The mid-series, per-game half of captain reporting."""

    def __init__(
        self,
        *,
        report_repo: EncounterMapReportRepository = EncounterMapReportRepository(),
        games: EncounterGameService = encounter_game_service,
    ) -> None:
        self.report_repo = report_repo
        self.games = games

    async def _notify_dispute(
        self,
        session: AsyncSession,
        encounter: Encounter,
        *,
        game: EncounterGame,
        reporter_auth_user_id: int | None,
    ) -> None:
        """Both captains, not just the opponent.

        A contradiction needs one of the two to correct their claim, and from
        inside the reconciliation neither side is known to be the wrong one -- the
        captain who just reported has as much to answer for as the one who
        reported first. Telling only the opponent would leave the report standing
        unexamined on the half that may be mistaken.

        One query for the pair, not one per side; a team with no captain, or one
        captained by a shadow player (``players.user.auth_user_id IS NULL``),
        simply drops out of the result.
        """
        result = await session.execute(
            sa.select(User.auth_user_id)
            .join(Team, Team.captain_id == User.id)
            .where(
                Team.id.in_([encounter.home_team_id, encounter.away_team_id]),
                User.auth_user_id.is_not(None),
            )
        )
        recipients = [int(value) for value in result.scalars().all()]
        # The organizer whose bracket this encounter belongs to: it owns the
        # rows, so its operators can retire them. One scalar, and only on the
        # dispute branch -- ``Encounter`` carries the tournament, not the tenant.
        workspace_id = await session.scalar(
            sa.select(Tournament.workspace_id).where(Tournament.id == encounter.tournament_id)
        )
        for recipient in recipients:
            await notify(
                session,
                kind="encounter.report_disputed",
                recipient_auth_user_id=recipient,
                source_workspace_id=int(workspace_id) if workspace_id is not None else None,
                actor_auth_user_id=reporter_auth_user_id,
                payload={
                    "encounter_id": encounter.id,
                    "tournament_id": encounter.tournament_id,
                    "game_id": game.id,
                    "position": game.position,
                    "map_id": game.map_id,
                },
            )

    async def submit_map_report(
        self,
        session: AsyncSession,
        encounter: Encounter,
        *,
        game_id: int,
        side: str,
        reporter_user_id: int | None,
        home_score: int,
        away_score: int,
    ) -> dict:
        """Upsert ``side``'s claim for one game; reconcile if both sides have now
        claimed. Returns ``{"disputed": bool, "resolved": bool, "game": dict}``.

        The claim targets a GAME, never a map: a series may play the same map
        twice, and only the position tells the two plays apart.
        """
        if not await is_encounter_live(session, encounter):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Stage bracket is a preview and is not active yet; wait for the organizer to activate it",
            )
        # Locked: two captains filing at once both reconcile against the pair of
        # claims, and the second one is what accepts the result.
        game = await self.games.game_repo.get_for_update(session, game_id)
        if game is None or game.encounter_id != encounter.id or game.state == EncounterGameState.CANCELLED:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Game not found")
        if game.state == EncounterGameState.CONFIRMED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[
                    ApiExc(
                        code="result_locked",
                        msg="This map's result is already accepted; ask an organizer to correct it",
                    )
                ],
            )
        if game.map_id is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[ApiExc(code="map_not_selected", msg="Choose this map before reporting its result")],
            )

        # Both sides of the position in ONE read: reconciliation needs the
        # opponent's row anyway, and it cannot change under us inside this
        # transaction.
        reports = list(await self.report_repo.list_for_games(session, [game.id]))
        row = next((report for report in reports if report.side == side), None)
        other = next((report for report in reports if report.side != side), None)
        if row is None:
            # Built complete: `home_score`/`away_score` are NOT NULL, so a row
            # created bare and filled in afterwards fails on the create's flush.
            row = await self.report_repo.create(
                session,
                EncounterMapReport(
                    game_id=game.id,
                    side=side,
                    reporter_user_id=reporter_user_id,
                    home_score=home_score,
                    away_score=away_score,
                ),
            )
            reports.append(row)
        else:
            row.reporter_user_id = reporter_user_id
            row.home_score = home_score
            row.away_score = away_score
        # Unconditional, on both branches below: the opponent's tile only flips
        # from "not reported" to "sealed" on this signal, and the FIRST
        # captain's claim -- the one that resolves nothing -- is exactly the
        # case that used to commit silently. Both topics, because the room
        # refetches map and hero state together: two phases of one loop.
        await emit_pick_ban_update(session, encounter.id)
        await emit_pick_ban_update(session, encounter.id, kind=PickBanKind.HERO.value)
        await session.flush()

        mine = (row.home_score, row.away_score)
        theirs = (other.home_score, other.away_score) if other is not None else None
        pair = engine.MapReportPair(
            home_report=mine if side == "home" else theirs,
            away_report=mine if side == "away" else theirs,
        )
        reconciliation = engine.reconcile_map_reports(pair)

        if reconciliation.resolved is None:
            if reconciliation.disputed:
                game.state = EncounterGameState.DISPUTED
                await self._notify_dispute(session, encounter, game=game, reporter_auth_user_id=reporter_user_id)
            await session.commit()
            return {
                "disputed": reconciliation.disputed,
                "resolved": False,
                "game": self.games.serialize(game, reports),
            }

        resolved_home, resolved_away = reconciliation.resolved
        # The service owns the accepted score AND the live series score, so the
        # win is counted exactly once however often this position is re-claimed.
        await self.games.accept_result(
            session,
            encounter,
            game,
            home_score=resolved_home,
            away_score=resolved_away,
            source=EncounterGameResultSource.CAPTAIN_AGREEMENT,
            actor_user_id=None,
        )

        await self.open_next_round(session, encounter, game, engine.map_outcome(resolved_home, resolved_away))

        # Unlike a veto/ban, an AGREED claim moves the encounter's own score --
        # the public encounter read is stale the moment this commits.
        await emit(
            session,
            scope=Scope.tournament(encounter.tournament_id),
            invalidates=[Resource.TOURNAMENT_ENCOUNTERS],
            entity_ids={"encounter_ids": [encounter.id]},
        )
        await session.commit()
        return {"disputed": False, "resolved": True, "game": self.games.serialize(game, reports)}

    async def open_next_round(
        self,
        session: AsyncSession,
        encounter: Encounter,
        game: EncounterGame,
        outcome: engine.MapOutcome,
    ) -> None:
        """Open whatever the series owes after ``game``'s position was accepted.

        Shared by captain agreement and by the admin correction: both settle ONE
        position, and "what comes next" is a property of the series, not of who
        settled it.
        """
        map_pick_ban = await pick_ban_session_service.get_pick_ban_session(session, encounter.id, PickBanKind.MAP)
        if map_pick_ban is None:
            # Freeplay: no veto to open a round, so the next position is opened
            # directly (and not at all once the series is decided).
            await self.games.ensure_freeplay_game(session, encounter)
            return
        # Only the MAP session advances here, and only while the series still has
        # a map to play: the next map's bans open on this result. That map's HERO
        # round opens later, once the map itself is picked --
        # `pick_ban_session.sync_hero_rounds`, because heroes are banned for a
        # known map, not for a map that is still being vetoed.
        games = await self.games.list_games(session, encounter.id)
        if engine.series_complete(self.games.live_score(games), encounter.best_of):
            return
        try:
            await pick_ban_session_service.advance_to_next_round(
                session, map_pick_ban, completed_round=game.position, outcome=outcome, commit=False
            )
        except engine.RotationNeedsChoice:
            map_pick_ban.awaiting_choice = True
            map_pick_ban.pending_loser_side = "away" if outcome == "home" else "home"
            await session.flush()


map_report_service = MapReportService()
