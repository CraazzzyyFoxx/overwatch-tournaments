"""The series' games: one row per position, its accepted result, and the live
score derived from them.

A ``Match`` (``matches.match``) is what a parsed log OBSERVED; an
``EncounterGame`` is what the tournament DECIDED for one position. This service
owns that decision end to end -- opening positions (from the map pick-ban, or
one at a time in freeplay), accepting a score, cancelling, and materialising the
running series score onto ``Encounter.home_score``/``away_score``.

The materialisation is LIVE only: once ``encounter.status`` is ``COMPLETED`` the
official finalize (``shared/services/encounter/finalize.py``) is the sole writer
of the encounter's score, so everything here leaves it alone. See
docs/plans/2026-09-20-pregame-results-statistics-separation.md §5.1/§5.2/§6.3.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import (
    EncounterGameResultSource,
    EncounterGameState,
    EncounterResultAuditAction,
    EncounterStatus,
)
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain import pick_ban_engine as engine
from shared.models.tournament.encounter import Encounter
from shared.models.tournament.encounter_game import EncounterGame
from shared.models.tournament.encounter_report import EncounterMapReport
from shared.models.tournament.pick_ban import PickBanSession
from shared.repository import (
    EncounterGameRepository,
    EncounterMapReportRepository,
    PickBanEntryRepository,
)
from shared.services.encounter.game_audit import record_game_result_transition

# States a game can still move out of. `cancelled` is terminal history and
# `confirmed` only moves via the admin correction command.
OPEN_STATES = (
    EncounterGameState.PLANNED,
    EncounterGameState.AWAITING_RESULT,
    EncounterGameState.DISPUTED,
)


class EncounterGameService:
    """Game lifecycle + the live series score. The only writer of
    ``encounter_game`` and of the encounter score before official finalize."""

    def __init__(
        self,
        *,
        game_repo: EncounterGameRepository = EncounterGameRepository(),
        report_repo: EncounterMapReportRepository = EncounterMapReportRepository(),
        entry_repo: PickBanEntryRepository = PickBanEntryRepository(),
    ) -> None:
        self.game_repo = game_repo
        self.report_repo = report_repo
        self.entry_repo = entry_repo

    # -- reads ------------------------------------------------------------
    async def list_games(self, session: AsyncSession, encounter_id: int) -> list[EncounterGame]:
        """The LIVE games (cancelled excluded) in series order."""
        games = await self.game_repo.list_for_encounter(session, encounter_id)
        return sorted(games, key=lambda game: (game.position, game.id or 0))

    async def reports_by_game(
        self, session: AsyncSession, games: Sequence[EncounterGame]
    ) -> dict[int, list[EncounterMapReport]]:
        """Captain claims grouped by game id; every given game gets a key."""
        grouped: dict[int, list[EncounterMapReport]] = {game.id: [] for game in games}
        rows = await self.report_repo.list_for_games(session, [game.id for game in games])
        for row in rows:
            grouped.setdefault(row.game_id, []).append(row)
        return grouped

    # -- opening positions -------------------------------------------------
    async def sync_games_with_picks(
        self, session: AsyncSession, encounter: Encounter, map_pick_ban: PickBanSession
    ) -> list[EncounterGame]:
        """Make the live games mirror the map session's settled picks.

        Never touches a confirmed game: an undo that would strand one is refused
        upstream, so reaching here means the tail is still unplayed.
        """
        entries = list(await self.entry_repo.list_by_session(session, map_pick_ban.id))
        settled = engine.settled_in_order(entries)
        games = await self.list_games(session, encounter.id)
        reports = await self.reports_by_game(session, games)
        by_position = {game.position: game for game in games}

        for position, entry in enumerate(settled, 1):
            game = by_position.get(position)
            if game is None:
                await self.game_repo.create(
                    session,
                    EncounterGame(
                        encounter_id=encounter.id,
                        position=position,
                        map_id=entry.item_id,
                        state=EncounterGameState.AWAITING_RESULT,
                    ),
                )
                continue
            if (
                game.map_id != entry.item_id
                and game.state in (EncounterGameState.PLANNED, EncounterGameState.AWAITING_RESULT)
                and not reports.get(game.id)
            ):
                game.map_id = entry.item_id
                if game.state == EncounterGameState.PLANNED:
                    # A pick names the map a freeplay position was still missing.
                    game.state = EncounterGameState.AWAITING_RESULT

        stale = [
            game
            for game in games
            if game.position > len(settled)
            and game.state != EncounterGameState.CONFIRMED
            and not reports.get(game.id)
        ]
        if stale:
            await self.cancel_games(session, encounter, stale, actor_user_id=None, reason="pick_undone")
        await session.flush()
        return await self.list_games(session, encounter.id)

    async def ensure_freeplay_game(self, session: AsyncSession, encounter: Encounter) -> EncounterGame | None:
        """The position captains should be reporting right now, opening a new one
        if the series has room. ``None`` once the series is decided."""
        games = await self.list_games(session, encounter.id)
        if engine.series_complete(self.live_score(games), encounter.best_of):
            return None
        open_game = next((game for game in games if game.state in OPEN_STATES), None)
        if open_game is not None:
            return open_game
        if len(games) >= encounter.best_of:
            return None
        return await self.game_repo.create(
            session,
            EncounterGame(
                encounter_id=encounter.id,
                position=max((game.position for game in games), default=0) + 1,
                state=EncounterGameState.PLANNED,
            ),
        )

    # -- the score ---------------------------------------------------------
    def live_score(self, games: Sequence[EncounterGame]) -> engine.SeriesScore:
        """Wins over confirmed positions. A draw is played but won by nobody."""
        return engine.series_score(
            (game.accepted_home_score, game.accepted_away_score)
            for game in games
            if game.state == EncounterGameState.CONFIRMED
        )

    def materialize_series_score(self, encounter: Encounter, games: Sequence[EncounterGame]) -> None:
        """Mirror the live score onto the encounter — only while it is unofficial."""
        if encounter.status == EncounterStatus.COMPLETED:
            return
        score = self.live_score(games)
        encounter.home_score, encounter.away_score = score.home_wins, score.away_wins

    # -- commands ----------------------------------------------------------
    async def accept_result(
        self,
        session: AsyncSession,
        encounter: Encounter,
        game: EncounterGame,
        *,
        home_score: int,
        away_score: int,
        source: EncounterGameResultSource,
        actor_user_id: int | None,
        reason: str | None = None,
    ) -> EncounterGame:
        """Write one position's accepted score. First write confirms it; a later
        one is a correction — both bump ``result_version`` and journal a row."""
        before = (game.accepted_home_score, game.accepted_away_score)
        game.accepted_home_score = home_score
        game.accepted_away_score = away_score
        game.result_source = source
        game.confirmed_at = datetime.now(UTC)
        game.state = EncounterGameState.CONFIRMED
        game.result_version = (game.result_version or 0) + 1
        record_game_result_transition(
            session,
            encounter,
            game,
            action=(
                EncounterResultAuditAction.GAME_CONFIRM
                if before == (None, None)
                else EncounterResultAuditAction.GAME_CORRECT
            ),
            source=source.value,
            actor_user_id=actor_user_id,
            home_score_before=before[0],
            away_score_before=before[1],
            reason=reason,
        )
        self.materialize_series_score(encounter, await self.list_games(session, encounter.id))
        await session.flush()
        return game

    async def select_map(
        self, session: AsyncSession, encounter: Encounter, game: EncounterGame, *, map_id: int
    ) -> EncounterGame:
        """Name the map a live position is played on (freeplay's half of what the
        pick-ban does automatically)."""
        if game.state not in OPEN_STATES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[ApiExc(code="result_locked", msg="This game's result is already settled")],
            )
        reports = (await self.reports_by_game(session, [game])).get(game.id) or []
        if reports and game.map_id != map_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=[ApiExc(code="map_locked", msg="A captain already reported this map; it cannot be changed")],
            )
        game.map_id = map_id
        if game.state == EncounterGameState.PLANNED:
            game.state = EncounterGameState.AWAITING_RESULT
        await session.flush()
        return game

    async def cancel_games(
        self,
        session: AsyncSession,
        encounter: Encounter,
        games: Sequence[EncounterGame],
        *,
        actor_user_id: int | None,
        reason: str,
    ) -> None:
        """Retire positions as history. A cancelled confirmed game loses its wins
        from the live score, so the journal has to say who dropped them."""
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
        self.materialize_series_score(encounter, await self.list_games(session, encounter.id))
        await session.flush()

    # -- serialization -----------------------------------------------------
    def serialize(self, game: EncounterGame, reports: Sequence[EncounterMapReport]) -> dict[str, Any]:
        return {
            "id": game.id,
            "position": game.position,
            "map_id": game.map_id,
            "state": game.state.value if game.state is not None else None,
            "accepted_home_score": game.accepted_home_score,
            "accepted_away_score": game.accepted_away_score,
            "result_source": game.result_source.value if game.result_source is not None else None,
            "result_version": game.result_version,
            "confirmed_at": game.confirmed_at.isoformat() if game.confirmed_at is not None else None,
            "reports": [
                {"side": report.side, "home_score": report.home_score, "away_score": report.away_score}
                for report in sorted(reports, key=lambda report: report.side != "home")
            ],
        }

    def serialize_series(self, encounter: Encounter, games: Sequence[EncounterGame]) -> dict[str, Any]:
        score = self.live_score(games)
        return {
            "home_wins": score.home_wins,
            "away_wins": score.away_wins,
            "played": score.played,
            "complete": engine.series_complete(score, encounter.best_of),
            "official": (
                {"home_score": encounter.home_score, "away_score": encounter.away_score}
                if encounter.status == EncounterStatus.COMPLETED
                else None
            ),
        }


encounter_game_service = EncounterGameService()
