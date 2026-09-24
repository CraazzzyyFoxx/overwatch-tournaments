"""FFA lobbies: the one service that writes a lobby and its participants.

A lobby is an ``Encounter`` with ``format = 'ffa'`` and no sides: the teams sit
in ``tournament.encounter_participant`` instead of home/away
(docs/plans/2026-09-24-ffa-encounters.md §3, decisions 1 and 3).

A lobby's truth is its games: ``best_of`` is how many the lobby plans to play,
and every confirmed one keeps a row per participant in
``tournament.encounter_game_result``. So completion is derived, never set by
hand -- recording, correcting, cancelling a game and changing the planned count
all end in the same :meth:`FfaEncounterService.refresh_completion` (plan §5.4),
which is also what makes a reopen impossible to forget.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.enums import (
    EncounterFormat,
    EncounterGameResultSource,
    EncounterGameState,
    EncounterResultAuditAction,
    EncounterResultStatus,
    EncounterStatus,
)
from shared.core.errors import ApiExc
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain.encounter_format import ensure_format
from shared.domain.ffa_scoring import (
    FFA_MAX_LOBBY_SIZE,
    FfaGameLine,
    FfaResultError,
    FfaRules,
    game_points,
    normalize_game_lines,
    parse_ffa_rules,
    team_totals,
)
from shared.models.tournament.encounter_game_result import EncounterGameResult
from shared.models.tournament.encounter_participant import EncounterParticipant
from shared.repository import (
    EncounterGameRepository,
    EncounterGameResultRepository,
    EncounterParticipantRepository,
    EncounterRepository,
    EncounterResultAuditRepository,
)
from src import models
from src.schemas.ffa import (
    FfaGameCellRead,
    FfaLobbyRead,
    FfaLobbyRowRead,
    FfaRulesRead,
)
from src.services.tournament.events import (
    enqueue_encounter_completed,
    enqueue_tournament_recalculation,
)

__all__ = ("FfaEncounterService", "FfaStageResults", "ffa_encounter_service")


@dataclass(frozen=True, slots=True)
class FfaStageResults:
    """Every confirmed FFA result of one stage, grouped by group (stage item).

    The standings build a table per group, not per lobby, so both reads are
    keyed by ``stage_item_id``: the roster (a team with no games still has a
    row) and the games, oldest first.
    """

    participants: dict[int, list[int]] = field(default_factory=dict)
    games_by_item: dict[int, list[tuple[FfaGameLine, ...]]] = field(default_factory=dict)

    def participant_ids(self, stage_item_id: int) -> list[int]:
        return list(self.participants.get(stage_item_id, ()))

    def games(self, stage_item_id: int) -> list[tuple[FfaGameLine, ...]]:
        return list(self.games_by_item.get(stage_item_id, ()))


class FfaEncounterService:
    """FFA lobbies end to end: seating, per-game results, completion, reads.

    The ONLY writer of ``encounter_participant`` and ``encounter_game_result``:
    that is what keeps "participants exist only on ffa encounters" true without
    a cross-table CHECK (plan §3, decision 4).
    """

    def __init__(
        self,
        *,
        encounter_repo: EncounterRepository = EncounterRepository(),
        participant_repo: EncounterParticipantRepository = EncounterParticipantRepository(),
        game_repo: EncounterGameRepository = EncounterGameRepository(),
        result_repo: EncounterGameResultRepository = EncounterGameResultRepository(),
        audit_repo: EncounterResultAuditRepository = EncounterResultAuditRepository(),
    ) -> None:
        self.encounter_repo = encounter_repo
        self.participant_repo = participant_repo
        self.game_repo = game_repo
        self.result_repo = result_repo
        self.audit_repo = audit_repo

    async def create_lobby(
        self,
        session: AsyncSession,
        stage: models.Stage,
        item: models.StageItem,
        team_ids: Sequence[int],
        *,
        games: int,
    ) -> models.Encounter:
        """Seat ``team_ids`` (already in seed order) in a new lobby for ``item``."""
        if not 2 <= len(team_ids) <= FFA_MAX_LOBBY_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=[
                    ApiExc(
                        code="ffa_lobby_size",
                        msg=f"A lobby seats 2..{FFA_MAX_LOBBY_SIZE} participants; {item.name!r} has {len(team_ids)}",
                    )
                ],
            )
        lobby = models.Encounter(
            name=item.name,
            format=EncounterFormat.FFA,
            home_team_id=None,
            away_team_id=None,
            home_score=0,
            away_score=0,
            round=1,
            best_of=games,
            tournament_id=stage.tournament_id,
            stage_id=stage.id,
            stage_item_id=item.id,
            status=EncounterStatus.OPEN,
        )
        lobby.participants = [
            EncounterParticipant(team_id=team_id, slot=slot) for slot, team_id in enumerate(team_ids, 1)
        ]
        session.add(lobby)
        await session.flush()
        return lobby

    # -- commands ----------------------------------------------------------
    async def set_game_results(
        self,
        session: AsyncSession,
        encounter_id: int,
        position: int,
        lines: Sequence[FfaGameLine],
        *,
        actor_user_id: int | None,
        reason: str | None,
    ) -> models.Encounter:
        """Record (or correct) one game of a lobby and settle its completion.

        Commits, like ``CaptainService.set_encounter_result``: the result rows,
        the game's state, the lobby's completion and the journal row are one
        decision, and half of it is worse than none of it.
        """
        lobby = await self._lock_lobby(session, encounter_id)
        if not 1 <= position <= lobby.best_of:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[ApiExc(code="ffa_game_out_of_range", msg=f"This lobby plays games 1..{lobby.best_of}")],
            )
        participants = await self.participant_repo.list_for_encounter(session, lobby.id)
        try:
            normalized = normalize_game_lines(
                lines, [p.team_id for p in participants], await self._rules(session, lobby)
            )
        except FfaResultError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=[ApiExc(code=exc.code, msg=str(exc))]
            ) from exc

        game = await self._live_game(session, lobby, position)
        correcting = game.state == EncounterGameState.CONFIRMED
        if correcting and not reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[ApiExc(code="ffa_reason_required", msg="Correcting a confirmed game needs a reason")],
            )
        before = await self._snapshot(session, game)
        await self.result_repo.replace_for_game(session, game, normalized)
        now = datetime.now(UTC)
        game.state = EncounterGameState.CONFIRMED
        game.result_source = EncounterGameResultSource.ADMIN
        game.confirmed_at = now
        game.result_version = (game.result_version or 0) + 1
        lobby.started_at = lobby.started_at or now
        self._journal(
            session,
            lobby,
            action=EncounterResultAuditAction.GAME_CORRECT if correcting else EncounterResultAuditAction.GAME_CONFIRM,
            actor_user_id=actor_user_id,
            game=game,
            before=before,
            after=[{"team_id": i.team_id, "placement": i.placement, "score": i.score} for i in normalized],
            reason=reason,
        )
        await self.refresh_completion(session, lobby, actor_user_id=actor_user_id)
        await enqueue_tournament_recalculation(session, lobby.tournament_id)
        await session.commit()
        return lobby

    async def cancel_game(
        self,
        session: AsyncSession,
        encounter_id: int,
        position: int,
        *,
        actor_user_id: int | None,
        reason: str,
    ) -> models.Encounter:
        """Retire one game as history, freeing its position for a replay.

        The partial unique index on ``(encounter_id, position)`` skips cancelled
        rows, so the next result for this position is a NEW game -- the void one
        stays readable instead of being overwritten. Commits.
        """
        lobby = await self._lock_lobby(session, encounter_id)
        if not reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[ApiExc(code="ffa_reason_required", msg="Cancelling a game needs a reason")],
            )
        games = await self.game_repo.list_for_encounter(session, lobby.id)
        game = next((item for item in games if item.position == position), None)
        if game is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=[ApiExc(code="ffa_game_not_found", msg=f"This lobby has no live game {position}")],
            )
        before = await self._snapshot(session, game)
        was_confirmed = game.state == EncounterGameState.CONFIRMED
        game.state = EncounterGameState.CANCELLED
        if was_confirmed:
            self._journal(
                session,
                lobby,
                action=EncounterResultAuditAction.GAME_CANCEL,
                actor_user_id=actor_user_id,
                game=game,
                before=before,
                after=[],
                reason=reason,
            )
        await self.refresh_completion(session, lobby, actor_user_id=actor_user_id)
        await enqueue_tournament_recalculation(session, lobby.tournament_id)
        await session.commit()
        return lobby

    async def set_games_count(
        self,
        session: AsyncSession,
        encounter_id: int,
        games: int,
        *,
        actor_user_id: int | None,
    ) -> models.Encounter:
        """Change how many games THIS lobby plays. Commits.

        Never below what it already played: the games are the record, so a
        smaller number would silently drop confirmed results from the table.
        """
        lobby = await self._lock_lobby(session, encounter_id)
        live = await self.game_repo.list_for_encounter(session, lobby.id)
        confirmed = sum(item.state == EncounterGameState.CONFIRMED for item in live)
        # A lobby that plays no games at all is not a lobby, hence the floor of 1.
        if games < max(confirmed, 1):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=[
                    ApiExc(
                        code="ffa_games_below_played",
                        msg=f"This lobby has already played {confirmed} games",
                    )
                ],
            )
        lobby.best_of = games
        await self.refresh_completion(session, lobby, actor_user_id=actor_user_id)
        await enqueue_tournament_recalculation(session, lobby.tournament_id)
        await session.commit()
        return lobby

    async def refresh_completion(
        self,
        session: AsyncSession,
        encounter: models.Encounter,
        *,
        actor_user_id: int | None,
    ) -> None:
        """Settle "is this lobby finished?" from its live games. No commit.

        Both directions are here on purpose: whatever made the lobby stop
        qualifying -- a cancelled game, a raised games count -- must reopen it,
        or a lobby stays COMPLETED with a result it no longer holds.
        """
        games = await self.game_repo.list_for_encounter(session, encounter.id)
        confirmed = sum(game.state == EncounterGameState.CONFIRMED for game in games)
        complete = confirmed >= encounter.best_of
        if complete and encounter.status != EncounterStatus.COMPLETED:
            was = encounter.result_status
            now = datetime.now(UTC)
            encounter.status = EncounterStatus.COMPLETED
            encounter.result_status = EncounterResultStatus.CONFIRMED
            encounter.confirmed_at = now
            encounter.ended_at = now
            self._journal(
                session,
                encounter,
                action=EncounterResultAuditAction.CONFIRM,
                actor_user_id=actor_user_id,
                game=None,
                before=[],
                after=await self._totals_snapshot(session, encounter),
                from_result_status=was,
            )
            await enqueue_encounter_completed(session, encounter)
        elif not complete and encounter.status == EncounterStatus.COMPLETED:
            was = encounter.result_status
            totals = await self._totals_snapshot(session, encounter)
            encounter.status = EncounterStatus.OPEN
            encounter.result_status = EncounterResultStatus.NONE
            encounter.confirmed_at = None
            encounter.ended_at = None
            self._journal(
                session,
                encounter,
                action=EncounterResultAuditAction.REOPEN,
                actor_user_id=actor_user_id,
                game=None,
                before=totals,
                after=[],
                from_result_status=was,
            )

    # -- reads -------------------------------------------------------------
    async def load_stage_results(self, session: AsyncSession, stage_id: int) -> FfaStageResults:
        """One stage's rosters and confirmed games, grouped for the standings.

        Two queries for the whole stage, not two per lobby: the standings job
        rebuilds every group at once.
        """
        participants: dict[int, list[int]] = {}
        for row in await self.participant_repo.list_for_stage(session, stage_id):
            seats = participants.setdefault(row.stage_item_id, [])
            # A team seated in two lobbies of one group is still one competitor.
            if row.team_id not in seats:
                seats.append(row.team_id)

        grouped: dict[int, list[list[FfaGameLine]]] = {}
        current: tuple[int, int] | None = None
        for row in await self.result_repo.list_confirmed_for_stage(session, stage_id):
            bucket = grouped.setdefault(row.stage_item_id, [])
            key = (row.encounter_id, row.position)
            if key != current:
                current = key
                bucket.append([])
            bucket[-1].append(FfaGameLine(team_id=row.team_id, placement=row.placement, score=row.score))
        return FfaStageResults(
            participants=participants,
            games_by_item={
                item_id: [tuple(sorted(game, key=_line_order)) for game in bucket]
                for item_id, bucket in grouped.items()
            },
        )

    async def load_lobby(self, session: AsyncSession, encounter_id: int) -> FfaLobbyRead:
        """One lobby as the table it is: rules, seats, game cells, standing.

        404 for an unknown encounter, 409 for a duel -- a lobby table cannot be
        drawn from a series.
        """
        lobby = await session.get(models.Encounter, encounter_id)
        if lobby is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=[ApiExc(code="encounter_not_found", msg=f"Encounter {encounter_id} not found")],
            )
        ensure_format(lobby, EncounterFormat.FFA)
        stage = await session.get(models.Stage, lobby.stage_id) if lobby.stage_id else None
        return (await self._read_lobbies(session, [lobby], stage))[0]

    async def load_stage_lobbies(
        self, session: AsyncSession, stage_id: int, *, tournament_id: int
    ) -> list[FfaLobbyRead]:
        """Every lobby of one stage, in group order.

        ``tournament_id`` is the one the caller was cleared to see: a stage of
        another tournament reads as absent, or a hidden tournament's lobbies
        would be reachable through a public tournament's path.
        """
        stage = await session.get(models.Stage, stage_id)
        if stage is None or stage.tournament_id != tournament_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=[ApiExc(code="stage_not_found", msg=f"Stage {stage_id} not found")],
            )
        rows = await session.execute(
            sa.select(models.Encounter)
            .outerjoin(models.StageItem, models.StageItem.id == models.Encounter.stage_item_id)
            .where(
                models.Encounter.stage_id == stage_id,
                models.Encounter.format == EncounterFormat.FFA,
            )
            .order_by(models.StageItem.order.nulls_last(), models.Encounter.id)
        )
        return await self._read_lobbies(session, list(rows.scalars()), stage)

    async def is_participant_captain(
        self, session: AsyncSession, auth_user: models.AuthUser, encounter: models.Encounter
    ) -> bool:
        """Does this account captain a team SEATED in this lobby?

        The lobby has no sides, so the duel question ("are you home or away?")
        has no answer here -- the participant rows are the whole roster.
        """
        return bool(
            await session.scalar(
                sa.select(
                    sa.exists()
                    .where(EncounterParticipant.encounter_id == encounter.id)
                    .where(models.Team.id == EncounterParticipant.team_id)
                    .where(models.User.id == models.Team.captain_id)
                    .where(models.User.auth_user_id == auth_user.id)
                )
            )
        )

    async def _read_lobbies(
        self,
        session: AsyncSession,
        lobbies: Sequence[models.Encounter],
        stage: models.Stage | None,
    ) -> list[FfaLobbyRead]:
        """Build the read model for a whole stage in a fixed number of queries.

        A stage read is one page of the tournament, so the seats, games,
        results, teams and standings of EVERY lobby are fetched once each
        instead of per lobby.
        """
        if not lobbies:
            return []
        rules = parse_ffa_rules(stage.settings_json if stage else None)
        # ``score_label`` is presentation, not arithmetic, so it never entered
        # ``FfaRules``; the read is the one place that needs it.
        rules_read = FfaRulesRead(
            placement_points=list(rules.placement_points),
            score_points=rules.score_points,
            score_label=(((stage.settings_json or {}) if stage else {}).get("ffa_scoring") or {}).get("score_label"),
        )

        lobby_ids = [lobby.id for lobby in lobbies]
        seats: dict[int, list[EncounterParticipant]] = {lobby_id: [] for lobby_id in lobby_ids}
        for seat in (
            await session.execute(
                sa.select(EncounterParticipant)
                .where(EncounterParticipant.encounter_id.in_(lobby_ids))
                .order_by(EncounterParticipant.encounter_id, EncounterParticipant.slot)
            )
        ).scalars():
            seats[seat.encounter_id].append(seat)

        # Cancelled games are history: the position they held is free again
        # (the partial unique index says so), so the cell must read as unplayed.
        games: dict[int, list[models.EncounterGame]] = {lobby_id: [] for lobby_id in lobby_ids}
        for game in (
            await session.execute(
                sa.select(models.EncounterGame)
                .where(
                    models.EncounterGame.encounter_id.in_(lobby_ids),
                    models.EncounterGame.state != EncounterGameState.CANCELLED,
                )
                .order_by(models.EncounterGame.encounter_id, models.EncounterGame.position)
            )
        ).scalars():
            games[game.encounter_id].append(game)

        game_ids = [game.id for lobby_games in games.values() for game in lobby_games]
        lines: dict[int, dict[int, FfaGameLine]] = {game_id: {} for game_id in game_ids}
        for row in await self.result_repo.list_for_games(session, game_ids):
            lines[row.game_id][row.team_id] = FfaGameLine(team_id=row.team_id, placement=row.placement, score=row.score)

        team_ids = [seat.team_id for lobby_seats in seats.values() for seat in lobby_seats]
        teams = {
            row.id: row
            for row in (
                await session.execute(
                    sa.select(models.Team.id, models.Team.name, models.Team.image_url).where(
                        models.Team.id.in_(team_ids)
                    )
                )
            ).all()
        }

        item_ids = [lobby.stage_item_id for lobby in lobbies if lobby.stage_item_id is not None]
        ranked = {
            (row.stage_item_id, row.team_id): row
            for row in (
                await session.execute(
                    sa.select(
                        models.Standing.stage_item_id,
                        models.Standing.team_id,
                        models.Standing.position,
                        models.Standing.tie_group,
                    ).where(models.Standing.stage_item_id.in_(item_ids), models.Standing.team_id.in_(team_ids))
                )
            ).all()
        }
        advance = {
            row.id: row.advance_count
            for row in (
                await session.execute(
                    sa.select(models.StageItem.id, models.StageItem.advance_count).where(
                        models.StageItem.id.in_(item_ids)
                    )
                )
            ).all()
        }

        return [
            self._read_lobby(
                lobby, seats[lobby.id], games[lobby.id], lines, teams, ranked, advance, stage, rules, rules_read
            )
            for lobby in lobbies
        ]

    def _read_lobby(
        self,
        lobby: models.Encounter,
        seats: Sequence[EncounterParticipant],
        games: Sequence[models.EncounterGame],
        lines: dict[int, dict[int, FfaGameLine]],
        teams: dict[int, sa.Row],
        ranked: dict[tuple[int, int], sa.Row],
        advance: dict[int, int | None],
        stage: models.Stage | None,
        rules: FfaRules,
        rules_read: FfaRulesRead,
    ) -> FfaLobbyRead:
        by_position = {game.position: game for game in games}
        # Normally 1..best_of, but a lowered games count must never hide a
        # result that was already recorded past the new end.
        last = max([lobby.best_of, *by_position], default=lobby.best_of)
        totals = team_totals(
            [seat.team_id for seat in seats],
            [
                tuple(sorted(lines[game.id].values(), key=_line_order))
                for game in games
                if game.state == EncounterGameState.CONFIRMED
            ],
            rules,
        )
        item_advance = advance.get(lobby.stage_item_id) if lobby.stage_item_id is not None else None
        rows = []
        for seat in seats:
            total = totals[seat.team_id]
            team = teams[seat.team_id]
            standing = ranked.get((lobby.stage_item_id, seat.team_id))
            rows.append(
                FfaLobbyRowRead(
                    team_id=seat.team_id,
                    team_name=team.name,
                    team_image_url=team.image_url,
                    slot=seat.slot,
                    position=standing.position if standing is not None else None,
                    tie_group=standing.tie_group if standing is not None else None,
                    points=total.points,
                    games_played=total.games,
                    wins=total.wins,
                    score=total.score,
                    games=[
                        self._read_cell(position, by_position.get(position), lines, seat.team_id, rules)
                        for position in range(1, last + 1)
                    ],
                )
            )
        # Rank order, then seat order for whatever the standings have not ranked.
        rows.sort(key=lambda row: (row.position is None, row.position or 0, row.slot))
        return FfaLobbyRead(
            encounter_id=lobby.id,
            tournament_id=lobby.tournament_id,
            stage_id=lobby.stage_id,
            stage_item_id=lobby.stage_item_id,
            name=lobby.name,
            status=lobby.status,
            result_status=lobby.result_status,
            best_of=lobby.best_of,
            scheduled_at=lobby.scheduled_at,
            advance_count=item_advance if item_advance is not None else (stage.advance_count if stage else None),
            rules=rules_read,
            rows=rows,
        )

    @staticmethod
    def _read_cell(
        position: int,
        game: models.EncounterGame | None,
        lines: dict[int, dict[int, FfaGameLine]],
        team_id: int,
        rules: FfaRules,
    ) -> FfaGameCellRead:
        line = lines.get(game.id, {}).get(team_id) if game is not None else None
        return FfaGameCellRead(
            position=position,
            state=game.state if game is not None else None,
            placement=line.placement if line is not None else None,
            score=line.score if line is not None else None,
            points=game_points(line, rules) if line is not None else None,
        )

    # -- internals ---------------------------------------------------------
    async def _lock_lobby(self, session: AsyncSession, encounter_id: int) -> models.Encounter:
        """The lobby, locked for this transaction. 404 unknown, 409 not a lobby."""
        lobby = await self.encounter_repo.get_for_update(session, encounter_id)
        if lobby is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=[ApiExc(code="encounter_not_found", msg=f"Encounter {encounter_id} not found")],
            )
        ensure_format(lobby, EncounterFormat.FFA)
        return lobby

    async def _live_game(self, session: AsyncSession, lobby: models.Encounter, position: int) -> models.EncounterGame:
        """The live game of ``position``, opening it if this is its first result."""
        games = await self.game_repo.list_for_encounter(session, lobby.id)
        game = next((item for item in games if item.position == position), None)
        if game is not None:
            return game
        return await self.game_repo.create(
            session,
            models.EncounterGame(
                encounter_id=lobby.id,
                position=position,
                format=EncounterFormat.FFA,
                state=EncounterGameState.PLANNED,
            ),
        )

    async def _rules(self, session: AsyncSession, lobby: models.Encounter) -> FfaRules:
        stage = await session.get(models.Stage, lobby.stage_id) if lobby.stage_id else None
        return parse_ffa_rules(stage.settings_json if stage else None)

    async def _snapshot(self, session: AsyncSession, game: models.EncounterGame) -> list[dict]:
        """A game's current result rows, in table order. ``[]`` for a fresh position."""
        if game.id is None:
            return []
        rows = await self.result_repo.list_for_games(session, [game.id])
        return [
            {"team_id": row.team_id, "placement": row.placement, "score": row.score}
            for row in sorted(rows, key=_line_order)
        ]

    async def _confirmed_games(self, session: AsyncSession, lobby: models.Encounter) -> list[tuple[FfaGameLine, ...]]:
        """The lobby's confirmed games, oldest position first."""
        games = [
            game
            for game in await self.game_repo.list_for_encounter(session, lobby.id)
            if game.state == EncounterGameState.CONFIRMED
        ]
        by_game: dict[int, list[FfaGameLine]] = {game.id: [] for game in games}
        for row in await self.result_repo.list_for_games(session, list(by_game)):
            by_game[row.game_id].append(FfaGameLine(team_id=row.team_id, placement=row.placement, score=row.score))
        return [tuple(sorted(by_game[game.id], key=_line_order)) for game in games]

    async def _totals_snapshot(self, session: AsyncSession, lobby: models.Encounter) -> list[dict]:
        """What the lobby decided, for the journal: points and games per team."""
        participants = await self.participant_repo.list_for_encounter(session, lobby.id)
        totals = team_totals(
            [p.team_id for p in participants],
            await self._confirmed_games(session, lobby),
            await self._rules(session, lobby),
        )
        return [{"team_id": row.team_id, "points": row.points, "games": row.games} for row in totals.values()]

    def _journal(
        self,
        session: AsyncSession,
        lobby: models.Encounter,
        *,
        action: EncounterResultAuditAction,
        actor_user_id: int | None,
        game: models.EncounterGame | None,
        before: list[dict],
        after: list[dict],
        reason: str | None = None,
        from_result_status: EncounterResultStatus | None = None,
    ) -> models.EncounterResultAudit:
        """Append one lobby decision to the shared encounter journal.

        Private, not a ``shared/services`` helper: one service writes these rows
        (backend/ARCHITECTURE.md:134-143). A lobby has no series score, so the
        ``*_score_*`` columns stay NULL and the snapshot carries the truth --
        which is exactly what ``ck_encounter_result_audit_after_shape`` demands.
        """
        return self.audit_repo.add(
            session,
            models.EncounterResultAudit(
                encounter_id=lobby.id,
                actor_user_id=actor_user_id,
                action=action,
                from_result_status=lobby.result_status if from_result_status is None else from_result_status,
                to_result_status=lobby.result_status,
                home_score_before=None,
                away_score_before=None,
                home_score_after=None,
                away_score_after=None,
                ffa_results_json={"before": before, "after": after},
                game_id=game.id if game is not None else None,
                game_result_version=game.result_version if game is not None else None,
                reason=reason,
                source="admin",
            ),
        )


def _line_order(line: FfaGameLine | EncounterGameResult) -> tuple[int, int]:
    """Best place first, ties by team -- the order results are read back in."""
    return (line.placement or 0, line.team_id)


ffa_encounter_service = FfaEncounterService()
